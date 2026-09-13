# Deployment runbook

## Required configuration

Deploy the included Dockerfile as a web service. Set:

| Variable | Value |
|---|---|
| `JDBC_DATABASE_URL` | `jdbc:postgresql://HOST:5432/DATABASE?sslmode=require` for managed Postgres |
| `DB_USER` | Managed database username |
| `DB_PASSWORD` | Managed database password, as a secret |
| `ADMIN_KEY` | Random secret at least 32 characters; never put it in source |
| `PORT` | Provided by host; defaults to 8080 |
| `DB_POOL_SIZE` | Default 8; reduce if provider connection limit requires it |

Configure health path `/health`, at least 512 MiB memory as an initial budget, and a region near the database. The app binds all container interfaces. The Dockerfile uses Java 17. Local Compose limits the app to 1 CPU and 512 MiB to make test conditions explicit. These are chosen starting settings, not requirements from Paytm or measured production sizing.

## Publish procedure

1. Review the implementation and AI disclosure. Create a public repository containing source, scripts, docs, and sanitized evidence. Exclude `.env` and recruiter attachments. Keep honest commit authorship.
2. Create a free managed PostgreSQL database and a Docker-based web service using the repository. Verify the selected plans remain ₹0, whether a card is required, cold-start behaviour, expiration, and any sleep timeouts. Do not select a paid plan automatically.
3. Configure the secrets above and deploy. Flyway runs versioned schema migration at application startup. Use a provider-supported secure PostgreSQL connection; use `verify-full` and the appropriate CA where supported.
4. Confirm the public `/health` endpoint returns UP, then run `ADMIN_KEY`-authorized `scripts/burst.py --url https://YOUR-HOST --output evidence/remote.json`.
5. Capture log streaming during the public burst. Inspect `/metrics` for p99, HTTP counters, and domain counters. Stop/restart the application and confirm database balances persist and replay is stable.
6. Add the verified API URL, repository URL, logs link/recording, cost note, and run evidence to SUBMISSION.md. A local benchmark is not proof of public deployment.

## Secret handling

Provision user tokens through the admin endpoint and supply evaluator credentials privately. The public repo contains no credentials. Public metrics have no token, user, or wallet labels. Administrative provisioning changes total demo funding; benchmark comparisons use only their own wallets after provisioning is finished. Do not allow other scripts to modify those wallets during a benchmark.

## Operational limitations

No HA or disaster recovery is configured by this repository. Free-tier availability and quotas belong to the chosen provider. Auth has no token rotation/revocation UI. No rate limiter is provided; internet exposure should use provider request limits. Database errors return a generic retryable response, while application logs retain diagnostic details. Domain counters reset when an instance restarts.
