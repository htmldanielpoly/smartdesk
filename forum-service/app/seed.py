"""Board seeding: one fixed discussion board per support department."""
from motor.motor_asyncio import AsyncIOMotorDatabase

BOARDS = [
    {"slug": "account", "name": "Account & Sign-in", "category": "Account"},
    {"slug": "billing", "name": "Billing & Payments", "category": "Billing"},
    {"slug": "technical", "name": "Technical Issues", "category": "Technical"},
    {"slug": "network", "name": "Network & Connectivity", "category": "Network"},
    {"slug": "hardware", "name": "Hardware & Devices", "category": "Hardware"},
    {"slug": "general", "name": "General Support", "category": "Other"},
]


async def seed_boards(db: AsyncIOMotorDatabase) -> None:
    """Idempotent: upsert each fixed board by slug. Safe to run on every startup."""
    for index, board in enumerate(BOARDS):
        await db.boards.update_one(
            {"slug": board["slug"]},
            {"$set": {"name": board["name"], "category": board["category"], "order": index}},
            upsert=True,
        )
