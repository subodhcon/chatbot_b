"""
Typing Indicator Service
========================
Manages ephemeral "bot is typing…" state in MongoDB `typing_events` collection.

Documents are upserted with an `expires_at` field.
A MongoDB TTL index on `expires_at` (expireAfterSeconds: 0) auto-removes stale docs.

Expected index:
    db.typing_events.createIndex({ "expires_at": 1 }, { expireAfterSeconds: 0 })
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("app.services.typing_indicator")

TYPING_TTL_SECONDS = 30   # Bot typing state auto-expires after 30 s if not cleared


class TypingIndicatorService:
    """
    Manages ephemeral typing state for public widget conversations.
    """
    def __init__(self):
        self._local_states = {}

    async def _get_collection(self):
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        if not settings.MONGODB_URL or "localhost" in settings.MONGODB_URL:
            # Skip localhost to prevent timeout and run in in-memory mode
            return None
        client = mongo_registry.get_client("typing_indicator", settings.MONGODB_URL)
        if client is None:
            return None
        return client["chatbot"]["typing_events"]

    async def set_typing(self, conversation_id: str, bot_id: str) -> None:
        """
        Upsert a typing document — marks bot as currently generating a response.
        """
        coll = await self._get_collection()
        if coll is None:
            # Fallback to in-memory storage
            now = datetime.now(timezone.utc)
            self._local_states[conversation_id] = {
                "bot_id": bot_id,
                "is_typing": True,
                "expires_at": now + timedelta(seconds=TYPING_TTL_SECONDS)
            }
            logger.info("TypingIndicator: set is_typing=True (In-Memory mode)")
            return


        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=TYPING_TTL_SECONDS)

        await coll.update_one(
            {"_id": conversation_id},
            {"$set": {
                "_id": conversation_id,
                "bot_id": bot_id,
                "is_typing": True,
                "started_at": now,
                "expires_at": expires_at,
            }},
            upsert=True,
        )
        logger.debug(f"TypingIndicator: set is_typing=True for conv={conversation_id}")

    async def clear_typing(self, conversation_id: str) -> None:
        """
        Remove the typing document — marks bot as done responding.
        """
        coll = await self._get_collection()
        if coll is None:
            # Fallback to in-memory storage
            self._local_states.pop(conversation_id, None)
            logger.info("TypingIndicator: cleared typing (In-Memory mode)")
            return

        await coll.delete_many({"_id": conversation_id})
        logger.debug(f"TypingIndicator: cleared typing for conv={conversation_id}")

    async def get_status(self, conversation_id: str) -> dict:
        """
        Return current typing status for a conversation.
        Returns: {"is_typing": bool, "started_at": str | None}
        """
        coll = await self._get_collection()
        if coll is None:
            # Fallback to in-memory check
            state = self._local_states.get(conversation_id)
            if not state:
                return {"is_typing": False, "started_at": None}
            now = datetime.now(timezone.utc)
            if now > state["expires_at"]:
                self._local_states.pop(conversation_id, None)
                return {"is_typing": False, "started_at": None}
            return {"is_typing": True, "started_at": None}


        started_at = doc.get("started_at")
        return {
            "is_typing": doc.get("is_typing", False),
            "started_at": started_at.isoformat() if started_at else None,
        }


typing_indicator_service = TypingIndicatorService()
