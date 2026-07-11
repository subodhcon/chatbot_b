"""
Analytics Snapshot Service
===========================
Generates and retrieves daily aggregated performance snapshots for each bot.
Snapshots are stored in MongoDB `bot_analytics_snapshots` collection.

Expected index:
    db.bot_analytics_snapshots.createIndex(
        { "bot_id": 1, "snapshot_date": 1 }, { unique: true }
    )
"""
import uuid
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("app.services.snapshot_service")


class SnapshotService:
    """
    Generates daily/weekly aggregated analytics snapshots from live MongoDB data.
    """

    async def _get_collection(self):
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        client = mongo_registry.get_client("snapshots", settings.MONGODB_URL)
        if client is None:
            return None
        return client["chatbot"]["bot_analytics_snapshots"]

    async def _get_messages_collection(self):
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        client = mongo_registry.get_client("snapshots", settings.MONGODB_URL)
        if client is None:
            return None
        return client["chatbot"]["messages"]

    async def generate_daily_snapshot(
        self,
        bot_id: str,
        snapshot_date: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Compute and upsert a daily snapshot for the given bot.
        Defaults to yesterday's date.
        """
        from app.core.config import settings
        from app.core.mongo import mongo_registry

        if snapshot_date is None:
            snapshot_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        snapshot_date_str = snapshot_date.isoformat()
        day_start = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day,
                             tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        client = mongo_registry.get_client("snapshots", settings.MONGODB_URL)
        if client is None:
            logger.error(f"Snapshot: MongoDB unavailable for bot {bot_id}")
            return None

        db = client["chatbot"]

        # 1. Total conversations for this day
        total_conversations = await db["conversations"].count_documents({
            "bot_id": bot_id,
            "created_at": {"$gte": day_start, "$lt": day_end},
        })

        # 2. Conversation IDs for message lookups
        conv_ids = []
        cursor = db["conversations"].find(
            {"bot_id": bot_id, "created_at": {"$gte": day_start, "$lt": day_end}},
            {"_id": 1}
        )
        async for c in cursor:
            conv_ids.append(c["_id"])

        # 3. Total messages
        total_messages = 0
        avg_messages = 0.0
        if conv_ids:
            total_messages = await db["messages"].count_documents({
                "conversation_id": {"$in": conv_ids}
            })
            avg_messages = round(total_messages / len(conv_ids), 2) if conv_ids else 0.0

        # 4. Ratings
        positive_ratings = await db["feedback_ratings"].count_documents({
            "conversation_id": {"$in": conv_ids},
            "rating": "thumbs_up",
        })
        negative_ratings = await db["feedback_ratings"].count_documents({
            "conversation_id": {"$in": conv_ids},
            "rating": "thumbs_down",
        })

        # 5. CSAT score
        total_ratings = positive_ratings + negative_ratings
        csat_score = round((positive_ratings / total_ratings) * 100, 1) if total_ratings > 0 else None

        # 6. Deflection rate (conversations with zero bot fallback messages)
        fallback_conversations = 0
        deflection_rate = None
        if conv_ids:
            # Check for bot config fallback message from PostgreSQL (via app service)
            # Here we store raw count; actual rate is computed when serving
            deflection_rate = None  # Computed on read if needed

        now = datetime.now(timezone.utc)
        snapshot_doc = {
            "bot_id": bot_id,
            "snapshot_date": snapshot_date_str,
            "period": "daily",
            "metrics": {
                "total_conversations": total_conversations,
                "total_messages": total_messages,
                "avg_messages_per_conversation": avg_messages,
                "positive_ratings": positive_ratings,
                "negative_ratings": negative_ratings,
                "csat_score": csat_score,
                "deflection_rate": deflection_rate,
            },
            "updated_at": now,
        }

        coll = await self._get_collection()
        if coll is None:
            return snapshot_doc

        await coll.update_one(
            {"bot_id": bot_id, "snapshot_date": snapshot_date_str},
            {"$set": snapshot_doc, "$setOnInsert": {"_id": str(uuid.uuid4()), "created_at": now}},
            upsert=True,
        )

        logger.info(f"Snapshot generated: bot={bot_id} date={snapshot_date_str} "
                    f"convs={total_conversations} msgs={total_messages}")
        return snapshot_doc

    async def get_snapshot(
        self,
        bot_id: str,
        snapshot_date: date,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single day's snapshot."""
        coll = await self._get_collection()
        if coll is None:
            return None
        doc = await coll.find_one({
            "bot_id": bot_id,
            "snapshot_date": snapshot_date.isoformat(),
        })
        return doc

    async def get_snapshot_range(
        self,
        bot_id: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        """
        Fetch a range of daily snapshots (for chart time-series rendering).
        Returns list sorted by snapshot_date ascending.
        """
        coll = await self._get_collection()
        if coll is None:
            return []

        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        results = []
        cursor = coll.find({
            "bot_id": bot_id,
            "snapshot_date": {"$gte": start_str, "$lte": end_str},
        }).sort("snapshot_date", 1)

        async for doc in cursor:
            doc.pop("_id", None)
            results.append(doc)

        return results


snapshot_service = SnapshotService()
