import logging
from typing import Dict, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.security import decrypt_string

logger = logging.getLogger(__name__)

class MongoConnectionRegistry:
    """
    A registry cache to manage dynamic connection pools to various MongoDB Atlas clusters.
    Avoids reconnecting on every request.
    """
    def __init__(self):
        self._clients: Dict[str, AsyncIOMotorClient] = {}

    def get_client(self, bot_id: str, encrypted_uri: str) -> Optional[AsyncIOMotorClient]:
        """
        Get or create a MongoClient instance for a specific bot.
        """
        if bot_id in self._clients:
            return self._clients[bot_id]

        try:
            # Check if URI is plaintext or encrypted
            if encrypted_uri.startswith("mongodb://") or encrypted_uri.startswith("mongodb+srv://"):
                connection_string = encrypted_uri
            else:
                connection_string = decrypt_string(encrypted_uri)
                if not connection_string:
                    logger.error(f"Failed to decrypt MongoDB URI for bot {bot_id}")
                    return None

            # Initialize Client
            client = AsyncIOMotorClient(
                connection_string,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )
            self._clients[bot_id] = client
            logger.info(f"Initialized new MongoDB client connection for bot {bot_id}")
            return client
        except Exception as e:
            logger.error(f"Error establishing MongoDB connection for bot {bot_id}: {str(e)}")
            return None

    def close_client(self, bot_id: str):
        """
        Close and remove a client connection from cache.
        """
        client = self._clients.pop(bot_id, None)
        if client:
            client.close()
            logger.info(f"Closed MongoDB client connection for bot {bot_id}")

    def clear(self):
        """
        Close all active connections.
        """
        for bot_id in list(self._clients.keys()):
            self.close_client(bot_id)

# Global registry instance
mongo_registry = MongoConnectionRegistry()
