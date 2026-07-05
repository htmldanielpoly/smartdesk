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
