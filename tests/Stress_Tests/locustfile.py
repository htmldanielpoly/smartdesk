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
"""
Enhanced Stress / Load test — Behavioral UX user flows.
Simulates realistic customer journeys and authenticated staff workflows.
"""
import itertools
import random
from locust import HttpUser, SequentialTaskSet, between, task

_counter = itertools.count()

TICKET_TEMPLATES = [
    ("VPN keeps dropping", "The corporate VPN disconnects every few minutes since this morning."),
    ("Cannot reset password", "The password reset email never arrives, I am locked out."),
    ("Invoice looks wrong", "This month's invoice charged me twice for the same subscription."),
    ("Printer offline", "The 3rd-floor printer shows offline for the whole team."),
    ("App crashes on export", "Exporting a report throws a 500 error every time."),
]

FORUM_POSTS = [
    "Has anyone else experienced this issue today?",
    "Thanks for the update, this helped solve my problem.",
    "Still waiting on a response regarding this.",
]


class CustomerBehavior(SequentialTaskSet):
    """Simulates a complete step-by-step customer journey."""

    def on_start(self):
        n = next(_counter)
        self.email = f"customer_{n}_{random.randint(0, 1_000_000)}@example.com"
        self.password = "password123"
        self.token = None
        self.created_ticket_id = None

        # 1. Register
        self.client.post(
            "/api/auth/register",
            json={"email": self.email, "password": self.password, "display_name": f"Customer {n}"},
            name="Customer: Register",
        )
        # 2. Login
        res = self.client.post(
            "/api/auth/login",
            json={"email": self.email, "password": self.password},
            name="Customer: Login",
        )
        if res.status_code == 200:
            self.token = res.json().get("access_token")

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task
    def create_support_ticket(self):
        if not self.token:
            return
        title, desc = random.choice(TICKET_TEMPLATES)
        res = self.client.post(
            "/api/tickets",
            json={"title": title, "description": desc},
            headers=self.headers,
            name="Customer: Create Ticket",
        )
        if res.status_code == 201:
            self.created_ticket_id = res.json().get("id")

    @task
    def update_ticket_description(self):
        if not self.token or not self.created_ticket_id:
            return
        self.client.patch(
            f"/api/tickets/{self.created_ticket_id}",
            json={"description": "Updating ticket description with additional diagnostic information."},
            headers=self.headers,
            name="Customer: Update Ticket",
        )

    @task
    def browse_and_interact_on_forums(self):
        if not self.token:
            return

        # 1. Get boards
        res = self.client.get("/api/forums/boards", headers=self.headers, name="Customer: View Boards")
        if res.status_code == 200 and res.json():
            board_list = res.json()
            board_slug = board_list[0].get("slug") if isinstance(board_list, list) else None

            if not board_slug:
                return

            # 2. Get threads in board
            threads_res = self.client.get(
                f"/api/forums/boards/{board_slug}/threads",
                headers=self.headers,
                name="Customer: View Threads",
            )

            if threads_res.status_code == 200:
                data = threads_res.json()
                # Bulletproof check: Extracts the array whether it is a raw list or wrapped in a dict
                thread_list = data if isinstance(data, list) else data.get("items", data.get("threads", []))

                if thread_list and len(thread_list) > 0:
                    thread_id = thread_list[0].get("id")

                    # 3. Post reply
                    self.client.post(
                        f"/api/forums/threads/{thread_id}/posts",
                        json={"content": random.choice(FORUM_POSTS)},
                        headers=self.headers,
                        name="Customer: Post Forum Reply",
                    )


class StaffBehavior(SequentialTaskSet):
    """Simulates an active support agent handling incoming work."""

    def on_start(self):
        # Authenticate as bootstrap Admin/Agent
        self.token = None
        res = self.client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "change-me-please-1"},
            name="Staff: Login",
        )
        if res.status_code == 200:
            self.token = res.json().get("access_token")

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task
    def process_queue_and_copilot(self):
        if not self.token:
            return
        # 1. View queue stats
        self.client.get("/api/queue/stats", headers=self.headers, name="Staff: Queue Stats")

        # 2. Claim top ticket
        claim_res = self.client.post("/api/queue/claim", headers=self.headers, name="Staff: Claim Ticket")
        if claim_res.status_code == 200:
            ticket = claim_res.json()
            ticket_id = ticket.get("id")

            # 3. Request AI Copilot response draft
            self.client.post(
                f"/api/tickets/{ticket_id}/ai/copilot",
                headers=self.headers,
                name="Staff: AI Copilot Draft",
            )


class CustomerUser(HttpUser):
    weight = 4
    wait_time = between(1, 3)
    tasks = [CustomerBehavior]


class StaffUser(HttpUser):
    weight = 1
    wait_time = between(2, 4)
    tasks = [StaffBehavior]