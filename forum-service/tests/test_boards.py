"""Board seeding and listing."""
from app.seed import BOARDS, seed_boards
from tests.conftest import auth_header

EXPECTED_SLUGS = {"account", "billing", "technical", "network", "hardware", "general"}


def test_boards_seeded_and_listed(client):
    r = client.get("/boards", headers=auth_header("user-1"))
    assert r.status_code == 200
    boards = r.json()
    assert len(boards) == len(BOARDS) == 6
    assert {b["slug"] for b in boards} == EXPECTED_SLUGS
    # Each board starts with exactly one demo thread from seed_boards().
    assert all(b["thread_count"] == 1 for b in boards)

    general = next(b for b in boards if b["slug"] == "general")
    assert general["name"] == "General Support"
    assert general["category"] == "Other"


async def test_seeding_is_idempotent(db):
    await seed_boards(db)  # fixture already seeded once; run again
    assert await db.boards.count_documents({}) == 6


def test_boards_require_auth(client):
    r = client.get("/boards")
    assert r.status_code in (401, 403)
