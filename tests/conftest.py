"""Shared fixtures for the cross-service, taxonomy-organized test suite.

The Security tests drive the *real* api-service FastAPI app against an
in-memory MongoDB (mongomock-motor) — no Docker, no Mongo, no model files —
exactly like the per-service integration tests. We add the api-service folder
to ``sys.path`` so its ``app`` package is importable from the repo root.
"""
import sys
from pathlib import Path

import pytest

# Make the api-service `app` package importable for the in-memory app fixtures.
API_SERVICE = Path(__file__).resolve().parent.parent / "api-service"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))


@pytest.fixture
async def db():
    from mongomock_motor import AsyncMongoMockClient

    from app import database

    mock = AsyncMongoMockClient()["smartdesk_test"]
    await mock.users.create_index("email", unique=True)
    database.set_db(mock)
    yield mock


@pytest.fixture
def client(db, monkeypatch):
    from starlette.testclient import TestClient

    from app.main import app
    from app.rate_limit import reset as reset_rate_limit
    from app.services import ai_client

    reset_rate_limit()

    # Treat the AI service as unavailable so the core flow is exercised alone.
    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(ai_client, "classify", _none)
    monkeypatch.setattr(ai_client, "copilot", _none)
    monkeypatch.setattr(ai_client, "duplicates", _none)

    # No context manager -> app lifespan (real DB connect) is skipped.
    return TestClient(app)


def register(client, email, password="password123", name="Test User"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
