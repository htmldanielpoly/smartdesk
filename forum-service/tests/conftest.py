"""Shared fixtures for integration tests.

These run the real FastAPI app against an in-memory MongoDB (mongomock-motor),
so no Docker/Mongo is required. Tokens are signed locally with the same secret
the app config uses, mimicking what the api-service would issue.
"""
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from mongomock_motor import AsyncMongoMockClient
from starlette.testclient import TestClient

from app import database
from app.config import settings
from app.main import app
from app.seed import seed_boards


@pytest.fixture
async def db():
    mock = AsyncMongoMockClient()["smartdesk_forum_test"]
    database.set_db(mock)
    await seed_boards(mock)
    yield mock


@pytest.fixture
def client(db):
    # Not used as a context manager -> app lifespan (real DB connect) is skipped.
    return TestClient(app)


def make_token(user_id: str, role: str = "USER") -> str:
    """Sign a JWT exactly like the api-service does (shared secret + claims)."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=60),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def auth_header(user_id: str, role: str = "USER") -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, role)}"}
