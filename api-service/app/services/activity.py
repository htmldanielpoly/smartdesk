from datetime import UTC, datetime

from bson import ObjectId

from app.database import get_db


async def log(ticket_id: ObjectId, actor_id: ObjectId, action: str, **details) -> None:
    """Append an immutable entry to the ticket activity log."""
    await get_db().activity_log.insert_one(
        {
            "ticketId": ticket_id,
            "actorId": actor_id,
            "action": action,
            "details": details,
            "timestamp": datetime.now(UTC),
        }
    )
