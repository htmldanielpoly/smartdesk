"""Load demo for the AI engine: many clients at once, priorities respected.

Fires a burst of ticket creations with mixed priorities and a handful of
agent copilot drafts through the public gateway, then prints the AI
scheduler's counters as the queue drains. Everything the engine does is
observable on GET /api/ai/status (staff) — the same numbers the Queue page
shows live.

Usage:
    python scripts/ai_load_demo.py [base_url] [--tickets 40] [--drafts 6]

Requires a running stack and the bootstrap admin (ADMIN_EMAIL/ADMIN_PASSWORD
from .env). Registration is metered per address, so raise
RATE_LIMIT_REQUESTS before a big burst; authenticated traffic is metered per
user. Only uses the Python standard library.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-please-1")
RUN_ID = str(int(time.time()))

TEMPLATES = [
    ("URGENT", "Whole office is down", "Nobody can reach the internet since 9am, outage, ASAP"),
    ("HIGH", "Cannot log in", "Password reset link says invalid token, blocked from work"),
    ("MEDIUM", "Invoice question", "The March invoice shows a charge I do not recognise"),
    ("LOW", "Feature request", "It would be nice to export tickets as CSV some day"),
]


def call(base, method, path, token=None, body=None):
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://localhost:8080")
    ap.add_argument("--tickets", type=int, default=40)
    ap.add_argument("--drafts", type=int, default=6)
    args = ap.parse_args()
    base = args.base

    code, admin = call(base, "POST", "/api/auth/login",
                       body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if code != 200:
        print("admin login failed:", admin)
        sys.exit(1)
    staff = admin["access_token"]

    # One customer per ticket, so budgets are per user and the burst is real.
    def customer(i):
        code, u = call(base, "POST", "/api/auth/register", body={
            "email": f"burst{RUN_ID}-{i}@example.com", "password": "password123",
            "display_name": f"Burst {i}",
        })
        return u["access_token"] if code == 201 else None

    print(f"registering {args.tickets} customers…")
    tokens = [t for t in (customer(i) for i in range(args.tickets)) if t]

    created: list[str] = []
    lock = threading.Lock()

    def fire(token):
        prio, title, desc = random.choice(TEMPLATES)
        code, t = call(base, "POST", "/api/tickets", token=token,
                       body={"title": f"{title} ({prio})", "description": desc})
        if code == 201:
            with lock:
                created.append(t["id"])

    print(f"firing {len(tokens)} tickets at once (mixed URGENT/HIGH/MEDIUM/LOW)…")
    t0 = time.time()
    threads = [threading.Thread(target=fire, args=(tok,)) for tok in tokens]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    print(f"  {len(created)} tickets accepted in {time.time() - t0:.2f}s "
          "(creation never waits for the AI)")

    # A few agent drafts on top: interactive work that should jump the queue.
    def draft(ticket_id):
        code, r = call(base, "POST", f"/api/tickets/{ticket_id}/ai/copilot", token=staff)
        source = r.get("source") if isinstance(r, dict) else "-"
        print(f"  copilot draft for {ticket_id[-6:]}: HTTP {code} source={source}")

    for tid in created[: args.drafts]:
        threading.Thread(target=draft, args=(tid,)).start()

    print("\nAI engine while the burst drains (GET /api/ai/status):")
    deadline = time.time() + 300
    while time.time() < deadline:
        code, h = call(base, "GET", "/api/ai/status", token=staff)
        if code != 200:
            print("  status unavailable:", h)
            break
        s, m = h.get("scheduler", {}), h.get("local_ai", {})
        print(f"  models={m.get('status'):<11} workers={s.get('workers')} "
              f"queued={s.get('queued'):>3} running={s.get('running')} "
              f"completed={s.get('completed'):>4} rejected={s.get('rejected')} "
              f"avg_wait={s.get('avg_wait_ms')}ms by_kind={s.get('by_kind')}")
        idle = s.get("queued", 0) == 0 and s.get("running", 0) == 0
        if idle and s.get("completed", 0) >= len(created):
            break
        time.sleep(2)

    pending = 0
    for tid in created:
        _, t = call(base, "GET", f"/api/tickets/{tid}", token=staff)
        if (t.get("ai_suggested") or {}).get("status") == "pending":
            pending += 1
    print(f"\ndone: {len(created) - pending}/{len(created)} tickets classified")


if __name__ == "__main__":
    main()
