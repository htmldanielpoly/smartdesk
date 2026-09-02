"""Board and cold-start seeding for the forum service."""
from datetime import UTC, datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

BOARDS = [
    {"slug": "account",   "name": "Account & Sign-in",      "category": "Account"},
    {"slug": "billing",   "name": "Billing & Payments",      "category": "Billing"},
    {"slug": "technical", "name": "Technical Issues",        "category": "Technical"},
    {"slug": "network",   "name": "Network & Connectivity",  "category": "Network"},
    {"slug": "hardware",  "name": "Hardware & Devices",      "category": "Hardware"},
    {"slug": "general",   "name": "General Support",         "category": "Other"},
]

# Fake community members — stable IDs so re-runs stay idempotent
_ALICE   = "aaaaaaaaaaaaaaaaaaaaaaaa"
_BOB     = "bbbbbbbbbbbbbbbbbbbbbbbb"
_CAROL   = "cccccccccccccccccccccccc"

SEED_THREADS = [
    {
        "board": "technical",
        "title": "App crashes on startup after latest update",
        "body": "Since the update this morning the desktop app won't open. I just see a white screen and then it closes. Anyone else?",
        "author": _ALICE,
        "role": "USER",
        "replies": [
            ("Same here on Windows 11. Tried reinstalling but no luck.", _BOB,   "USER"),
            ("Workaround: delete %AppData%\\SmartDesk\\cache and restart.", _CAROL, "USER"),
        ],
    },
    {
        "board": "network",
        "title": "VPN disconnects every 30 minutes",
        "body": "Our office VPN drops exactly every half hour. Started happening after the router firmware update last week.",
        "author": _BOB,
        "role": "USER",
        "replies": [
            ("Check the idle-timeout setting in your router admin panel — default is 1800 s.", _CAROL, "USER"),
        ],
    },
    {
        "board": "billing",
        "title": "Double charged for last month",
        "body": "My credit card was charged twice on the 1st. Invoice number INV-20240901. Please advise.",
        "author": _CAROL,
        "role": "USER",
        "replies": [
            ("I had the same issue in July — support refunded within 3 days once I emailed billing@smartdesk.com.", _ALICE, "USER"),
        ],
    },
    {
        "board": "account",
        "title": "Cannot reset my password — email never arrives",
        "body": "I click 'forgot password' but the reset email never shows up, not even in spam.",
        "author": _BOB,
        "role": "USER",
        "replies": [
            ("Check that your email isn't on the suppression list. happened to me too.", _ALICE, "USER"),
        ],
    },
    {
        "board": "hardware",
        "title": "USB-C dock not detected on MacBook",
        "body": "My CalDigit dock stopped being recognised after macOS Sonoma update. Monitors and ethernet all dead.",
        "author": _ALICE,
        "role": "USER",
        "replies": [
            ("SMC reset fixed it for me: shut down, hold Shift+Control+Option+Power for 10s.", _BOB, "USER"),
            ("Also try a different USB-C port — Sonoma has a known bug with the left-side ports.", _CAROL, "USER"),
        ],
    },
    {
        "board": "general",
        "title": "How do I export my data?",
        "body": "Is there a way to download all my tickets and messages as a CSV or PDF?",
        "author": _CAROL,
        "role": "USER",
        "replies": [
            ("Settings → Account → Export Data. Takes a few minutes then emails you a link.", _ALICE, "USER"),
        ],
    },
]


async def seed_boards(db: AsyncIOMotorDatabase) -> None:
    """Idempotent: upsert boards, then seed cold-start threads/posts once."""
    # 1. Upsert boards
    for index, board in enumerate(BOARDS):
        await db.boards.update_one(
            {"slug": board["slug"]},
            {"$set": {"name": board["name"],
                      "category": board["category"],
                      "order": index}},
            upsert=True,
        )

    # 2. Seed threads — skip entirely if any thread already exists
    if await db.threads.count_documents({}) > 0:
        return

    now = datetime.now(UTC)

    for i, seed in enumerate(SEED_THREADS):
        # Stagger timestamps so the board looks naturally active
        from datetime import timedelta
        created = now - timedelta(days=len(SEED_THREADS) - i, hours=i * 3)

        thread_id = ObjectId()
        thread_doc = {
            "_id": thread_id,
            "boardSlug": seed["board"],
            "title": seed["title"],
            "authorId": seed["author"],
            "authorRole": seed["role"],
            "isAnonymous": False,
            "mediaUrls": [],
            "createdAt": created,
            "lastPostAt": created,
            "postCount": 1 + len(seed["replies"]),
            "locked": False,
            "pinned": False,
            "likes": [],
            "dislikes": [],
        }
        await db.threads.insert_one(thread_doc)

        # Opening post
        await db.posts.insert_one({
            "threadId": thread_id,
            "authorId": seed["author"],
            "authorRole": seed["role"],
            "isAnonymous": False,
            "mediaUrls": [],
            "body": seed["body"],
            "deleted": False,
            "createdAt": created,
            "likes": [],
            "dislikes": [],
        })

        # Reply posts
        for j, (body, author, role) in enumerate(seed["replies"]):
            reply_time = created + timedelta(hours=j + 1)
            await db.posts.insert_one({
                "threadId": thread_id,
                "authorId": author,
                "authorRole": role,
                "isAnonymous": False,
                "mediaUrls": [],
                "body": body,
                "deleted": False,
                "createdAt": reply_time,
                "likes": [],
                "dislikes": [],
            })