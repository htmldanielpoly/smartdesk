"""Resolve user ids to display names in one query, so API responses can show
"Dana Levi" instead of a six-character id suffix."""
from bson import ObjectId

from app.database import get_db


async def display_names(ids) -> dict[ObjectId, str]:
    wanted = {i for i in ids if isinstance(i, ObjectId)}
    if not wanted:
        return {}
    cursor = get_db().users.find({"_id": {"$in": list(wanted)}}, {"displayName": 1, "email": 1})
    return {
        u["_id"]: (u.get("displayName") or u.get("email") or str(u["_id"])) async for u in cursor
    }
