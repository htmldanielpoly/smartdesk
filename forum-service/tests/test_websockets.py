"""Regression test for ConnectionManager.broadcast()'s list-mutation race.

broadcast() (forum-service/app/websockets.py) does:

    for user_id, connections in list(self.active_connections.items()):
        for connection in connections:
            await connection.send_text(payload)
            ...

`list(...)` only copies the outer dict's (key, value) pairs — `connections`
is still the SAME list object as self.active_connections[user_id]. If a
concurrent disconnect() for that user fires while a `send_text` await is in
flight (a real scenario: one tab's send is slow/blocked while another of the
user's tabs closes), it mutates that live list mid-iteration.

This is deterministic, not a timing gamble: Python's list iterator holds a
plain integer index and never re-reads positions it has already passed. If
the *currently-being-sent-to* connection removes itself from the list during
its own send_text() call, everything after it shifts down by one slot — the
element that lands in the just-vacated "next" slot is the one the iterator
was going to fetch next, but the element that was originally in that "next"
slot is skipped entirely, because the iterator's index has already moved
past it. No sleep(), no thread timing, no flakiness: the disconnect always
happens at the exact same point in ws1's send_text, every run.
"""
from app.websockets import ConnectionManager


class _FakeConnection:
    """Stands in for a starlette WebSocket: records what it was sent, and
    can run an arbitrary hook mid-send to simulate a concurrent disconnect."""

    def __init__(self, name, on_send=None):
        self.name = name
        self.sent = []
        self._on_send = on_send

    async def send_text(self, payload):
        if self._on_send:
            await self._on_send()
        self.sent.append(payload)


async def test_broadcast_skips_a_connection_when_another_disconnects_mid_send():
    manager = ConnectionManager()
    user_id = "race-user"

    ws1 = _FakeConnection("ws1")
    ws2 = _FakeConnection("ws2")
    ws3 = _FakeConnection("ws3")
    manager.active_connections[user_id] = [ws1, ws2, ws3]

    # While ws1 is mid-send, ws1 itself disconnects (e.g. that tab's socket
    # errors out and the exception handler calls disconnect concurrently) —
    # removing the CURRENT list element during iteration.
    async def _disconnect_ws1_mid_send():
        manager.disconnect(ws1, user_id)
    ws1._on_send = _disconnect_ws1_mid_send

    await manager.broadcast({"type": "x"})

    # ws1 was mid-send when it disconnected, so it still received this
    # broadcast (the send already started) — that part is fine either way.
    assert ws1.sent == ['{"type": "x"}']

    # ws3 shifted into the list slot the iterator was about to fetch next,
    # and got delivered to correctly.
    assert ws3.sent == ['{"type": "x"}']

    # ws2 — sitting between ws1 and ws3 — is exactly what got shifted out of
    # reach by the removal, and never received the broadcast at all, despite
    # never having disconnected. This is the bug: a fully live connection
    # silently missed a message because of an unrelated connection's timing.
    assert ws2.sent == ['{"type": "x"}'], (
        "ws2 never received the broadcast — it was silently skipped because "
        "broadcast() iterates the live connections list while disconnect() "
        "mutates that same list out from under it"
    )
