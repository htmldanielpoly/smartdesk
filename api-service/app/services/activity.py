from datetime import UTC, datetime

from bson import ObjectId

from app.database import get_db


async def log(
    ticket_id: ObjectId, actor_id: ObjectId | None, action: str, **details
) -> None:
    """Append an immutable entry to the ticket activity log.

    ``actor_id`` is None for actions taken by the system/AI (e.g. a ticket
    answered from long-term memory)."""
    await get_db().activity_log.insert_one(
        {
            "ticketId": ticket_id,
            "actorId": actor_id,
            "action": action,
            "details": details,
            "timestamp": datetime.now(UTC),
        }
    )
