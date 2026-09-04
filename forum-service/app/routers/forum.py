from datetime import UTC, datetime

import os
import uuid
from fastapi import UploadFile, File
from fastapi.responses import FileResponse

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status,WebSocket, WebSocketDisconnect
from app.rate_limit import rate_limit, rate_limit_post, rate_limit_message

from app.config import settings
from app.database import get_db
from app.deps import Role, get_current_user, require_roles,get_ws_user
from app.schemas import (
    BoardOut,
    PostCreate,
    PostOut,
    ThreadCreate,
    ThreadDetail,
    ThreadModerate,
    ThreadOut,
    ThreadPage,
    DirectMessageCreate,
    DirectMessageOut
)
from app.websockets import manager
from app.serializers import serialize_board, serialize_post, serialize_thread

router = APIRouter(tags=["forum"])


def _oid(raw_id: str, detail: str) -> ObjectId:
    if not ObjectId.is_valid(raw_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return ObjectId(raw_id)


async def _get_board_or_404(slug: str) -> dict:
    board = await get_db().boards.find_one({"slug": slug})
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    return board


async def _get_thread_or_404(thread_id: str) -> dict:
    thread = await get_db().threads.find_one({"_id": _oid(thread_id, "Thread not found")})
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return thread


async def _get_post_or_404(post_id: str) -> dict:
    post = await get_db().posts.find_one({"_id": _oid(post_id, "Post not found")})
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


def _is_staff(user: dict) -> bool:
    return user["role"] in (Role.AGENT.value, Role.ADMIN.value)


# --- Existing Endpoints (Updated with new schema fields) ---

@router.get("/boards", response_model=list[BoardOut])
async def list_boards(user: dict = Depends(get_current_user)):
    """One board per support department, in seed order, with thread counts."""
    boards = []
    async for board in get_db().boards.find({}).sort("order", 1):
        count = await get_db().threads.count_documents({"boardSlug": board["slug"]})
        boards.append(serialize_board(board, thread_count=count))
    return boards


@router.get("/boards/{slug}/threads", response_model=ThreadPage)
async def list_threads(
        slug: str,
        page: int = Query(default=1, ge=1),
        user: dict = Depends(get_current_user),
):
    """Threads on a board: pinned first, then newest activity first."""
    board = await _get_board_or_404(slug)

    query = {"boardSlug": board["slug"]}
    total = await get_db().threads.count_documents(query)
    cursor = (
        get_db()
        .threads.find(query)
        .sort([("pinned", -1), ("lastPostAt", -1)])
        .skip((page - 1) * settings.page_size)
        .limit(settings.page_size)
    )
    return ThreadPage(
        items=[serialize_thread(t) async for t in cursor],
        page=page,
        page_size=settings.page_size,
        total=total,
    )


@router.post(
    "/boards/{slug}/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED
)
async def create_thread(
        slug: str,
        payload: ThreadCreate,
        user: dict = Depends(get_current_user),
        _: None = Depends(rate_limit_post),
):
    """Any authenticated user opens a thread; its body becomes the first post."""
    board = await _get_board_or_404(slug)

    now = datetime.now(UTC)

    # NEW: Initialize engagement arrays and handle anonymity/media
    thread_doc = {
        "boardSlug": board["slug"],
        "title": payload.title,
        "authorId": user["id"],
        "authorRole": user["role"],
        "isAnonymous": payload.is_anonymous,
        "mediaUrls": payload.media_urls,
        "createdAt": now,
        "lastPostAt": now,
        "postCount": 1,
        "locked": False,
        "pinned": False,
        "likes": [],
        "dislikes": []
    }
    result = await get_db().threads.insert_one(thread_doc)
    thread_doc["_id"] = result.inserted_id

    await get_db().posts.insert_one(
        {
            "threadId": result.inserted_id,
            "authorId": user["id"],
            "authorRole": user["role"],
            "isAnonymous": payload.is_anonymous,
            "mediaUrls": payload.media_urls,
            "body": payload.body,
            "deleted": False,
            "createdAt": now,
            "likes": [],
            "dislikes": []
        }
    )
    return serialize_thread(thread_doc)


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: str, user: dict = Depends(get_current_user)):
    thread = await _get_thread_or_404(thread_id)
    cursor = get_db().posts.find({"threadId": thread["_id"]}).sort("createdAt", 1)
    return ThreadDetail(
        thread=serialize_thread(thread),
        posts=[serialize_post(p) async for p in cursor],
    )


@router.post(
    "/threads/{thread_id}/posts", response_model=PostOut, status_code=status.HTTP_201_CREATED
)
async def create_post(
        thread_id: str,
        payload: PostCreate,
        user: dict = Depends(get_current_user),
        _: None = Depends(rate_limit_post),
):
    thread = await _get_thread_or_404(thread_id)
    if thread.get("locked", False):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Thread is locked")

    if not payload.body.strip() and not payload.media_urls:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Post must include text or an attachment")

    now = datetime.now(UTC)
    doc = {
        "threadId": thread["_id"],
        "authorId": user["id"],
        "authorRole": user["role"],
        "isAnonymous": payload.is_anonymous,
        "mediaUrls": payload.media_urls,
        "body": payload.body,
        "deleted": False,
        "createdAt": now,
        "likes": [],
        "dislikes": []
    }
    result = await get_db().posts.insert_one(doc)
    doc["_id"] = result.inserted_id

    await get_db().threads.update_one(
        {"_id": thread["_id"]},
        {"$set": {"lastPostAt": now}, "$inc": {"postCount": 1}},
    )
    return serialize_post(doc)


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def moderate_thread(
        thread_id: str,
        payload: ThreadModerate,
        user: dict = Depends(require_roles(Role.AGENT, Role.ADMIN)),
):
    """AGENT/ADMIN moderation: lock (no new replies) and/or pin (sort first)."""
    thread = await _get_thread_or_404(thread_id)

    updates: dict = {}
    if payload.locked is not None:
        updates["locked"] = payload.locked
    if payload.pinned is not None:
        updates["pinned"] = payload.pinned
    if updates:
        await get_db().threads.update_one({"_id": thread["_id"]}, {"$set": updates})

    return serialize_thread(await _get_thread_or_404(thread_id))


@router.delete("/posts/{post_id}", response_model=PostOut)
async def delete_post(post_id: str, user: dict = Depends(get_current_user)):
    """Soft-delete a post (author or staff). The thread itself is never deleted."""
    post = await get_db().posts.find_one({"_id": _oid(post_id, "Post not found")})
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["authorId"] != user["id"] and not _is_staff(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await get_db().posts.update_one({"_id": post["_id"]}, {"$set": {"deleted": True}})
    post["deleted"] = True
    return serialize_post(post)


# --- NEW: Engagement Endpoints ---

@router.post("/threads/{thread_id}/like", status_code=status.HTTP_200_OK)
async def like_thread(thread_id: str, user: dict = Depends(get_current_user)):
    thread = await _get_thread_or_404(thread_id)
    await get_db().threads.update_one(
        {"_id": thread["_id"]},
        {"$addToSet": {"likes": user["id"]}, "$pull": {"dislikes": user["id"]}}
    )
    # Notify thread owner if someone else liked it
    owner_id = thread.get("authorId")
    if owner_id and owner_id != user["id"]:
        await manager.send_personal_message({
            "type": "like_notification",
            "data": {
                "kind": "thread",
                "action": "like",
                "thread_id": thread_id,
                "title": thread["title"],
                "by_user": user["id"],
            }
        }, owner_id)
    return {"detail": "Thread liked successfully"}


@router.post("/threads/{thread_id}/dislike", status_code=status.HTTP_200_OK)
async def dislike_thread(thread_id: str, user: dict = Depends(get_current_user)):
    thread = await _get_thread_or_404(thread_id)
    await get_db().threads.update_one(
        {"_id": thread["_id"]},
        {"$addToSet": {"dislikes": user["id"]}, "$pull": {"likes": user["id"]}}
    )
    owner_id = thread.get("authorId")
    if owner_id and owner_id != user["id"] :
        await manager.send_personal_message({
            "type": "like_notification",
            "data": {
                "kind": "thread",
                "action": "dislike",
                "thread_id": thread_id,
                "title": thread["title"],
                "by_user": user["id"],
            }
        }, owner_id)
    return {"detail": "Thread disliked successfully"}


@router.post("/posts/{post_id}/like", status_code=status.HTTP_200_OK)
async def like_post(post_id: str, user: dict = Depends(get_current_user)):
    post = await _get_post_or_404(post_id)
    await get_db().posts.update_one(
        {"_id": post["_id"]},
        {"$addToSet": {"likes": user["id"]}, "$pull": {"dislikes": user["id"]}}
    )
    owner_id = post.get("authorId")
    if owner_id and owner_id != user["id"] :
        await manager.send_personal_message({
            "type": "like_notification",
            "data": {
                "kind": "post",
                "action": "like",
                "thread_id": str(post["threadId"]),
                "by_user": user["id"],
            }
        }, owner_id)
    return {"detail": "Post liked successfully"}


@router.post("/posts/{post_id}/dislike", status_code=status.HTTP_200_OK)
async def dislike_post(post_id: str, user: dict = Depends(get_current_user)):
    post = await _get_post_or_404(post_id)
    await get_db().posts.update_one(
        {"_id": post["_id"]},
        {"$addToSet": {"dislikes": user["id"]}, "$pull": {"likes": user["id"]}}
    )
    owner_id = post.get("authorId")
    if owner_id and owner_id != user["id"] :
        await manager.send_personal_message({
            "type": "like_notification",
            "data": {
                "kind": "post",
                "action": "dislike",
                "thread_id": str(post["threadId"]),
                "by_user": user["id"],
            }
        }, owner_id)
    return {"detail": "Post disliked successfully"}


# --- NEW: Direct Messaging Endpoints ---

def _serialize_dm(doc: dict) -> dict:
    """Helper to convert MongoDB _id to string id for Pydantic."""
    doc["id"] = str(doc.pop("_id"))

    # Convert datetime to an ISO 8601 string so json.dumps can serialize it
    if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
        doc["created_at"] = doc["created_at"].isoformat()

    return doc


@router.post("/messages", response_model=DirectMessageOut, status_code=status.HTTP_201_CREATED)
async def create_direct_message(
        payload: DirectMessageCreate,
        user: dict = Depends(get_current_user),
        _: None = Depends(rate_limit_message),
):
    """Sends a direct message to another user."""
    if not payload.content.strip() and not payload.media_urls:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message must include text or an attachment")

    doc = {
        "sender_id": user["id"],
        "recipient_id": payload.recipient_id,
        "content": payload.content,
        "media_urls": payload.media_urls,
        "created_at": datetime.now(UTC),
        "is_read": False
    }
    result = await get_db().direct_messages.insert_one(doc)
    doc["_id"] = result.inserted_id

    serialized_dm = _serialize_dm(doc)

    # NEW: Send real-time notification to the recipient
    notification_payload = {
        "type": "new_direct_message",
        "data": serialized_dm
    }
    await manager.send_personal_message(notification_payload, payload.recipient_id)

    return serialized_dm

@router.get("/messages/{other_user_id}", response_model=list[DirectMessageOut])
async def get_direct_messages(
        other_user_id: str,
        limit: int = Query(default=50, le=100),
        user: dict = Depends(get_current_user)
):
    """Retrieves chronological chat history between current user and another user."""
    query = {
        "$or": [
            {"sender_id": user["id"], "recipient_id": other_user_id},
            {"sender_id": other_user_id, "recipient_id": user["id"]}
        ]
    }
    cursor = get_db().direct_messages.find(query).sort("created_at", 1).limit(limit)
    return [_serialize_dm(doc) async for doc in cursor]






@router.get("/me/summary")
async def my_summary(user: dict = Depends(get_current_user)):
    """Returns the current user's threads, posts, and total likes/dislikes."""
    user_id = user["id"]

    # My threads (non-anonymous only)
    threads = []
    async for t in get_db().threads.find(
        {"authorId": user_id, "isAnonymous": False}
    ).sort("createdAt", -1).limit(50):
        threads.append(serialize_thread(t))

    # My posts (non-anonymous, non-deleted)
    posts = []
    async for p in get_db().posts.find(
        {"authorId": user_id, "isAnonymous": False, "deleted": False}
    ).sort("createdAt", -1).limit(50):
        posts.append(serialize_post(p))

    # Total likes and dislikes across all threads and posts
    total_likes = sum(len(t["likes"]) for t in threads) + sum(len(p["likes"]) for p in posts)
    total_dislikes = sum(len(t["dislikes"]) for t in threads) + sum(len(p["dislikes"]) for p in posts)

    return {
        "threads": threads,
        "posts": posts,
        "total_likes": total_likes,
        "total_dislikes": total_dislikes,
    }





# --- Media Upload ---

UPLOAD_DIR = "/app/uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB hard limit
ALLOWED_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "video/mp4", "video/webm",
}
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit),
):
    """Upload an image or video. Max 10 MB. Returns a URL to embed in posts."""
    # 1. Check content type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type '{file.content_type}' not allowed. Use JPEG, PNG, GIF, WebP, MP4, or WebM.",
        )

    # 2. Read with size cap — protects against huge file uploads
    chunk_size = 1024 * 64  # 64 KB chunks
    total = 0
    chunks = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large. Maximum size is 10 MB.",
            )
        chunks.append(chunk)

    # 3. Save with a unique name to prevent collisions and path traversal
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as f:
        for chunk in chunks:
            f.write(chunk)

    return {"url": f"/media/{safe_name}", "filename": safe_name}


@router.get("/media/{filename}")
async def serve_media(filename: str):
    """Serve an uploaded media file."""
    # Prevent path traversal attacks
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(path)







@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user: dict = Depends(get_ws_user)
):
    """Establishes a persistent WebSocket connection for real-time notifications."""
    # user["id"] is now securely verified via the token dependency
    await manager.connect(websocket, user["id"])
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user["id"])