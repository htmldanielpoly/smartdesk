# Integration Tests

> *Integration testing: check that features work together — that nothing breaks
> where the parts connect. Behave like a real user by talking to the software
> through its interface; for a web app, the HTTP REST API.*

This folder holds representative integration tests (`test_ticket_journey.py` —
register → login → create ticket → view, plus ownership isolation). Integration
tests drive the **real FastAPI app** against an in-memory MongoDB
(`mongomock-motor`) — no Docker, no Mongo, no model files — and act like a user
calling the HTTP API. The **full** suite lives in each service's `tests/`
folder:

| File | Feature wiring under test |
|---|---|
| `api-service/tests/test_tickets_flow.py` | register → login → create ticket → view; ownership isolation; AI-unavailable fallback |
| `api-service/tests/test_queue_api.py` | queue listing/stats/claim over HTTP; RBAC; concurrency |
| `api-service/tests/test_forums_gateway.py` | forum reverse-proxy through the gateway |
| `api-service/tests/test_bootstrap.py` | first-admin bootstrap at startup |
| `forum-service/tests/test_threads_flow.py` | create thread → reply → moderate (lock/pin) |
| `forum-service/tests/test_posts.py` | post creation, soft-delete, permissions |
| `forum-service/tests/test_boards.py` | board seeding and listing |

Run them:

```bash
cd api-service   && pytest
cd forum-service && pytest
```
