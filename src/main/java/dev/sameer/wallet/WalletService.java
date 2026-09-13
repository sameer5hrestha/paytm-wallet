package dev.sameer.wallet;

import java.util.*;
import java.time.OffsetDateTime;
import jakarta.validation.constraints.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.LoggerFactory;

@Service
public class WalletService {
    public record Wallet(UUID id, UUID user_id, long balance_paise) {}
    public record TransferRequest(@NotNull UUID from, @NotNull UUID to,
            @NotNull @Positive Long amount_paise,
            @NotBlank @Pattern(regexp="[A-Za-z0-9._:-]{1,128}") String idempotency_key) {}
    public record Transfer(UUID id, UUID from, UUID to, long amount_paise, String idempotency_key,
                           String status, String reason, OffsetDateTime created_at) {}
    private record Outcome(Transfer transfer, boolean replay) {}
    private static final RowMapper<Wallet> WALLET = (rs, n) -> new Wallet(rs.getObject("id", UUID.class), rs.getObject("user_id", UUID.class), rs.getLong("balance_paise"));
    private static final RowMapper<Transfer> TRANSFER = (rs, n) -> new Transfer(rs.getObject("id", UUID.class), rs.getObject("from_wallet", UUID.class), rs.getObject("to_wallet", UUID.class), rs.getLong("amount_paise"), rs.getString("idempotency_key"), rs.getString("status"), rs.getString("reason"), rs.getObject("created_at", OffsetDateTime.class));
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final MeterRegistry metrics;
    private final PublicEventLog publicLogs;
    WalletService(JdbcTemplate db, PlatformTransactionManager manager, MeterRegistry metrics, PublicEventLog publicLogs) {
        this.publicLogs = publicLogs;
        this.db = db; this.metrics = metrics; tx = new TransactionTemplate(manager);
        tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_READ_COMMITTED);
        tx.setTimeout(15);
        for (String counter : List.of("wallet.transfers.recorded", "wallet.transfers.completed", "wallet.transfers.declined.insufficient.funds", "wallet.transfers.declined.balance.limit", "wallet.idempotent.replays")) metrics.counter(counter);
    }
    private void limits() { db.execute("SET LOCAL lock_timeout = '5s'"); db.execute("SET LOCAL statement_timeout = '10s'"); }
    public Wallet getOrCreate(UUID user) {
        return tx.execute(s -> {
            limits();
            db.update("INSERT INTO wallets(id,user_id,balance_paise) SELECT ?,id,opening_balance_paise FROM app_users WHERE id=? ON CONFLICT(user_id) DO NOTHING", UUID.randomUUID(), user);
            return db.queryForObject("SELECT * FROM wallets WHERE user_id=?", WALLET, user);
        });
    }
    public Wallet wallet(UUID id, UUID user) {
        Wallet w = findWallet(id);
        if (!w.user_id().equals(user)) throw new ApiError(403, "FORBIDDEN");
        return w;
    }
    private Wallet findWallet(UUID id) {
        var rows = db.query("SELECT * FROM wallets WHERE id=?", WALLET, id);
        if (rows.isEmpty()) throw new ApiError(404, "WALLET_NOT_FOUND");
        return rows.get(0);
    }
    public Transfer transfer(UUID id, UUID user) {
        var rows = db.query("SELECT t.* FROM transfers t JOIN wallets a ON a.id=t.from_wallet JOIN wallets b ON b.id=t.to_wallet WHERE t.id=? AND (a.user_id=? OR b.user_id=?)", TRANSFER, id, user, user);
        if (rows.isEmpty()) throw new ApiError(404, "TRANSFER_NOT_FOUND");
        return rows.get(0);
    }
    public Transfer send(UUID user, TransferRequest request) {
        Outcome result = tx.execute(s -> execute(user, request));
        Transfer t = result.transfer();
        // These events represent committed results; rolled-back attempts emit no money-movement events.
        if (result.replay()) { metrics.counter("wallet.idempotent.replays").increment(); event("idempotent_replay_hit", t); }
        else {
            metrics.counter("wallet.transfers.recorded").increment(); event("transfer_created", t);
            if (t.status().equals("COMPLETED")) {
                metrics.counter("wallet.transfers.completed").increment(); event("debited", t); event("credited", t);
            } else {
                metrics.counter(t.reason().equals("INSUFFICIENT_FUNDS") ? "wallet.transfers.declined.insufficient.funds" : "wallet.transfers.declined.balance.limit").increment();
                event("declined", t);
            }
        }
        return t;
    }
    private Outcome execute(UUID user, TransferRequest r) {
        limits();
        // Check committed replays before validation dependent on mutable wallet state.
        var existing = db.query("SELECT * FROM transfers WHERE user_id=? AND idempotency_key=?", TRANSFER, user, r.idempotency_key());
        if (!existing.isEmpty()) return replay(existing.get(0), r);
        if (r.from().equals(r.to())) throw new ApiError(400, "SELF_TRANSFER_NOT_ALLOWED");
        wallet(r.from(), user); findWallet(r.to());
        UUID id = UUID.randomUUID();
        int inserted = db.update("INSERT INTO transfers(id,user_id,idempotency_key,from_wallet,to_wallet,amount_paise,status) VALUES(?,?,?,?,?,?,'PENDING') ON CONFLICT(user_id,idempotency_key) DO NOTHING", id, user, r.idempotency_key(), r.from(), r.to(), r.amount_paise());
        if (inserted == 0) {
            // Under READ COMMITTED this new statement sees the winner after uniqueness waited for commit.
            return replay(db.queryForObject("SELECT * FROM transfers WHERE user_id=? AND idempotency_key=?", TRANSFER, user, r.idempotency_key()), r);
        }
        // FK inserts hold KEY SHARE locks. NO KEY UPDATE protects balances without
        // conflicting with those locks; full FOR UPDATE would create upgrade deadlocks.
        var locked = db.query("SELECT * FROM wallets WHERE id IN (?,?) ORDER BY id FOR NO KEY UPDATE", WALLET, r.from(), r.to());
        Wallet from = locked.stream().filter(w -> w.id().equals(r.from())).findFirst().orElseThrow();
        Wallet to = locked.stream().filter(w -> w.id().equals(r.to())).findFirst().orElseThrow();
        String reason = from.balance_paise() < r.amount_paise() ? "INSUFFICIENT_FUNDS"
                : to.balance_paise() > Long.MAX_VALUE - r.amount_paise() ? "RECIPIENT_BALANCE_LIMIT" : null;
        if (reason == null) {
            db.update("UPDATE wallets SET balance_paise=balance_paise-? WHERE id=?", r.amount_paise(), r.from());
            db.update("UPDATE wallets SET balance_paise=balance_paise+? WHERE id=?", r.amount_paise(), r.to());
        }
        db.update("UPDATE transfers SET status=?,reason=? WHERE id=?", reason == null ? "COMPLETED" : "DECLINED", reason, id);
        return new Outcome(db.queryForObject("SELECT * FROM transfers WHERE id=?", TRANSFER, id), false);
    }
    private Outcome replay(Transfer t, TransferRequest r) {
        if (!t.from().equals(r.from()) || !t.to().equals(r.to()) || t.amount_paise() != r.amount_paise()) throw new ApiError(409, "IDEMPOTENCY_KEY_CONFLICT");
        return new Outcome(t, true);
    }
    private void event(String name, Transfer t) {
        publicLogs.append(name, t);
        LoggerFactory.getLogger(WalletService.class).atInfo().addKeyValue("event", name)
                .addKeyValue("transfer_id", t.id()).addKeyValue("status", t.status()).addKeyValue("reason", t.reason()).log(name);
    }
}
