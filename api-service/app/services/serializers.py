"""Convert MongoDB documents into API response dicts (ObjectId -> str)."""


def serialize_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "email": doc["email"],
        "display_name": doc["displayName"],
        "role": doc["role"],
        "department": doc.get("department"),
    }


def _serialize_auto_resolved(info: dict | None) -> dict | None:
    if not info:
        return None
    return {
        "source_ticket_id": str(info.get("sourceTicketId")),
        "similarity": info.get("similarity", 0.0),
        "threshold": info.get("threshold"),
        "source": info.get("source", "ai"),
        "at": info.get("at"),
        "reopened_at": info.get("reopenedAt"),
    }


def serialize_ticket(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "title": doc["title"],
        "description": doc["description"],
        "status": doc["status"],
        "created_by": str(doc["createdBy"]),
        "assigned_agent": str(doc["assignedAgent"]) if doc.get("assignedAgent") else None,
        "category": doc.get("category"),
        "priority": doc.get("priority"),
        "department": doc.get("department"),
        "resolution": doc.get("resolution"),
        "ai_suggested": doc.get("aiSuggested"),
        "auto_resolved": _serialize_auto_resolved(doc.get("autoResolved")),
        "created_at": doc["createdAt"],
        "updated_at": doc["updatedAt"],
    }


def serialize_comment(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "ticket_id": str(doc["ticketId"]),
        "author_id": str(doc["authorId"]) if doc.get("authorId") else None,
        "author_type": doc.get("authorType", "user"),
        "body": doc["body"],
        "internal": doc.get("internal", False),
        "created_at": doc["createdAt"],
    }
