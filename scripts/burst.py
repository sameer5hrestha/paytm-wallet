#!/usr/bin/env python3
"""Black-box invariant benchmark. Standard library only; no tokens in output."""
import argparse
import concurrent.futures
import http.client
import json
import math
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8080")
parser.add_argument("--peer-url", help="Optional second instance sharing the same database")
parser.add_argument("--transfers", type=int, default=500)
parser.add_argument("--concurrency", type=int, default=30)
parser.add_argument("--output", default="evidence/benchmark.json")
parser.add_argument("--admin-key-file", help="Read the admin key from a private local file instead of the environment")
args = parser.parse_args()
if args.transfers < 1 or not 1 <= args.concurrency <= 100:
    parser.error("positive transfers and concurrency between 1 and 100 required")
admin = os.environ.get("ADMIN_KEY")
if args.admin_key_file:
    admin = Path(args.admin_key_file).read_text().strip()
if not admin and args.url in ("http://localhost:8080", "http://127.0.0.1:8080"):
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        admin = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line).get("ADMIN_KEY")
if not admin:
    parser.error("Set ADMIN_KEY (local default also reads .env)")

samples = []
samples_lock = threading.Lock()
checks = []
connections = threading.local()


def request(method, path, token=None, body=None, expected=200, base=None, timeout=40):
    headers = {"Content-Type": "application/json", "X-Correlation-ID": str(uuid.uuid4())}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    origin = urllib.parse.urlsplit(base or args.url)
    if origin.scheme not in ("http", "https"):
        raise ValueError("Only HTTP or HTTPS targets are supported")
    address = (origin.scheme, origin.hostname, origin.port)
    cache = getattr(connections, "cache", None)
    if cache is None:
        connections.cache = cache = {}
    connection = cache.get(address)
    if connection is None:
        connection_type = http.client.HTTPSConnection if origin.scheme == "https" else http.client.HTTPConnection
        connection = cache[address] = connection_type(origin.hostname, origin.port, timeout=timeout)
    connection.timeout = timeout
    if connection.sock:
        connection.sock.settimeout(timeout)
    start = time.perf_counter()
    try:
        connection.request(method, origin.path.rstrip("/") + path, body=data, headers=headers)
        response = connection.getresponse()
    except Exception:
        connection.close()
        cache.pop(address, None)
        raise
    with response:
        raw = response.read().decode()
        elapsed = (time.perf_counter() - start) * 1000
        with samples_lock:
            samples.append({"status": response.status, "latency_ms": elapsed})
        assert response.status == expected, f"{method} {path}: expected {expected}, got {response.status}: {raw[:300]}"
        assert response.headers.get("X-Correlation-ID") == headers["X-Correlation-ID"], "Missing correlation id"
        return json.loads(raw) if response.headers.get("Content-Type", "").startswith("application/json") else raw


def passed(name, **detail):
    checks.append({"name": name, "passed": True, **detail})
    print("PASS", name, json.dumps(detail), flush=True)


def user(balance=1000000, create=True):
    result = request("POST", "/admin/users", admin, {"opening_balance_paise": balance}, 201)
    if create:
        result["wallet"] = request("POST", "/wallets", result["token"])
    return result


def balance(account):
    return request("GET", "/wallets/" + account["wallet"]["id"], account["token"])["balance_paise"]


def transfer_body(a, b, amount, key=None):
    return {"from": a["wallet"]["id"], "to": b["wallet"]["id"], "amount_paise": amount, "idempotency_key": key or str(uuid.uuid4())}


def storm(count, operation):
    barrier = threading.Barrier(count)
    def run(i):
        barrier.wait(timeout=20)
        return operation(i)
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def base(i):
    return args.peer_url if args.peer_url and i % 2 else args.url


warmup_start = time.perf_counter()
request("GET", "/health", timeout=180)
warmup_seconds = time.perf_counter() - warmup_start
samples.clear()
started = time.perf_counter()
print("Health ready; starting invariant checks", flush=True)
# One new user, fifty callers, one initial endowment.
a = user(create=False)
created = storm(50, lambda i: request("POST", "/wallets", a["token"], base=base(i)))
assert len({w["id"] for w in created}) == 1
assert all(w["balance_paise"] == 1000000 for w in created)
a["wallet"] = created[0]
passed("race_free_get_or_create", requests=50, distinct_wallets=1)

b = user()
body = transfer_body(a, b, 2000)
results = storm(30, lambda i: request("POST", "/transfers", a["token"], body, base=base(i)))
assert all(r == results[0] for r in results)
assert results[0]["status"] == "COMPLETED"
assert balance(a) == 998000 and balance(b) == 1002000
assert request("GET", "/transfers/" + results[0]["id"], a["token"]) == results[0]
assert request("GET", "/transfers/" + results[0]["id"], b["token"]) == results[0]
passed("idempotent_retry_storm", requests=30, distinct_transfers=1, applied_debits=1)

conflict = dict(body, amount_paise=2001)
request("POST", "/transfers", a["token"], conflict, 409)
request("POST", "/transfers", a["token"], dict(body, to=str(uuid.uuid4())), 409)
assert request("POST", "/transfers", a["token"], body) == results[0]
assert balance(a) == 998000 and balance(b) == 1002000
passed("different_body_conflicts_and_lost_response_replay")

# Insufficient-funds result remains stable even after a later credit.
empty = user(0)
decline_body = transfer_body(empty, a, 100)
declines = storm(30, lambda i: request("POST", "/transfers", empty["token"], decline_body, base=base(i)))
assert all(d == declines[0] for d in declines)
assert declines[0]["status"] == "DECLINED" and declines[0]["reason"] == "INSUFFICIENT_FUNDS"
request("POST", "/transfers", a["token"], transfer_body(a, empty, 1000))
assert request("POST", "/transfers", empty["token"], decline_body) == declines[0]
assert balance(empty) == 1000
passed("declined_retry_storm_and_stable_decline_after_funding")

accounts = [a, b, empty, user(), user()]
before = {u["wallet"]["id"]: balance(u) for u in accounts}
expected_balances = dict(before)
rng = random.Random(42)
operations = []
for i in range(args.transfers):
    source, target = rng.sample(accounts, 2)
    amount = 100000000 if i % 11 == 0 else rng.randint(1, 2000)
    operations.append((source, transfer_body(source, target, amount)))

load_start = time.perf_counter()
def execute(item):
    i, (account, payload) = item
    return request("POST", "/transfers", account["token"], payload, base=base(i))
with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
    movements = list(pool.map(execute, enumerate(operations)))
load_seconds = time.perf_counter() - load_start
assert len({t["id"] for t in movements}) == args.transfers
for t in movements:
    assert t["status"] in ("COMPLETED", "DECLINED")
    if t["status"] == "COMPLETED":
        expected_balances[t["from"]] -= t["amount_paise"]
        expected_balances[t["to"]] += t["amount_paise"]
    else:
        assert t["reason"] == "INSUFFICIENT_FUNDS"
after = {u["wallet"]["id"]: balance(u) for u in accounts}
assert after == expected_balances, "Committed responses disagree with actual wallet balances"
assert sum(before.values()) == sum(after.values()) and min(after.values()) >= 0
passed("conservation_under_contention", transfers=args.transfers, concurrency=args.concurrency,
       total_before_paise=sum(before.values()), total_after_paise=sum(after.values()),
       minimum_balance_paise=min(after.values()), completed=sum(t["status"] == "COMPLETED" for t in movements),
       declined=sum(t["status"] == "DECLINED" for t in movements),
       requests_per_second=round(args.transfers / load_seconds, 2))

# Only one of two competing overdrawing requests can succeed.
c, d = user(100), user(0)
race = storm(2, lambda i: request("POST", "/transfers", c["token"], transfer_body(c, d, 80)))
assert sorted(r["status"] for r in race) == ["COMPLETED", "DECLINED"]
assert balance(c) == 20 and balance(d) == 80
passed("competing_overdraft")

request("GET", "/wallets/" + a["wallet"]["id"], expected=401)
request("GET", "/wallets/" + a["wallet"]["id"], b["token"], expected=403)
request("GET", "/transfers/" + results[0]["id"], c["token"], expected=404)
request("POST", "/transfers", b["token"], transfer_body(a, b, 1), 403)
request("POST", "/admin/users", b["token"], {"opening_balance_paise": 100}, 403)
for amount in (0, -1, 1.5, "100", True, 9223372036854775808, None):
    request("POST", "/transfers", a["token"], transfer_body(a, b, amount), 400)
request("POST", "/transfers", a["token"], transfer_body(a, a, 1), 400)
request("POST", "/transfers", a["token"], dict(transfer_body(a, b, 1), extra="invalid"), 400)
request("POST", "/transfers", a["token"], dict(transfer_body(a, b, 1), to=str(uuid.uuid4())), 404)
request("GET", "/wallets/not-a-uuid", a["token"], expected=400)
passed("authorization_and_strict_input_validation")

metrics = request("GET", "/metrics")
for name in ("wallet_transfers_recorded_total", "wallet_transfers_declined_insufficient_funds_total", "wallet_idempotent_replays_total", "http_server_requests_seconds_bucket"):
    assert name in metrics, "Missing metric: " + name
passed("observability_metrics")

# Produce a correlated transfer and replay so public logs can be checked directly.
logged_body = transfer_body(a, b, 1)
logged = request("POST", "/transfers", a["token"], logged_body)
request("POST", "/transfers", a["token"], logged_body)
public_logs = request("GET", "/logs")
assert len(public_logs) <= 200
matching = [e for e in public_logs if e["transfer_id"] == logged["id"]]
assert {e["event"] for e in matching} == {"transfer_created", "debited", "credited", "idempotent_replay_hit"}
assert all(e["correlation_id"] for e in matching)
assert all(set(e) == {"timestamp", "correlation_id", "event", "transfer_id", "status", "reason"} for e in public_logs)
passed("public_sanitized_domain_logs")

latencies = sorted(x["latency_ms"] for x in samples)
report = {"passed": True, "target": args.url, "peer_target": args.peer_url,
          "warmup_seconds": round(warmup_seconds, 2),
          "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks": checks,
          "requests": len(samples), "elapsed_seconds": round(time.perf_counter() - started, 2),
          "latency_p50_ms": round(statistics.median(latencies), 2),
          "latency_p99_ms": round(latencies[math.ceil(len(latencies) * .99) - 1], 2),
          "server_errors": sum(x["status"] >= 500 for x in samples),
          "notes": "Per-thread HTTP connection reuse; initial health/cold-start excluded. Aggregate includes expected validation errors. No automatic retries mask failures. Independent run uses fresh users."}
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
