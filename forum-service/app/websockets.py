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
        """Sends a JSON message to all active connections for a specific user."""
        if user_id in self.active_connections:
            payload = json.dumps(message)
            for connection in self.active_connections[user_id]:
                await connection.send_text(payload)

# Instantiate a singleton manager to be imported across the app
manager = ConnectionManager()