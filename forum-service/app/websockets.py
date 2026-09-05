import json
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Maps user_id to a list of active WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accepts a connection and registers the user."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        """Removes a connection when a client disconnects."""
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            # Clean up the key if the user has no more active tabs
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]


    async def send_personal_message(self, message: dict, user_id: str):
        """Sends a JSON message to all active connections for a specific user.

        NOTE: Single-process only. Redis Pub/Sub is the upgrade path
        for multi-worker deployments where sockets are held per-worker.
        """
        if user_id in self.active_connections:
            payload = json.dumps(message, default=str)
            dead: list[WebSocket] = []
            # Iterate a copy: a concurrent connect()/disconnect() for this
            # same user (e.g. another tab) could otherwise mutate this list
            # mid-iteration and silently skip a still-live connection.
            for connection in list(self.active_connections[user_id]):
                try:
                    await connection.send_text(payload)
                except Exception:
                    dead.append(connection)
            for connection in dead:
                self.disconnect(connection, user_id)

    async def broadcast(self, message: dict):
        """Sends a JSON message to every currently connected client, across all users.

        NOTE: Single-process only, same caveat as send_personal_message.
        """
        payload = json.dumps(message, default=str)
        for user_id, connections in list(self.active_connections.items()):
            dead: list[WebSocket] = []
            # Iterate a copy of this user's connection list, not the live
            # reference — see the same note in send_personal_message().
            for connection in list(connections):
                try:
                    await connection.send_text(payload)
                except Exception:
                    dead.append(connection)
            for connection in dead:
                self.disconnect(connection, user_id)



# Instantiate a singleton manager to be imported across the app
manager = ConnectionManager()