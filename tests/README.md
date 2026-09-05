# SmartDesk Test Suite — organized by the testing-lecture taxonomy

The testing lecture defines five kinds of tests (Unit, Integration, System,
Stress, Security) plus the idea of a **regression** suite you re-run after every
change so you're "not afraid to change the code". This folder mirrors that
taxonomy at the repo root, and points to the fast per-service tests that already
live next to the code they test.

```
tests/
├── Unit_Tests/          -> see per-service tests/ (pure logic, no I/O)
├── Integration_Tests/   -> see per-service tests/ (feature wiring over HTTP)
├── Security_Tests/      auth-bypass, RBAC, data isolation, injection
├── System_Tests/        full end-to-end journey through the live gateway
└── Stress_Tests/        Locust swarm + Apache Bench + concurrency test
```

## Taxonomy → where it lives

| Lecture test type | What it checks | In this project |
|---|---|---|
| **Unit** | one function/class in isolation; tests independent of the impl | `api-service/tests/test_queueing.py` (queue scoring, SLA, aging), `test_security.py` (hashing/JWT), `test_status_transitions.py` (state machine), `ai-service/tests/test_guardrails.py`, `test_fallback.py` |
| **Integration** | features wired together, "behave like a user" over the HTTP REST API | `api-service/tests/test_tickets_flow.py`, `test_queue_api.py`, `test_forums_gateway.py`, `test_bootstrap.py`, `forum-service/tests/test_threads_flow.py`, `test_posts.py`, `test_boards.py` |
| **System** | the whole stack end-to-end, closest to "real", hardest to localize | [`System_Tests/test_end_to_end.py`](./System_Tests) → runs `scripts/smoke_test.py` against the live gateway |
| **Stress** | resilience under many concurrent users / heavy load | [`Stress_Tests/`](./Stress_Tests) — **Locust** swarm, **Apache Bench**, and the `test_concurrent_claims_*` race test |
| **Security** | try to break in: no-auth, forged tokens, role/data boundaries | [`Security_Tests/test_access_control.py`](./Security_Tests) |
| **Regression** | re-run everything on every change (CI) | `.github/workflows/ci.yml` runs the whole suite on every push |

## Test-only endpoints

`forum-service` has one route that exists purely for tests: `GET
/debug/ws-connections/{user_id}` (in `forum-service/app/routers/forum.py`),
which reports how many live WebSocket connections `ConnectionManager` holds
for a user — used by
[`Security_Tests/test_websocket_disconnect_cleans_up_connection.py`](./Security_Tests)
to check that a disconnect actually gets cleaned up. It 404s unless
`ENABLE_TEST_ENDPOINTS=true`, which is never set in `docker-compose.yml`'s
defaults — only via `docker-compose.test.yml` (see that file for the exact
command). In any normal deployment this route does not respond.

## Running it all

```bash
# Fast per-service suites (no Docker, no Mongo, no models):
cd api-service   && pytest      # unit + integration
cd ai-service    && pytest      # guardrails + fallbacks
cd forum-service && pytest      # forum integration

# Cross-service taxonomy suite (from repo root):
pip install -r api-service/requirements-dev.txt   # provides the deps it imports
pytest tests/                    # Security + System (skips if no stack)

# Stress / load — needs a running stack, driven by Locust (see Stress_Tests/):
docker compose up -d
locust -f tests/Stress_Tests/locustfile.py --host http://localhost:8080
```

`System_Tests` **skip** automatically when no stack is reachable at
`SMARTDESK_URL` (default `http://localhost:8080`), so the whole `pytest tests/`
run stays green on a laptop with nothing booted. Bring the stack up to exercise
them for real.

## Test-design notes (from the lecture)

- **Tests are independent of the implementation** — the queue scoring tests
  assert *behavior* (URGENT outranks LOW, aging prevents starvation) computed
  from the documented constants, not a golden number copied out of the code.
- **Each test checks one thing** and fails for one reason — see the focused
  cases in `test_status_transitions.py`.
- **Fixtures** set up and tear down state (`conftest.py` injects a fresh
  in-memory Mongo per test), so tests don't leak into each other.
- **Fail-safe over fail-loud** for AI: the security/integration suites assert
  the core flow still works when the AI service is unavailable or attacked.
