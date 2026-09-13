# Verified local evidence

Run date: 13 September 2026. Docker on macOS/Colima (ARM64). PostgreSQL 17.6. Two Java 17 API containers sharing one database; each app limited to 1 CPU and 512 MiB RAM with an eight-connection pool. The Colima VM has 6 CPUs and 5 GiB memory. Tests run from the host over localhost.

`two-instances.json`: all eight check groups passed; 667 HTTP requests; zero unexpected 5xx responses. The contention phase made 500 transfers at concurrency 30: 450 completed, 50 declined; total stayed at 4,000,000 paise and every wallet matched its expected closing balance. Observed contention throughput was 158.19 requests/second. Aggregate client p50/p99 were 153.38/1998.33 ms across the whole suite, including connection setup and validation scenarios. These are environment-specific observations, not a service-level guarantee.

`failures.json`: injected credit failure after debit rolls back both balances and the idempotency key; the same request then succeeds. Hard process restart preserves the committed result. Database outage rejects writes and recovery works. No pending transfer or negative balance remained.

The initial contention run revealed lock-upgrade deadlocks when transfer foreign keys took KEY SHARE locks and balance locking requested full FOR UPDATE. The verified version uses ordered FOR NO KEY UPDATE, which remains compatible with foreign-key locks. The benchmark does not hide errors with retries. A metrics-name check also caught Prometheus normalization of the reserved `created` suffix; the final counter is `wallet_transfers_recorded_total`.

The replay test retries an already committed result; it does not physically drop a network packet. The restart and credit-failure checks are separate, real process/transaction failure tests. Public deployment and CI are not demonstrated by these local files.

## Cloud verification

The deployed API uses Render Singapore: 0.1 CPU / 512 MB for the app; PostgreSQL 17.11 on 0.1 CPU / 256 MB, 1 GB storage; connection pool limited to four. Both plans showed $0/month. `remote-core.json` records the first complete passing cloud run: 666 checked requests, no server errors, 500 contention transfers at concurrency 30, conserved 4,000,000 paise, 14.36 requests/second during contention. This is not comparable to the higher-resource two-instance local run.

Earlier public attempts encountered (1) a cold-start timeout and (2) one Render HTML 502 during a decline replay storm. At inspection the process had stayed running and application metrics contained no 5xx responses. This points to the gateway/connection path, but the precise provider cause is unconfirmed. The harness was changed to allow a 180-second initial health check and reuse per-thread HTTP connections. **No automatic transfer retries were added.** The failure is not presented as a clean run.

The final revision adds `/logs`, a bounded buffer containing only event timestamp, correlation ID, event name, transfer ID, status and reason. `local-final.json` verifies all nine groups, including that endpoint, with 669 checked requests and no server errors. `remote.json` records the final cloud run after deploying the same revision. CI remains an inactive template because the connected GitHub login lacks workflow scope.

Final public run completed at 2026-09-13T18:43:37Z (14 September in India): **669 requests, all nine check groups passed, zero server errors**. Contention throughput was 11.89 requests/second, client p50/p99 2382.68/5397.10 ms, and total remained 4,000,000 paise. This includes public-log privacy/correlation checks. The first rollout of the final image stalled in provider health checks without an application error; it was canceled, and the exact same commit deployed successfully on a fresh instance. No code or paid-plan change was required.
