"""
Rate Limiter Service
====================
Sliding-window rate limiting for public widget messages.
Stores counters in MongoDB `rate_limit_logs` collection.
Each document tracks a visitor's message count within a time window.

MongoDB TTL index (24 h) expected on `window_start` field.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

logger = logging.getLogger("app.services.rate_limiter")


class RateLimiterService:
    """
    Sliding-window rate limiter backed by MongoDB rate_limit_logs collection.
    """

    async def _get_collection(self, settings, mongo_registry):
        client = mongo_registry.get_client("rate_limiter", settings.MONGODB_URL)
        if client is None:
            return None
        return client["chatbot"]["rate_limit_logs"]

    async def check_and_record(
        self,
        conversation_id: str,
        bot_id: str,
        ip_address: str,
        visitor_identifier: str,
    ) -> Tuple[bool, int]:
        """
        Check whether a visitor is within rate limits, then increment counter.

        Returns:
            (is_allowed: bool, retry_after_seconds: int)
            retry_after_seconds is 0 when allowed.
        """
        from app.core.config import settings
        from app.core.mongo import mongo_registry

        coll = await self._get_collection(settings, mongo_registry)
        if coll is None:
            # If MongoDB unavailable, allow request (fail open)
            logger.warning("Rate limiter: MongoDB unavailable — allowing request.")
            return True, 0

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=settings.RATE_LIMIT_WINDOW_MINUTES)

        # Count messages in current window for this conversation
        count = await coll.count_documents({
            "conversation_id": conversation_id,
            "window_start": {"$gte": window_start},
        })

        if count >= settings.RATE_LIMIT_MAX_MESSAGES:
            # Calculate retry window
            retry_after = int(settings.RATE_LIMIT_WINDOW_MINUTES * 60)
            logger.warning(
                f"Rate limit exceeded: conv={conversation_id} ip={ip_address} "
                f"count={count}/{settings.RATE_LIMIT_MAX_MESSAGES}"
            )
            return False, retry_after

        # Record this message attempt
        log_doc = {
            "_id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "bot_id": bot_id,
            "ip_address": ip_address,
            "visitor_identifier": visitor_identifier,
            "window_start": now,
            "created_at": now,
        }
        try:
            await coll.insert_one(log_doc)
        except Exception as e:
            logger.error(f"Rate limiter: failed to record log: {e}")

        return True, 0

    async def get_current_count(self, conversation_id: str) -> int:
        """Return message count within the current window (for debugging/admin)."""
        from app.core.config import settings
        from app.core.mongo import mongo_registry

        coll = await self._get_collection(settings, mongo_registry)
        if coll is None:
            return 0

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=settings.RATE_LIMIT_WINDOW_MINUTES)
        return await coll.count_documents({
            "conversation_id": conversation_id,
            "window_start": {"$gte": window_start},
        })


rate_limiter_service = RateLimiterService()
