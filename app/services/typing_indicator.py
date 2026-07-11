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

    async def _get_collection(self):
        from app.core.config import settings
        from app.core.mongo import mongo_registry
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
            logger.warning("TypingIndicator: MongoDB unavailable — skipping set_typing.")
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
            return {"is_typing": False, "started_at": None}

        doc = await coll.find_one({"_id": conversation_id})
        if not doc:
            return {"is_typing": False, "started_at": None}

        # Check if still within TTL (double safety check)
        now = datetime.now(timezone.utc)
        expires_at = doc.get("expires_at")
        if expires_at and now > expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at:
            # Stale — clean up
            await coll.delete_many({"_id": conversation_id})
            return {"is_typing": False, "started_at": None}

        started_at = doc.get("started_at")
        return {
            "is_typing": doc.get("is_typing", False),
            "started_at": started_at.isoformat() if started_at else None,
        }


typing_indicator_service = TypingIndicatorService()
