"""Stress / load test — "swarming" the gateway with Locust.

Locust (https://locust.io) simulates a *swarm* of concurrent users hammering
the API, and reports throughput (requests/s), latency percentiles and error
rate — the metrics the testing lecture lists for stress testing. This is the
tool of choice from that lecture (alongside Apache Bench / LoadRunner).

Each simulated user registers once, logs in, then loops over realistic
actions: creating tickets, listing their tickets, and browsing forums. A
smaller weighted set of "agent" users works the queue.

--- Run it -----------------------------------------------------------------
1. Boot the stack (and lift the rate limit so it doesn't cap throughput):

     RATE_LIMIT_REQUESTS=1000000 docker compose up --build -d
   (or set RATE_LIMIT_REQUESTS in .env before `docker compose up`)

2. Install + launch Locust, then open the web UI at http://localhost:8089:

     pip install -r tests/Stress_Tests/requirements.txt
     locust -f tests/Stress_Tests/locustfile.py --host http://localhost:8080

3. Or run headless — e.g. swarm to 200 users, spawning 20/s, for 1 minute:

     locust -f tests/Stress_Tests/locustfile.py --host http://localhost:8080 \
            --headless -u 200 -r 20 -t 1m --csv results

Note: the api-service has a per-IP rate limiter (default 30 req/60s). From a
single load-generator host every virtual user shares one IP, so leave it
lifted (step 1) for a meaningful load test — otherwise you are measuring the
limiter, not the server.
"""
import itertools
import random

from locust import HttpUser, between, task

_counter = itertools.count()

TICKET_TEMPLATES = [
    ("VPN keeps dropping", "The corporate VPN disconnects every few minutes since this morning."),
    ("Cannot reset password", "The password reset email never arrives, I am locked out."),
    ("Invoice looks wrong", "This month's invoice charged me twice for the same subscription."),
    ("Printer offline", "The 3rd-floor printer shows offline for the whole team."),
    ("App crashes on export", "Exporting a report throws a 500 error every time."),
]


class SupportUser(HttpUser):
    """A regular customer: opens tickets and browses the forums."""

    weight = 4
    wait_time = between(1, 3)

    def on_start(self):
        n = next(_counter)
        email = f"load_user_{n}_{random.randint(0, 1_000_000)}@example.com"
        self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "display_name": f"Load {n}"},
            name="POST /auth/register",
        )
        r = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": "password123"},
            name="POST /auth/login",
        )
        self.token = r.json().get("access_token") if r.status_code == 200 else None

    @property
    def auth(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(5)
    def create_ticket(self):
        if not self.token:
            return
        title, desc = random.choice(TICKET_TEMPLATES)
        self.client.post(
            "/api/tickets",
            json={"title": title, "description": desc},
            headers=self.auth,
            name="POST /tickets",
        )

    @task(3)
    def list_my_tickets(self):
        if not self.token:
            return
        self.client.get("/api/tickets", headers=self.auth, name="GET /tickets")

    @task(2)
    def browse_forums(self):
        if not self.token:
            return
        self.client.get("/api/forums/boards", headers=self.auth, name="GET /forums/boards")

    @task(1)
    def health(self):
        self.client.get("/health", name="GET /health")


class AgentUser(HttpUser):
    """An agent working the queue — heavier read/claim traffic."""

    weight = 1
    wait_time = between(1, 2)

    def on_start(self):
        # Agents can't self-promote, so in a load test they read the queue as
        # authenticated users; without staff role these 403 — which is itself a
        # useful signal. For a full agent load test, seed AGENT accounts first.
        n = next(_counter)
        email = f"load_agent_{n}_{random.randint(0, 1_000_000)}@example.com"
        self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "display_name": f"Agent {n}"},
            name="POST /auth/register",
        )
        r = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": "password123"},
            name="POST /auth/login",
        )
        self.token = r.json().get("access_token") if r.status_code == 200 else None

    @task
    def view_queue(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        # 403 for non-staff is expected; we still measure the endpoint's latency.
        with self.client.get(
            "/api/queue", headers=headers, name="GET /queue", catch_response=True
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
