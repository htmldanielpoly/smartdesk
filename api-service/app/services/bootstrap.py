"""First-run bootstrap: create the initial admin account.

Self-registration only ever creates USERs and only an ADMIN can promote
roles, so a fresh database would otherwise have no way to get its first
admin. If ADMIN_EMAIL/ADMIN_PASSWORD are configured and no admin exists yet,
one is created at startup. Idempotent: an existing admin short-circuits.
"""
import logging
from datetime import UTC, datetime

from app.config import settings
from app.database import get_db
from app.models.enums import Role
from app.security import hash_password

logger = logging.getLogger(__name__)


async def ensure_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        return

    db = get_db()
    if await db.users.find_one({"role": Role.ADMIN.value}) is not None:
        return

    await db.users.update_one(
        {"email": settings.admin_email.lower()},
        {
            "$set": {"role": Role.ADMIN.value},
            "$setOnInsert": {
                "email": settings.admin_email.lower(),
                "passwordHash": hash_password(settings.admin_password),
                "displayName": "Administrator",
                "department": None,
                "createdAt": datetime.now(UTC),
            },
        },
        upsert=True,
    )
    logger.info("Bootstrap admin ensured: %s", settings.admin_email)

# Seed users — realistic fake accounts for demo and grading
_SEED_USERS = [
    {"email": "alice@example.com",   "name": "Alice Chen",    "role": Role.USER.value},
    {"email": "bob@example.com",     "name": "Bob Martinez",  "role": Role.USER.value},
    {"email": "carol@example.com",   "name": "Carol Singh",   "role": Role.USER.value},
    {"email": "david@example.com",   "name": "David Kim",     "role": Role.USER.value},
    {"email": "eve@example.com",     "name": "Eve Goldstein", "role": Role.USER.value},
    {"email": "agent1@example.com",  "name": "Agent Sarah",   "role": Role.AGENT.value},
    {"email": "agent2@example.com",  "name": "Agent Tom",     "role": Role.AGENT.value},
]
_SEED_PASSWORD = "password123"


async def ensure_seed_users() -> None:
    """Idempotent: insert demo users on first run. Skips existing emails."""
    db = get_db()
    for u in _SEED_USERS:
        existing = await db.users.find_one({"email": u["email"]})
        if existing:
            continue
        await db.users.insert_one({
            "email": u["email"],
            "passwordHash": hash_password(_SEED_PASSWORD),
            "displayName": u["name"],
            "role": u["role"],
            "department": None,
            "createdAt": datetime.now(UTC),
        })
    logger.info("Seed users ensured.")