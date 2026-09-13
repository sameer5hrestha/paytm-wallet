# Verified local evidence

Run date: 13 September 2026. Docker on macOS/Colima (ARM64). PostgreSQL 17.6. Two Java 17 API containers sharing one database; each app limited to 1 CPU and 512 MiB RAM with an eight-connection pool. The Colima VM has 6 CPUs and 5 GiB memory. Tests run from the host over localhost.

`two-instances.json`: all eight check groups passed; 667 HTTP requests; zero unexpected 5xx responses. The contention phase made 500 transfers at concurrency 30: 450 completed, 50 declined; total stayed at 4,000,000 paise and every wallet matched its expected closing balance. Observed contention throughput was 158.19 requests/second. Aggregate client p50/p99 were 153.38/1998.33 ms across the whole suite, including connection setup and validation scenarios. These are environment-specific observations, not a service-level guarantee.

`failures.json`: injected credit failure after debit rolls back both balances and the idempotency key; the same request then succeeds. Hard process restart preserves the committed result. Database outage rejects writes and recovery works. No pending transfer or negative balance remained.

The initial contention run revealed lock-upgrade deadlocks when transfer foreign keys took KEY SHARE locks and balance locking requested full FOR UPDATE. The verified version uses ordered FOR NO KEY UPDATE, which remains compatible with foreign-key locks. The benchmark does not hide errors with retries. A metrics-name check also caught Prometheus normalization of the reserved `created` suffix; the final counter is `wallet_transfers_recorded_total`.

The replay test retries an already committed result; it does not physically drop a network packet. The restart and credit-failure checks are separate, real process/transaction failure tests. Public deployment and CI are not demonstrated by these local files.
