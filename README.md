# Wallet & P2P Transfer

Java 17 / Spring Boot 3.5 / PostgreSQL. A runnable demonstration of atomic wallet transfers, durable idempotency, and concurrency verification. This moves **demo balances**, not real money.

## Start locally

Requires Docker with Compose, OpenSSL, and Python 3 for the benchmark. Maven and Java are provided by the build container.

```sh
sh scripts/setup.sh
python3 scripts/burst.py
```

The setup creates random secrets in the ignored `.env` file only if it does not exist, builds the image, and waits for app + database health. The app listens on http://localhost:8080. Data persists in a named Docker volume. `docker compose down` stops services without deleting balances. Systems with standalone Compose can use `docker-compose` instead.

## API contract

All four business endpoints require `Authorization: Bearer <user-token>`. Responses carry `X-Correlation-ID`; a safe supplied ID is preserved. JSON error responses contain `error` and `correlation_id`.

| Endpoint | Contract |
|---|---|
| `POST /wallets` | 200: get-or-create the authenticated user's only wallet; no body required |
| `GET /wallets/{id}` | 200: owned wallet with integer `balance_paise`; another user's wallet is 403 |
| `POST /transfers` | 200: immutable COMPLETED or DECLINED result, including on replay |
| `GET /transfers/{id}` | 200: transfer visible to sender or recipient; others receive 404 |
| `POST /admin/users` | 201: create a demo identity; requires the separate ADMIN_KEY bearer token |
| `GET /health` | Public health, including database connectivity |
| `GET /metrics` | Public Prometheus metrics; no token or user ID labels |
| `GET /logs` | Public last 200 committed domain events from this instance; no bearer tokens, wallet IDs, amounts, or user IDs |

Provision a demo user with `{"opening_balance_paise":1000000}`. The response provides `user_id` and a randomly generated bearer `token` once. Only its SHA-256 hash is stored. The opening balance is assigned once when that user creates their wallet; repeated wallet requests cannot mint money. The admin endpoint is a demo funding mechanism outside the transfer invariant, and must never be exposed with a weak/shared public admin secret. Maximum initial funding is 1,000,000,000 paise per user.

Example transfer body:

```json
{
  "from": "<sender-wallet-uuid>",
  "to": "<recipient-wallet-uuid>",
  "amount_paise": 2000,
  "idempotency_key": "order-2026-001"
}
```

Example response shape:

```json
{
  "id": "<transfer-uuid>",
  "from": "<sender-wallet-uuid>",
  "to": "<recipient-wallet-uuid>",
  "amount_paise": 2000,
  "idempotency_key": "order-2026-001",
  "status": "COMPLETED",
  "reason": null,
  "created_at": "<timestamp>"
}
```

Idempotency keys are scoped to the authenticated user, 1–128 characters using letters, digits, `.`, `_`, `:`, or `-`. Same key and body return the same transfer result; changed sender, recipient, or amount returns 409. Declines are persistent: adding money later does not turn a replay into a new transfer. Use a new key for a new intent.

Errors: 400 invalid input/self-transfer; 401 missing or invalid token; 403 unauthorized wallet access/debit; 404 missing wallet or inaccessible transfer; 409 key conflict; 503 transient database/lock failure. Retry a 503 or lost response with the **same key and body**. There is no automatic client retry in the benchmark. Successful and declined transfer results both use HTTP 200, so inspect `status`. Amount must be a positive JSON integer within signed 64-bit range: decimal, string, boolean, null, unknown fields, and overflow inputs are rejected.

## Concurrency benchmark

```sh
python3 scripts/burst.py --transfers 500 --concurrency 30
# Remote: set ADMIN_KEY securely in your shell; it is not printed or stored in results.
python3 scripts/burst.py --url https://YOUR-HOST --output evidence/remote.json
# Alternative: read the admin secret from a private file instead of an environment variable.
python3 scripts/burst.py --url https://YOUR-HOST --admin-key-file /path/to/private-key.txt --output evidence/remote.json
```

Every run provisions fresh identities. It checks 50-way wallet creation, 30-way successful and declined replay storms, conflicting payloads, 500 mixed transfers including opposite directions, aggregate conservation, each wallet's exact expected closing balance, competing overdrafts, API access control, strict input parsing, correlation IDs, and useful metrics. Expected 4xx responses test validation. Any unexpected status, 5xx, balance mismatch, or failed assertion exits nonzero. The generated JSON contains pass/fail evidence and client p50/p99 timings, but no credentials.

No throughput threshold was specified in the exercise. Client throughput/latency are observations for this environment, not production capacity guarantees. Domain declines are business outcomes, not server errors. The API meters p99 separately using Micrometer.

Optional multi-instance verification:

```sh
docker compose -f compose.yaml -f compose.peer.yaml up -d --build --wait
python3 scripts/burst.py --peer-url http://localhost:8081 --output evidence/two-instances.json
```

Requests alternate between instances sharing PostgreSQL. Idempotency and locking do not depend on app memory.

## Transactions and failures

PostgreSQL READ COMMITTED; unique wallet/user constraint; unique `(user_id,idempotency_key)`; both wallet rows locked in database UUID order with `FOR NO KEY UPDATE`. This protects balance writes while remaining compatible with the KEY SHARE locks taken by transfer foreign-key checks. Using full FOR UPDATE here creates lock-upgrade deadlocks despite sorted ordering. Transfer insertion, balance changes, and terminal result commit together. A concurrent unique-key loser waits, then uses a new READ COMMITTED statement to see the winner's result. A transaction rollback removes the pending key and both balance updates. Pending states are never deliberately committed or returned.

Run `python3 scripts/failure_checks.py` locally after the burst. It injects a credit failure after debit, asserts rollback of money and key, retries, kills/restarts the app, and stops/restarts PostgreSQL. It is intentionally limited to this local Compose project and briefly interrupts it; never run this on a shared production database.

Insufficient funds and recipient integer overflow produce stable declines. Constraints provide a second line of defence. Lock wait is bounded to 5 seconds; statement execution to 10 seconds; transaction timeout is 15 seconds. An uncertain commit or lost response is resolved by retrying the original key. In-memory locks and distributed caches are not required.

Structured domain logs are emitted **after successful commit** and include event, transfer ID, status, and request correlation ID. There is a crash window after commit but before logging: logs/counters are operational telemetry, not a financial audit ledger. The durable transfer table remains the source of truth. A production financial system would need a transactional audit/outbox and reconciliation.

## Observe

```sh
curl -fsS http://localhost:8080/health
curl -fsS http://localhost:8080/metrics
curl -fsS http://localhost:8080/logs
docker compose logs -f --no-log-prefix app
```

Prometheus examples:

```promql
sum(rate(http_server_requests_seconds_count{uri="/transfers"}[5m]))
histogram_quantile(0.99, sum by (le) (rate(http_server_requests_seconds_bucket{uri="/transfers"}[5m])))
sum(rate(http_server_requests_seconds_count{status=~"5.."}[5m]))
wallet_transfers_recorded_total
wallet_transfers_declined_insufficient_funds_total
wallet_idempotent_replays_total
```

The public `/logs` endpoint provides the most recent 200 sanitized domain events, so an evaluator can inspect current activity without a Render account. It is an in-memory, per-instance buffer and resets on restart; it is not an audit ledger. The complete structured console output is retained according to host log retention. Never include `.env`, bearer tokens, database credentials, or the recruiter attachments in the public repository.

## Deployment and submission

See [DEPLOYMENT.md](DEPLOYMENT.md), [DESIGN.md](DESIGN.md), and [SUBMISSION.md](SUBMISSION.md). The inactive CI template at `ci/verify.yml.template` builds from checkout and runs the real HTTP benchmark with PostgreSQL. To enable it, copy it to `.github/workflows/verify.yml` using a GitHub login with workflow permission. The current login lacks that scope, so no Actions workflow was published or executed.
