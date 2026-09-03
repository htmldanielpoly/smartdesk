"""Shared fixtures for integration tests.

These run the real FastAPI app against an in-memory MongoDB (mongomock-motor),
so no Docker/Mongo is required. The AI client is patched to behave as if the AI
service is unavailable, exercising the graceful-fallback paths.
"""
import pytest
from mongomock_motor import AsyncMongoMockClient
from starlette.testclient import TestClient

from app import database
from app.main import app
from app.rate_limit import reset as reset_rate_limit
from app.services import ai_client


@pytest.fixture
async def db():
    mock = AsyncMongoMockClient()["smartdesk_test"]
    await mock.users.create_index("email", unique=True)
    database.set_db(mock)
    yield mock


@pytest.fixture
def client(db, monkeypatch):
    reset_rate_limit()

    # Simulate the AI service being unavailable by default.
    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(ai_client, "classify", _none)
    monkeypatch.setattr(ai_client, "copilot", _none)
    monkeypatch.setattr(ai_client, "duplicates", _none)
    monkeypatch.setattr(ai_client, "auto_resolve", _none)
    monkeypatch.setattr(ai_client, "assist", _none)

    # Not used as a context manager -> app lifespan (real DB connect) is skipped.
    return TestClient(app)


def register(client, email, password="password123", name="Test User"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
