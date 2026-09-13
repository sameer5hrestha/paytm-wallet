package dev.sameer.wallet;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
class AuthFilter extends OncePerRequestFilter {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final String adminHash;
    AuthFilter(JdbcTemplate db, ObjectMapper json, @Value("${wallet.admin-key}") String key) {
        if (key.length() < 32) throw new IllegalArgumentException("ADMIN_KEY must contain at least 32 characters");
        this.db = db; this.json = json; this.adminHash = hash(key);
    }
    static String hash(String token) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    @Override protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain) throws ServletException, IOException {
        String supplied = req.getHeader("X-Correlation-ID");
        String correlation = supplied != null && supplied.matches("[A-Za-z0-9_-]{1,64}") ? supplied : UUID.randomUUID().toString();
        MDC.put("correlation_id", correlation);
        res.setHeader("X-Correlation-ID", correlation);
        try {
            String path = req.getRequestURI();
            if (path.equals("/health") || path.startsWith("/health/") || path.equals("/metrics") || path.equals("/logs")) {
                chain.doFilter(req, res); return;
            }
            String auth = req.getHeader("Authorization");
            if (auth == null || !auth.startsWith("Bearer ") || auth.length() > 512) { reject(res, 401, "UNAUTHORIZED"); return; }
            String tokenHash = hash(auth.substring(7));
            if (path.startsWith("/admin/")) {
                if (!MessageDigest.isEqual(tokenHash.getBytes(StandardCharsets.UTF_8), adminHash.getBytes(StandardCharsets.UTF_8))) {
                    reject(res, 403, "FORBIDDEN"); return;
                }
            } else {
                var users = db.query("SELECT id FROM app_users WHERE token_hash = ?", (rs, i) -> rs.getObject(1, UUID.class), tokenHash);
                if (users.isEmpty()) { reject(res, 401, "UNAUTHORIZED"); return; }
                req.setAttribute("userId", users.get(0));
            }
            chain.doFilter(req, res);
        } catch (org.springframework.dao.DataAccessException e) {
            res.setHeader("Retry-After", "1");
            reject(res, 503, "TEMPORARILY_UNAVAILABLE_RETRY_SAME_KEY");
        } finally { MDC.remove("correlation_id"); }
    }
    private void reject(HttpServletResponse res, int status, String code) throws IOException {
        res.setStatus(status); res.setContentType("application/json"); json.writeValue(res.getOutputStream(), ApiError.body(code));
    }
}
