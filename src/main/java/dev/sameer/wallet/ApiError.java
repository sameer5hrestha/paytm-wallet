package dev.sameer.wallet;

import java.util.Map;
import org.slf4j.MDC;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

public class ApiError extends RuntimeException {
    final int status;
    final String code;
    ApiError(int status, String code) { super(code); this.status = status; this.code = code; }
    static Map<String, String> body(String code) {
        return Map.of("error", code, "correlation_id", String.valueOf(MDC.get("correlation_id")));
    }
}

@RestControllerAdvice
class ErrorAdvice {
    @ExceptionHandler(ApiError.class)
    ResponseEntity<?> known(ApiError e) { return ResponseEntity.status(e.status).body(ApiError.body(e.code)); }
    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class})
    ResponseEntity<?> invalid(Exception e) { return ResponseEntity.badRequest().body(ApiError.body("INVALID_REQUEST")); }
    @ExceptionHandler(DataAccessException.class)
    ResponseEntity<?> database(DataAccessException e) {
        LoggerFactory.getLogger(ErrorAdvice.class).warn("database_operation_failed", e);
        return ResponseEntity.status(503).header("Retry-After", "1").body(ApiError.body("TEMPORARILY_UNAVAILABLE_RETRY_SAME_KEY"));
    }
}
