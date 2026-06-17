# SmartDesk

SmartDesk is a web-based, AI-powered support ticket management system. Users can
submit support tickets, track their status, communicate with support agents, and
receive updates throughout the resolution process. AI assists agents with ticket
classification, drafting responses, and spotting duplicate incidents — but never
blocks the core workflow.

## Architecture

Microservices on a private Docker network; only the API service is exposed.

| Service | Stack | Port | Exposed? |
|---|---|---|---|
| `api-service` | Python · FastAPI | 8080 | yes (the only public entrypoint) |
| `ai-service` | Python · FastAPI | 8000 | internal only |
| `mongo` | MongoDB 7 | 27017 | internal only |

The AI service runs with **rule-based fallbacks** when no OpenAI key is set, so
the whole system is fully runnable without any external API key.

## Quick start (Docker)

```bash
cp .env.example .env        # optionally add your OPENAI_API_KEY
docker compose up --build
```

Then open http://localhost:8080/docs for the interactive API (Swagger UI).

## Quick start (local, per service)

Each service is independent. From its folder:

```bash
# api-service (needs a local MongoDB on :27017)
cd api-service
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8080

# ai-service
cd ai-service
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Running tests

```bash
cd api-service && pip install -r requirements-dev.txt && pytest
cd ai-service  && pip install -r requirements-dev.txt && pytest
```

The api-service tests use an in-memory MongoDB (`mongomock-motor`) and stub the
AI service, so **no Docker or external services are required** to run them.

## API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/register`, `POST /api/auth/login` |
| Tickets | `POST/GET /api/tickets`, `GET/PATCH /api/tickets/{id}`, `POST /api/tickets/{id}/assign` |
| Comments | `GET/POST /api/tickets/{id}/comments` |
| AI | `POST /api/tickets/{id}/ai/copilot`, `GET /api/tickets/{id}/ai/duplicates` |
| Admin | `GET /api/admin/users`, `PATCH /api/admin/users/{id}/role` |

Roles: `USER` (own tickets), `AGENT` (all tickets + AI copilot), `ADMIN` (+ user
management). Self-registration always creates a `USER`; an admin promotes others.

## Roadmap status

- [x] Phase 1 — Foundation: services, docker-compose, Mongo wiring, tests
- [x] Phase 2 — Auth: register/login/JWT/roles + rate limiting
- [x] Phase 3 — Ticketing: CRUD, status machine, assignment, comments, activity log
- [x] Phase 4 — AI integration: classify on create, with fallback
- [x] Phase 5 — AI copilot + duplicate detection
- [ ] Phase 6 — Hardening: stress tests, e2e suite, fuller security tests, frontend

## Project layout

```
smartdesk/
├── docker-compose.yml
├── api-service/        FastAPI backend (auth, tickets, comments, AI proxy)
│   └── app/{routers,services,schemas,models}
└── ai-service/         FastAPI AI service (classify, copilot, duplicates)
    └── app/{routers,services}
```
