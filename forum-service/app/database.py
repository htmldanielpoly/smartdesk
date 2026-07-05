from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database handle.

    Tests can override the module-level handle via ``set_db`` to inject a
    mongomock database instead of a real connection.
    """
    if _db is None:
        raise RuntimeError("Database not initialised. Call connect() first.")
    return _db


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def connect() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(settings.mongo_uri)
    _db = _client[settings.mongo_db]
    await _ensure_indexes(_db)


async def disconnect() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.boards.create_index("slug", unique=True)
    await db.threads.create_index([("boardSlug", 1), ("lastPostAt", -1)])
    await db.posts.create_index([("threadId", 1), ("createdAt", 1)])
