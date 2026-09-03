# SmartDesk

SmartDesk is a web-based, AI-powered support ticket management system. Users
submit support tickets, track their status, discuss issues on per-department
forums, and communicate with support agents. AI assists agents with ticket
classification, drafting grounded responses, and spotting duplicate incidents,
and it **remembers resolved tickets**: when a client submits the exact same
problem another client already had solved, the AI answers it itself with no
agent in the loop. It all runs **locally, on open-weights models, with no API
keys** and no data leaving the machine. AI never blocks the core workflow.

## Architecture

Microservices on a private Docker network; only the API service is exposed.

| Service | Stack | Port | Exposed? |
|---|---|---|---|
| `api-service` | Python · FastAPI | 8080 | yes (the only public entrypoint / gateway) |
| `ai-service` | Python · FastAPI · llama.cpp | 8000 | internal only |
| `forum-service` | Python · FastAPI | 8001 | internal only (proxied at `/api/forums`) |
| `mongo` | MongoDB 7 | 27017 | internal only |

```
client ──> api-service (auth, tickets, comments, queue, admin)
              ├──> ai-service     (classify / copilot / duplicates, local LLM)
              ├──> forum-service  (boards / threads / posts, stateless JWT)
              └──> mongo          (smartdesk + smartdesk_forum databases)
```

## Web UI

A lightweight, Freshdesk-style single-page app ships with the gateway and is
served from its root (`http://localhost:8080/`) — no separate frontend server,
no build step. It's plain HTML/CSS/JS (`api-service/app/static/`) that talks to
the same `/api/*` gateway, so the whole product runs on one exposed port.

- **Customers** register/sign in, open tickets (AI auto-classifies them),
  track status, chat with agents, and use the community forums.
- **Agents** work the SLA-scored queue, claim the next ticket, set
  classification and status, use the AI copilot (draft reply / find
  duplicates), and moderate forums.
- **Admins** additionally manage user roles.

The staff-only **Incidents** view groups active complaints into incidents using
the **local embedding model** (`ai-service` `POST /cluster`, cosine similarity
over MiniLM embeddings; lexical token-overlap fallback when the model is off)
and shows a manager overview — severity, affected-customer estimate and a
recommended action per incident, with the source (model vs. fallback) shown on
screen. Its **⚡ Load Grid Incidents Demo** button seeds 50 realistic complaints
spanning two simultaneous grid outages — a one-click, fully model-driven live
demo (raise `RATE_LIMIT_REQUESTS` first; see `demo/`).

The UI adapts to the signed-in role and keeps you logged in across refreshes
(JWT in `localStorage`).

## Local AI — no API keys

The AI service runs two small open-weights models in-process via
`llama-cpp-python` (CPU-only, no GPU needed):

- **Qwen2.5-0.5B-Instruct** (4-bit GGUF, ~400 MB) — classification and the
  agent copilot.
- **all-MiniLM-L6-v2** (8-bit GGUF, ~25 MB) — embeddings for duplicate
  detection and knowledge-base retrieval.

Model files are downloaded automatically on first start into a Docker volume
(`ai_models`) and reused forever after. Until they are ready — and whenever
anything fails — every feature transparently degrades to deterministic
rule-based fallbacks, so the system is always fully functional.
`GET /health` on the AI service reports the model state
(`unloaded → downloading → loading → ready`).

## Parallel AI engine: a priority queue of chats

Local inference is CPU-bound and a llama.cpp model is not thread-safe, so
the AI service schedules its work instead of letting requests race
(`ai-service/app/services/scheduler.py`):

- **Every request is a job on an `asyncio.PriorityQueue`.** The key is
  *(job kind + ticket priority, arrival order)*: an URGENT ticket's copilot
  draft is served before a LOW ticket's classification, and interactive work
  (an agent or a customer is waiting) beats batch work (incident clustering).
  The gateway sends each ticket's priority along with the request.
- **A pool of worker tasks** (`AI_WORKERS`, default 4) pulls jobs and runs
  each in a thread, so the event loop keeps accepting requests and answering
  `/health` while a model is busy.
- **Two models, two locks.** Embeddings and chat completions hold separate
  locks and run truly in parallel on different cores; embeddings take the
  lock per text so a 200-ticket clustering batch cannot starve a single
  lookup. Rule-based fallbacks need no lock at all.
- **Backpressure.** Beyond `AI_QUEUE_MAX` queued jobs the engine answers
  `503 Retry-After` immediately, and every job has a timeout (`504`). The
  gateway treats both as "AI unavailable" and uses its rule-based path, so a
  burst of clients can never pile up unbounded work or block ticketing.
- **Observable.** `GET /health` on the AI service (and `GET /api/ai/status`
  for staff, shown live on the **Queue** page) reports workers, queued,
  running, completed, rejected and timed-out jobs, average queue wait, and
  jobs per kind. `python scripts/ai_load_demo.py` fires a burst of mixed-
  priority tickets and copilot drafts through the gateway and prints the
  engine's counters as it drains.

## AI safety: no hallucinations, no jailbreaks

Defense in depth, tested by a dedicated guardrail test suite
(`ai-service/tests/test_guardrails.py`):

1. **Constrained decoding** — every LLM call is grammar-constrained to a JSON
   schema (llama.cpp compiles it into the sampler). Category/priority are
   *enums in the grammar*: an invalid label cannot even be generated.
2. **Prompt-injection and coercion detection** — tickets matching jailbreak
   patterns ("ignore previous instructions", "ignore all rules", DAN and
   other personas, "pretend to be", fake authority, prompt extraction) or
   "yes-man" pressure ("admit the problem is with the service", "otherwise a
   catastrophe will happen", "you must agree with me") never reach the
   model; they are classified by deterministic rules, never auto-answered
   from memory, and flagged `injection_suspected` / `coercion_suspected`.
   The flag is shown on the ticket (⚠ badge) so agents see the attempt.
3. **Input sanitization** — chat-template control tokens (`<|im_start|>` etc.)
   and control characters are stripped, lengths capped, and ticket text is
   fenced as untrusted data in the prompt.
4. **Grounded copilot (RAG or refuse)** — the copilot may only answer from the
   curated knowledge base (`ai-service/app/data/kb_articles.json`). If no
   article is similar enough to the ticket, it *refuses to generate* and
   returns a safe template. Citations are grammar-constrained to the retrieved
   article ids and validated after generation; a draft that cites nothing real,
   contains a URL not present in the KB, or **makes a commitment the KB does
   not back** (a refund, a credit, an admission of fault, "as you demanded")
   is discarded — the copilot cannot be talked into being a yes-man.
5. **The model never decides alone** — departments are derived server-side
   from the category; all labels are whitelist-validated again after decoding.

## Long-term memory — repeat tickets are answered by the AI itself

Once an agent has resolved a ticket, SmartDesk remembers the answer. When a
client later opens a ticket describing the **same problem**, the AI answers it
on its own, with no human in the loop, and the ticket never enters the agent
queue (`api-service/app/services/memory.py`, `ai-service/app/services/memory.py`):

1. **Memory** — every resolved ticket carries a `resolution`: snapshotted from
   the agent's last public reply when the ticket is resolved, from a public
   staff reply posted after resolving, or set explicitly (staff-only
   `PATCH /api/tickets/{id}` `resolution`; also editable in the UI).
2. **Match** — right after a ticket is created (in the background, before
   classification) the api-service offers the recently resolved tickets to
   `POST /auto-resolve` on the AI service, which embeds them with the local
   MiniLM model and takes the best cosine match. The bar is deliberately
   strict: **≥ 0.95** by default (`AUTO_RESOLVE_SIMILARITY_THRESHOLD`) versus
   0.55 for merely *flagging* duplicates to an agent, so paraphrases still go
   to a human. Without the model, the lexical fallback needs a near-verbatim
   repeat (Jaccard ≥ 0.90).
3. **Answer** — on a match the ticket is atomically taken out of the queue
   (only if no agent has claimed it meanwhile; a human always wins the race),
   an AI-authored reply containing the stored resolution is posted, the
   ticket is marked `RESOLVED` (`AUTO_RESOLVE_CLOSE_TICKET=true` closes it
   outright) with an audit trail (`auto_resolved`: source ticket, similarity,
   path) and an activity-log entry with no actor. The answered ticket becomes
   memory too.
4. **Human override** — the customer sees the reply and a *This solved it /
   Didn't help* choice; reopening sends the ticket to the agent queue and
   whatever the agent then resolves it with replaces the remembered answer.

Safety: the reply reuses the human-written resolution verbatim (nothing is
generated, so nothing can be hallucinated), tickets that trip the
prompt-injection detector are never auto-answered, and the whole path is
best-effort: if the AI service is down the ticket simply waits for an agent.
`AUTO_RESOLVE_ENABLED=false` turns the feature off.

## Smart ticket queueing

Agents work from a scored queue instead of cherry-picking
(`api-service/app/services/queueing.py`):

- **Score = priority weight + aging + SLA-breach bonus.** URGENT starts above
  HIGH, but waiting tickets gain points over time so LOW tickets can't starve,
  and tickets past their SLA deadline (URGENT 4h / HIGH 24h / MEDIUM 72h /
  LOW 168h) jump the queue.
- `GET /api/queue` — ranked queue with per-ticket score, SLA deadline and
  breach flag; `GET /api/queue/stats` — totals by priority.
- `POST /api/queue/claim` — claims the top ticket **race-safely**: an atomic
  `find_one_and_update` guarantees a ticket is never assigned to two agents,
  even under concurrent claims (proven by a concurrency stress test).

## Forums — one per support department

Every support area gets a discussion board (Account, Billing, Technical,
Network, Hardware, General), auto-seeded at startup. Threads and replies for
all authenticated users; agents/admins can lock and pin threads; posts are
soft-deleted. The forum-service is never exposed directly — the api-service
proxies it under `/api/forums/*` and it validates the same JWTs (shared
secret, no cross-service user lookup).

## Abuse protection — spam, floods and oversized uploads

The gateway is the only exposed service, so the defences live there
(`api-service/app/rate_limit.py`, `api-service/app/middleware.py`):

- **Per-user rate limits.** Every metered endpoint has a general budget
  (`RATE_LIMIT_REQUESTS` per minute); anything that *creates content* — ticket
  comments, forum threads, posts and messages — has a stricter one
  (`RATE_LIMIT_WRITES`). Budgets are keyed by the user id in the JWT, not the
  client address, so one flooding customer cannot lock out everyone behind
  the same NAT or reverse proxy (and a Locust swarm from one host is metered
  per virtual user). Unauthenticated calls (register/login) are metered per
  address. Rejections are `429` with a `Retry-After` header.
- **Body size cap.** Requests bigger than `MAX_REQUEST_BODY_BYTES` (1 MiB by
  default; every API body is a small JSON document) are refused with `413`
  before they are read — declared lengths are rejected outright, chunked
  streams are cut off the moment they cross the cap.
- **Secrets.** The api-service logs a loud warning when it runs with the
  public example `JWT_SECRET`, and refuses to start with it when
  `REQUIRE_STRONG_SECRET=true` (the production compose file sets this).

## Quick start (Docker)

```bash
cp .env.example .env        # sensible defaults: admin login, local AI on, rate limit raised
docker compose up --build -d
```

First start downloads ~450 MB of model files into a Docker volume — watch
`docker compose logs -f ai-service` until they're ready. Until then (and
whenever anything fails) AI features degrade to rule-based fallbacks, so the app
is usable immediately. Check the gateway is up with
`curl http://localhost:8080/health`.

Then open the app and the API docs:

- **Web app** — http://localhost:8080/
- **API / Swagger UI** — http://localhost:8080/docs

**Sign in as the admin.** On the app's *Sign in* form use `ADMIN_EMAIL` /
`ADMIN_PASSWORD` from `.env` (defaults `admin@example.com` /
`change-me-please-1`). A bootstrap admin is created on first start;
self-registration only ever creates regular users, and the admin promotes
agents. Only staff (agent/admin) see the **Queue** and **Incidents** tabs.

### Live demo: two simultaneous grid incidents

Signed in as staff, open **Incidents → ⚡ Load Grid Incidents Demo**. This seeds
50 realistic complaints spanning two outages; SmartDesk clusters them into two
incidents using the local embedding model (the on-screen badge says whether the
model or the lexical fallback did the clustering), prioritizes each and shows a
manager overview. Give the AI a minute to classify the tickets, then hit
**↻ Refresh** for the severities to fill in. Reset between runs with
`docker compose down -v`.

To skip local AI entirely and run on rule-based fallbacks only, set
`LOCAL_AI_ENABLED=false` in `.env` before starting.

### End-to-end smoke test

With the stack running:

```bash
python scripts/smoke_test.py
```

It exercises the full journey through the public gateway: register → ticket →
async AI classification → injection attempt → agent promotion → queue claim →
copilot → comments → status machine → long-term memory (a second user's
identical ticket is answered by the AI, bypasses the queue, can be reopened) →
forums. CI runs the same script.

## Quick start (local, per service)

Each service is independent. From its folder (`api-service`, `ai-service`,
`forum-service`):

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port <8080|8000|8001>
```

The api-service needs a local MongoDB on :27017. The ai-service runs with
rule-based fallbacks unless you also `pip install -r requirements-llm.txt`
(needs a C++ toolchain; inside Docker this is prebuilt).

## Running tests

```bash
cd api-service   && pip install -r requirements-dev.txt && pytest   # 74 tests
cd ai-service    && pip install -r requirements-dev.txt && pytest   # 95 tests
cd forum-service && pip install -r requirements-dev.txt && pytest   # 14 tests
```

Tests need **no Docker, no Mongo, no model files**: the api/forum tests run
against an in-memory MongoDB (`mongomock-motor`) and the AI tests mock the
model, exercising the guardrails and fallback paths. Lint with `ruff check .`
(config in `ruff.toml`).

### Test taxonomy (Unit / Integration / System / Stress / Security)

The `tests/` folder at the repo root organizes testing by the standard
taxonomy and maps each type to concrete tests — see
[`tests/README.md`](tests/README.md). Fast unit/integration tests live next to
each service; the cross-service suite adds:

```bash
pytest tests/                              # Security (RBAC, auth-bypass, injection, spam, uploads)
                                           #  + System (end-to-end, skips if no stack)
```

**Stress / load testing ("swarming")** uses **Locust** — a swarm of scripted
users measuring throughput, latency and error rate
([`tests/Stress_Tests/`](tests/Stress_Tests)):

```bash
docker compose up -d
pip install -r tests/Stress_Tests/requirements.txt
locust -f tests/Stress_Tests/locustfile.py --host http://localhost:8080
```

(Apache Bench and the race-condition concurrency test are covered there too.)

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`):

1. **lint-test** — ruff + pytest for each service, in parallel.
2. **docker-smoke** — builds the real images, boots the whole stack with
   docker compose and runs `scripts/smoke_test.py` against the public gateway.
3. **publish** — on `main` only: pushes the three images to GitHub Container
   Registry (`ghcr.io/<repo>/<service>:latest` and `:<sha>`).

## API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/register`, `POST /api/auth/login` |
| Tickets | `POST/GET /api/tickets`, `GET/PATCH /api/tickets/{id}` (staff: `resolution`), `POST /api/tickets/{id}/assign` |
| Comments | `GET/POST /api/tickets/{id}/comments` |
| AI | `POST /api/tickets/{id}/ai/copilot`, `GET /api/tickets/{id}/ai/duplicates`, `GET /api/ai/status` (staff: model state + scheduler stats) |
| Queue | `GET /api/queue`, `GET /api/queue/stats`, `POST /api/queue/claim` |
| Incidents | `GET /api/incidents` (staff: complaints clustered into incidents by the local model) |
| Forums | `GET /api/forums/boards`, `GET/POST /api/forums/boards/{slug}/threads`, `GET /api/forums/threads/{id}`, `POST /api/forums/threads/{id}/posts`, `PATCH /api/forums/threads/{id}`, `DELETE /api/forums/posts/{id}` |
| Admin | `GET /api/admin/users`, `PATCH /api/admin/users/{id}/role` |

Roles: `USER` (own tickets + forums), `AGENT` (all tickets, queue, AI copilot,
forum moderation), `ADMIN` (+ user management). Ticket classification is
asynchronous: `ai_suggested.status` moves `pending → ok | unavailable`.

## Project layout

```
smartdesk/
├── docker-compose.yml
├── ruff.toml                  shared lint config
├── scripts/smoke_test.py      end-to-end test (stdlib only, used by CI)
├── .github/workflows/ci.yml   lint+test / docker smoke / publish to GHCR
├── tests/                     cross-service tests by taxonomy (see tests/README)
│   └── {Security,System,Stress}_Tests   RBAC/injection · e2e · Locust swarm
├── api-service/               public gateway: auth, tickets, comments, queue,
│   ├── app/{routers,services,schemas,models}        forum proxy, admin
│   └── app/static/            the Freshdesk-style web UI (served at /)
├── ai-service/                local LLM: classify, copilot (KB-grounded),
│   └── app/{routers,services,data}                  duplicates, long-term memory, guardrails
└── forum-service/             per-department boards, threads, posts
    └── app/routers
```
