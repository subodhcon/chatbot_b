import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("app.core.websocket")


class ConnectionManager:
    """
    Manages active WebSocket connections.
    Supports targeting connections by a unique session/conversation identifier.
    """

    def __init__(self) -> None:
        # Maps a conversation/session ID (str) to a set of active WebSockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """
        Accepts the WebSocket connection and tracks it.
        """
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = set()
        self.active_connections[client_id].add(websocket)
        logger.info(
            f"WebSocket connected for client_id {client_id}. "
            f"Active connections for client: {len(self.active_connections[client_id])}"
        )

    def disconnect(self, websocket: WebSocket, client_id: str) -> None:
        """
        Removes a disconnected WebSocket from the tracked connections.
        """
        if client_id in self.active_connections:
            self.active_connections[client_id].discard(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
        logger.info(f"WebSocket disconnected for client_id {client_id}.")

    async def send_personal_message(self, message: str, websocket: WebSocket) -> None:
        """
        Send a text message directly to a single WebSocket client.
        """
        await websocket.send_text(message)

    async def send_json(self, data: dict, websocket: WebSocket) -> None:
        """
        Send a JSON payload directly to a single WebSocket client.
        """
        await websocket.send_json(data)

    async def broadcast_to_session(self, client_id: str, message: str) -> None:
        """
        Broadcast a text message to all WebSockets associated with a client_id/session.
        """
        if client_id in self.active_connections:
            for connection in list(self.active_connections[client_id]):
                try:
                    await connection.send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting text to connection: {e}")
                    self.active_connections[client_id].discard(connection)

    async def broadcast_json_to_session(self, client_id: str, data: dict) -> None:
        """
        Broadcast a JSON payload to all WebSockets associated with a client_id/session.
        """
        if client_id in self.active_connections:
            for connection in list(self.active_connections[client_id]):
                try:
                    await connection.send_json(data)
                except Exception as e:
                    logger.error(f"Error broadcasting JSON to connection: {e}")
                    # Clean up broken connections dynamically
                    self.active_connections[client_id].discard(connection)


# Global WebSocket connection manager instance
manager = ConnectionManager()
