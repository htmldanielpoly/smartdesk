from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import settings
from app.database import get_db
from app.deps import Role, get_current_user, require_roles
from app.schemas import (
    BoardOut,
    PostCreate,
    PostOut,
    ThreadCreate,
    ThreadDetail,
    ThreadModerate,
    ThreadOut,
    ThreadPage,
)
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


def _is_staff(user: dict) -> bool:
    return user["role"] in (Role.AGENT.value, Role.ADMIN.value)


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
):
    """Any authenticated user opens a thread; its body becomes the first post."""
    board = await _get_board_or_404(slug)

    now = datetime.now(UTC)
    thread_doc = {
        "boardSlug": board["slug"],
        "title": payload.title,
        "authorId": user["id"],
        "authorRole": user["role"],
        "createdAt": now,
        "lastPostAt": now,
        "postCount": 1,
        "locked": False,
        "pinned": False,
    }
    result = await get_db().threads.insert_one(thread_doc)
    thread_doc["_id"] = result.inserted_id

    await get_db().posts.insert_one(
        {
            "threadId": result.inserted_id,
            "authorId": user["id"],
            "authorRole": user["role"],
            "body": payload.body,
            "deleted": False,
            "createdAt": now,
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
):
    thread = await _get_thread_or_404(thread_id)
    if thread.get("locked", False):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Thread is locked")

    now = datetime.now(UTC)
    doc = {
        "threadId": thread["_id"],
        "authorId": user["id"],
        "authorRole": user["role"],
        "body": payload.body,
        "deleted": False,
        "createdAt": now,
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
