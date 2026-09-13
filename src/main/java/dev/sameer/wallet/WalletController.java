package dev.sameer.wallet;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.security.SecureRandom;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
class WalletController {
    private final WalletService service;
    private final JdbcTemplate db;
    WalletController(WalletService service, JdbcTemplate db) { this.service = service; this.db = db; }
    @PostMapping("/wallets")
    WalletService.Wallet create(@RequestAttribute("userId") UUID user) { return service.getOrCreate(user); }
    @GetMapping("/wallets/{id}")
    WalletService.Wallet wallet(@PathVariable UUID id, @RequestAttribute("userId") UUID user) { return service.wallet(id, user); }
    @PostMapping("/transfers")
    WalletService.Transfer send(@RequestAttribute("userId") UUID user, @Valid @RequestBody WalletService.TransferRequest request) { return service.send(user, request); }
    @GetMapping("/transfers/{id}")
    WalletService.Transfer transfer(@PathVariable UUID id, @RequestAttribute("userId") UUID user) { return service.transfer(id, user); }
    record UserRequest(@NotNull @Min(0) @Max(1000000000) Long opening_balance_paise) {}
    @PostMapping("/admin/users")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    Map<String, Object> user(@Valid @RequestBody UserRequest request) {
        byte[] secret = new byte[32]; new SecureRandom().nextBytes(secret);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(secret);
        UUID id = UUID.randomUUID();
        db.update("INSERT INTO app_users(id,token_hash,opening_balance_paise) VALUES(?,?,?)", id, AuthFilter.hash(token), request.opening_balance_paise());
        return Map.of("user_id", id, "token", token, "opening_balance_paise", request.opening_balance_paise());
    }
}
