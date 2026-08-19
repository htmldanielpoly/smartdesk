"""Convert MongoDB documents into API response dicts (ObjectId -> str)."""

def serialize_board(doc: dict, thread_count: int = 0) -> dict:
    return {
        "slug": doc["slug"],
        "name": doc["name"],
        "category": doc["category"],
        "thread_count": thread_count,
    }

def serialize_thread(doc: dict) -> dict:
    is_anon = doc.get("isAnonymous", False)
    return {
        "id": str(doc["_id"]),
        "board_slug": doc["boardSlug"],
        "title": doc["title"],
        # Defensively scrub author data if the thread is anonymous
        "author_id": None if is_anon else doc.get("authorId"),
        "author_role": None if is_anon else doc.get("authorRole"),
        "is_anonymous": is_anon,
        "created_at": doc["createdAt"],
        "last_post_at": doc["lastPostAt"],
        "post_count": doc["postCount"],
        "locked": doc.get("locked", False),
        "pinned": doc.get("pinned", False),
        "media_urls": doc.get("mediaUrls", []),
        "likes": doc.get("likes", []),
        "dislikes": doc.get("dislikes", []),
    }

def serialize_post(doc: dict) -> dict:
    deleted = doc.get("deleted", False)
    is_anon = doc.get("isAnonymous", False)
    return {
        "id": str(doc["_id"]),
        "thread_id": str(doc["threadId"]),
        # Defensively scrub author data if the post is anonymous
        "author_id": None if is_anon else doc.get("authorId"),
        "author_role": None if is_anon else doc.get("authorRole"),
        "is_anonymous": is_anon,
        "body": "[deleted]" if deleted else doc["body"],
        "deleted": deleted,
        "created_at": doc["createdAt"],
        "media_urls": doc.get("mediaUrls", []),
        "likes": doc.get("likes", []),
        "dislikes": doc.get("dislikes", []),
    }