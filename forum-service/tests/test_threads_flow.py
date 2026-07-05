"""Thread lifecycle: create, list, reply, paginate, moderate."""
from tests.conftest import auth_header


def _create_thread(client, headers, slug="technical", title="Wifi drops", body="Every hour."):
    return client.post(
        f"/boards/{slug}/threads", json={"title": title, "body": body}, headers=headers
    )


def test_create_thread_appears_in_board_listing(client):
    headers = auth_header("user-1")
    r = _create_thread(client, headers)
    assert r.status_code == 201
    thread = r.json()
    assert thread["board_slug"] == "technical"
    assert thread["post_count"] == 1
    assert thread["locked"] is False and thread["pinned"] is False

    listing = client.get("/boards/technical/threads", headers=headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == thread["id"]

    # The thread's body became its first post.
    detail = client.get(f"/threads/{thread['id']}", headers=headers).json()
    assert len(detail["posts"]) == 1
    assert detail["posts"][0]["body"] == "Every hour."

    # Board thread_count reflects the new thread.
    boards = client.get("/boards", headers=headers).json()
    technical = next(b for b in boards if b["slug"] == "technical")
    assert technical["thread_count"] == 1


def test_reply_bumps_post_count_and_last_post_at(client):
    headers = auth_header("user-1")
    thread = _create_thread(client, headers).json()

    r = client.post(
        f"/threads/{thread['id']}/posts", json={"body": "Same here."}, headers=auth_header("user-2")
    )
    assert r.status_code == 201

    detail = client.get(f"/threads/{thread['id']}", headers=headers).json()
    assert detail["thread"]["post_count"] == 2
    assert len(detail["posts"]) == 2
    assert detail["posts"][-1]["body"] == "Same here."  # oldest first
    assert detail["thread"]["last_post_at"] >= detail["thread"]["created_at"]


def test_board_listing_pagination(client):
    headers = auth_header("user-1")
    for i in range(25):
        r = _create_thread(client, headers, slug="general", title=f"Thread {i}")
        assert r.status_code == 201

    page1 = client.get("/boards/general/threads?page=1", headers=headers).json()
    assert page1["total"] == 25
    assert page1["page_size"] == 20
    assert len(page1["items"]) == 20
    # Newest activity first.
    assert page1["items"][0]["title"] == "Thread 24"

    page2 = client.get("/boards/general/threads?page=2", headers=headers).json()
    assert len(page2["items"]) == 5
    ids = {t["id"] for t in page1["items"]} | {t["id"] for t in page2["items"]}
    assert len(ids) == 25


def test_unknown_board_404(client):
    headers = auth_header("user-1")
    assert client.get("/boards/nope/threads", headers=headers).status_code == 404
    assert _create_thread(client, headers, slug="nope").status_code == 404


def test_locked_thread_rejects_replies(client):
    user = auth_header("user-1")
    thread = _create_thread(client, user).json()

    r = client.patch(
        f"/threads/{thread['id']}", json={"locked": True}, headers=auth_header("agent-1", "AGENT")
    )
    assert r.status_code == 200
    assert r.json()["locked"] is True

    reply = client.post(f"/threads/{thread['id']}/posts", json={"body": "Late."}, headers=user)
    assert reply.status_code == 409


def test_only_staff_can_lock(client):
    user = auth_header("user-1")
    thread = _create_thread(client, user).json()

    r = client.patch(f"/threads/{thread['id']}", json={"locked": True}, headers=user)
    assert r.status_code == 403

    r = client.patch(
        f"/threads/{thread['id']}", json={"locked": True}, headers=auth_header("admin-1", "ADMIN")
    )
    assert r.status_code == 200


def test_pinned_threads_listed_first(client):
    headers = auth_header("user-1")
    old = _create_thread(client, headers, slug="billing", title="Old but pinned").json()
    _create_thread(client, headers, slug="billing", title="Newer thread")

    r = client.patch(
        f"/threads/{old['id']}", json={"pinned": True}, headers=auth_header("agent-1", "AGENT")
    )
    assert r.status_code == 200
    assert r.json()["pinned"] is True

    listing = client.get("/boards/billing/threads", headers=headers).json()
    assert [t["title"] for t in listing["items"]] == ["Old but pinned", "Newer thread"]
