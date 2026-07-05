"""Convert MongoDB documents into API response dicts (ObjectId -> str)."""


def serialize_board(doc: dict, thread_count: int = 0) -> dict:
    return {
        "slug": doc["slug"],
        "name": doc["name"],
        "category": doc["category"],
        "thread_count": thread_count,
    }


def serialize_thread(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "board_slug": doc["boardSlug"],
        "title": doc["title"],
        "author_id": doc["authorId"],
        "author_role": doc["authorRole"],
        "created_at": doc["createdAt"],
        "last_post_at": doc["lastPostAt"],
        "post_count": doc["postCount"],
        "locked": doc.get("locked", False),
        "pinned": doc.get("pinned", False),
    }


def serialize_post(doc: dict) -> dict:
    deleted = doc.get("deleted", False)
    return {
        "id": str(doc["_id"]),
        "thread_id": str(doc["threadId"]),
        "author_id": doc["authorId"],
        "author_role": doc["authorRole"],
        "body": "[deleted]" if deleted else doc["body"],
        "deleted": deleted,
        "created_at": doc["createdAt"],
    }
