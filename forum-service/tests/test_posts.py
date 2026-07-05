"""Post soft-deletion permissions and rendering."""
from tests.conftest import auth_header


def _make_thread_with_post(client):
    """Create a thread as user-1 and return (thread_id, first_post_id)."""
    headers = auth_header("user-1")
    thread = client.post(
        "/boards/account/threads",
        json={"title": "Locked out", "body": "Password reset loops."},
        headers=headers,
    ).json()
    detail = client.get(f"/threads/{thread['id']}", headers=headers).json()
    return thread["id"], detail["posts"][0]["id"]


def test_author_can_soft_delete_own_post(client):
    thread_id, post_id = _make_thread_with_post(client)

    r = client.delete(f"/posts/{post_id}", headers=auth_header("user-1"))
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert r.json()["body"] == "[deleted]"

    # Thread survives; the deleted post renders as "[deleted]".
    detail = client.get(f"/threads/{thread_id}", headers=auth_header("user-1"))
    assert detail.status_code == 200
    assert detail.json()["posts"][0]["body"] == "[deleted]"
    assert detail.json()["posts"][0]["deleted"] is True


def test_other_user_cannot_delete_post(client):
    _, post_id = _make_thread_with_post(client)
    r = client.delete(f"/posts/{post_id}", headers=auth_header("user-2"))
    assert r.status_code == 403


def test_agent_can_delete_any_post(client):
    _, post_id = _make_thread_with_post(client)
    r = client.delete(f"/posts/{post_id}", headers=auth_header("agent-1", "AGENT"))
    assert r.status_code == 200
    assert r.json()["body"] == "[deleted]"


def test_delete_missing_post_404(client):
    r = client.delete("/posts/64b64b64b64b64b64b64b64b", headers=auth_header("user-1"))
    assert r.status_code == 404
