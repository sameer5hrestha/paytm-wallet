#!/usr/bin/env python3
"""Local-only failure injection against this Compose project's demo database."""
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if "=" in line)
COMPOSE = ["docker", "compose"] if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0 else ["docker-compose"]
checks = []


def compose(*args, input=None):
    result = subprocess.run(COMPOSE + list(args), cwd=ROOT, input=input, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def sql(statement):
    return compose("exec", "-T", "db", "psql", "-U", "wallet", "-d", "wallet", "-v", "ON_ERROR_STOP=1", "-At", input=statement)


def call(method, path, token=None, body=None, expected=200):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("http://localhost:8080" + path, json.dumps(body).encode() if body is not None else None, headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = json.load(response)
        assert response.status == expected, (response.status, data)
        return data


def account():
    u = call("POST", "/admin/users", env["ADMIN_KEY"], {"opening_balance_paise": 1000}, 201)
    u["wallet"] = call("POST", "/wallets", u["token"])
    return u


def balances(a, b):
    return [call("GET", "/wallets/" + u["wallet"]["id"], u["token"])["balance_paise"] for u in (a, b)]


def passed(name):
    checks.append({"name": name, "passed": True})
    print("PASS", name, flush=True)


a, b = account(), account()
body = {"from": a["wallet"]["id"], "to": b["wallet"]["id"], "amount_paise": 200, "idempotency_key": str(uuid.uuid4())}
# Deliberately fail the credit statement, after the debit has already executed.
# Interpolated IDs come from the UUID API; no arbitrary/user-provided SQL is used.
recipient = str(uuid.UUID(body["to"]))
key = str(uuid.UUID(body["idempotency_key"]))
sql(f"""
CREATE FUNCTION test_reject_credit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id = '{recipient}'::uuid AND NEW.balance_paise > OLD.balance_paise THEN
  RAISE EXCEPTION 'test injected credit failure';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER test_reject_credit BEFORE UPDATE ON wallets FOR EACH ROW EXECUTE FUNCTION test_reject_credit();
""")
try:
    call("POST", "/transfers", a["token"], body, 503)
    assert balances(a, b) == [1000, 1000], "A partial debit survived rollback"
    assert sql(f"SELECT count(*) FROM transfers WHERE idempotency_key='{key}';") == "0"
finally:
    sql("DROP TRIGGER IF EXISTS test_reject_credit ON wallets; DROP FUNCTION IF EXISTS test_reject_credit();")
result = call("POST", "/transfers", a["token"], body)
assert result["status"] == "COMPLETED" and balances(a, b) == [800, 1200]
passed("credit_failure_rolls_back_debit_and_key_then_retry_succeeds")

# Hard process termination: durable committed result must survive.
compose("kill", "-s", "SIGKILL", "app")
compose("up", "-d", "--wait", "app")
assert call("POST", "/transfers", a["token"], body) == result
assert balances(a, b) == [800, 1200]
passed("hard_app_restart_preserves_balances_and_idempotency")

# Do not accept a transfer while the authoritative database is unavailable.
outage_body = dict(body, idempotency_key=str(uuid.uuid4()))
compose("stop", "db")
try:
    call("POST", "/transfers", a["token"], outage_body, 503)
finally:
    compose("up", "-d", "--wait", "db")
for attempt in range(30):
    try:
        call("GET", "/health")
        break
    except Exception:
        if attempt == 29:
            raise
        time.sleep(1)
assert balances(a, b) == [800, 1200]
assert call("POST", "/transfers", a["token"], outage_body)["status"] == "COMPLETED"
assert balances(a, b) == [600, 1400]
passed("database_outage_rejects_writes_then_recovers")
assert sql("SELECT count(*) FROM transfers WHERE status='PENDING';") == "0"
assert sql("SELECT count(*) FROM wallets WHERE balance_paise<0;") == "0"
passed("no_committed_pending_transfers_or_negative_balances")
report = {"passed": True, "scope": "local Docker Compose only", "checks": checks}
(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence" / "failures.json").write_text(json.dumps(report, indent=2) + "\n")
