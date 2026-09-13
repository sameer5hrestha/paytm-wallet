package dev.sameer.wallet;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.List;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Bounded, sanitized demo telemetry. Durable financial state lives in PostgreSQL. */
@RestController
class PublicEventLog {
    record Entry(Instant timestamp, String correlation_id, String event, UUID transfer_id, String status, String reason) {}
    private final ArrayDeque<Entry> entries = new ArrayDeque<>();
    synchronized void append(String event, WalletService.Transfer transfer) {
        if (entries.size() == 200) entries.removeFirst();
        entries.addLast(new Entry(Instant.now(), MDC.get("correlation_id"), event, transfer.id(), transfer.status(), transfer.reason()));
    }
    @GetMapping("/logs")
    synchronized List<Entry> recent() { return List.copyOf(entries); }
}
