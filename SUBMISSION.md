# Submission checklist

- Live API URL: https://sameer-paytm-wallet.onrender.com
- Public repository: https://github.com/sameer5hrestha/paytm-wallet
- Public logs: https://sameer-paytm-wallet.onrender.com/logs (last 200 sanitized events, per instance)
- Metrics: https://sameer-paytm-wallet.onrender.com/metrics
- Burst command: `python3 scripts/burst.py --url https://sameer-paytm-wallet.onrender.com` with ADMIN_KEY supplied privately
- One-page design and AI disclosure: [DESIGN.md](DESIGN.md)
- Local verification: **passed** — [two-instance benchmark](evidence/two-instances.json), [failure recovery](evidence/failures.json), and [test conditions](evidence/README.md)
- Public verification: core invariant benchmark passed; final log-endpoint validation is recorded in `evidence/remote.json` after deployment
- Hosting cost: **$0/month plans selected**, no card or paid service used. Database expires **13 October 2026**; API sleeps after inactivity and can take over a minute to wake.

Send evaluator demo-user credentials privately. Do not publish administrator/database secrets. Review the AI disclosure and be prepared to explain every transaction and failure case. No recruiter reply or submission is sent by this repository.
