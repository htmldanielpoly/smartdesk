# SmartDesk

SmartDesk is a web-based, AI-powered support ticket management system. Users
submit support tickets, track their status, discuss issues on per-department
forums, and communicate with support agents. AI assists agents with ticket
classification, drafting grounded responses, and spotting duplicate incidents —
and it all runs **locally, on open-weights models, with no API keys** and no
data leaving the machine. AI never blocks the core workflow.

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

## AI safety: no hallucinations, no jailbreaks

Defense in depth, tested by a dedicated guardrail test suite
(`ai-service/tests/test_guardrails.py`):

1. **Constrained decoding** — every LLM call is grammar-constrained to a JSON
   schema (llama.cpp compiles it into the sampler). Category/priority are
   *enums in the grammar*: an invalid label cannot even be generated.
2. **Prompt-injection detection** — tickets matching jailbreak patterns
   ("ignore previous instructions", persona switches, ...) never reach the
   model; they are classified by deterministic rules and flagged
   `injection_suspected`.
3. **Input sanitization** — chat-template control tokens (`<|im_start|>` etc.)
   and control characters are stripped, lengths capped, and ticket text is
   fenced as untrusted data in the prompt.
4. **Grounded copilot (RAG or refuse)** — the copilot may only answer from the
   curated knowledge base (`ai-service/app/data/kb_articles.json`). If no
   article is similar enough to the ticket, it *refuses to generate* and
   returns a safe template. Citations are grammar-constrained to the retrieved
   article ids and validated after generation; a draft that cites nothing real
   or contains a URL not present in the KB is discarded.
5. **The model never decides alone** — departments are derived server-side
   from the category; all labels are whitelist-validated again after decoding.

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

## Quick start (Docker)

```bash
cp .env.example .env        # defaults work out of the box
docker compose up --build
```

Then open **http://localhost:8080/** for the SmartDesk web app, or
http://localhost:8080/docs for the interactive API (Swagger UI).
First start downloads ~450 MB of model files in the background; AI answers
use rule-based fallbacks until the models are ready (watch
`docker compose logs -f ai-service`). Set `LOCAL_AI_ENABLED=false` in `.env`
to skip local AI entirely.

A bootstrap admin is created on first start from `ADMIN_EMAIL`/`ADMIN_PASSWORD`
in `.env` (self-registration only creates regular users; the admin promotes
agents).

### End-to-end smoke test

With the stack running:

```bash
python scripts/smoke_test.py
```

It exercises the full journey through the public gateway: register → ticket →
async AI classification → injection attempt → agent promotion → queue claim →
copilot → comments → status machine → forums. CI runs the same script.

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
cd api-service   && pip install -r requirements-dev.txt && pytest   # 39 tests
cd ai-service    && pip install -r requirements-dev.txt && pytest   # 31 tests
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
pytest tests/                              # Security (RBAC, auth-bypass, injection)
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
| Tickets | `POST/GET /api/tickets`, `GET/PATCH /api/tickets/{id}`, `POST /api/tickets/{id}/assign` |
| Comments | `GET/POST /api/tickets/{id}/comments` |
| AI | `POST /api/tickets/{id}/ai/copilot`, `GET /api/tickets/{id}/ai/duplicates` |
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
│   └── app/{routers,services,data}                  duplicates, guardrails
└── forum-service/             per-department boards, threads, posts
    └── app/routers
```
