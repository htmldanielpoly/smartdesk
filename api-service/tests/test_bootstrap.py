"""Tests for the first-admin bootstrap."""
from app.config import settings
from app.services.bootstrap import ensure_admin


async def test_bootstrap_creates_admin_once(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "root@example.com")
    monkeypatch.setattr(settings, "admin_password", "super-secret-1")

    await ensure_admin()
    await ensure_admin()  # idempotent

    admins = [u async for u in db.users.find({"role": "ADMIN"})]
    assert len(admins) == 1
    assert admins[0]["email"] == "root@example.com"
    assert admins[0]["passwordHash"] != "super-secret-1"  # hashed, not plain


async def test_bootstrap_skipped_without_config(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_email", "")
    monkeypatch.setattr(settings, "admin_password", "")

    await ensure_admin()
    assert await db.users.find_one({"role": "ADMIN"}) is None


async def test_bootstrap_admin_can_login(db, monkeypatch, client):
    monkeypatch.setattr(settings, "admin_email", "root@example.com")
    monkeypatch.setattr(settings, "admin_password", "super-secret-1")
    await ensure_admin()

    r = client.post(
        "/api/auth/login",
        json={"email": "root@example.com", "password": "super-secret-1"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"
