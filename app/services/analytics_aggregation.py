import uuid
import logging
from datetime import datetime, date, timedelta, time
from typing import Dict, Any, List, Optional

from app.models.conversation import Conversation
from app.models.feedback_rating import FeedbackRating, FeedbackRatingValue
from app.models.analytics_event import AnalyticsEvent, AnalyticsEventType

logger = logging.getLogger("app.services.analytics_aggregation")


class AnalyticsAggregationService:
    """
    Service layer providing unified aggregation interfaces for bot performance dashboards.
    """

    async def get_bot_summary_metrics(
        self,
        db: Any,
        bot_id: uuid.UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate total conversations, total messages, and positive/negative rating counts
        for a given bot within an optional time range.
        """
        logger.info(f"Aggregating summary metrics for bot {bot_id}")

        from app.core.config import settings
        from app.core.mongo import mongo_registry
        from app.models.bot_config import BotConfig
        from sqlalchemy import select

        # Resolve MongoDB config
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        bot_config = bot_config_res.scalars().first()
        
        mongo_uri = None
        db_name = "chatbot"
        if bot_config and bot_config.use_custom_mongo:
            mongo_uri = bot_config.mongo_uri or settings.MONGODB_URL
            db_name = bot_config.mongo_db_name or mongo_registry.get_database_name(mongo_uri)
        else:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(mongo_uri)

        mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
        if not mongo_client:
            return {
                "total_conversations": 0,
                "total_messages": 0,
                "positive_ratings": 0,
                "negative_ratings": 0,
                "total_rated": 0,
                "helpful_rate": 0.0,
            }

        conv_coll = mongo_client[db_name]["conversations"]
        rating_coll = mongo_client[db_name]["feedback_ratings"]
        messages_coll = mongo_client[db_name]["messages"]

        # Construct time filters
        query = {"bot_id": str(bot_id)}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            query["created_at"] = date_filter

        # 1. Total Conversations
        total_conversations = await conv_coll.count_documents(query)

        # 2. Total Messages
        cursor = conv_coll.find(query, {"_id": 1})
        conv_ids = [doc["_id"] async for doc in cursor]

        total_messages = 0
        if conv_ids:
            total_messages = await messages_coll.count_documents({"conversation_id": {"$in": conv_ids}})

        # 3. Thumbs Up Ratings
        positive_ratings = 0
        negative_ratings = 0
        if conv_ids:
            rating_query = {
                "conversation_id": {"$in": conv_ids},
                "rating": "thumbs_up"
            }
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter["$gte"] = start_date
                if end_date:
                    date_filter["$lte"] = end_date
                rating_query["created_at"] = date_filter
            positive_ratings = await rating_coll.count_documents(rating_query)

            # 4. Thumbs Down Ratings
            rating_query["rating"] = "thumbs_down"
            negative_ratings = await rating_coll.count_documents(rating_query)

        # Calculate helper rates
        total_rated = positive_ratings + negative_ratings
        helpful_rate = (positive_ratings / total_rated * 100) if total_rated > 0 else 0.0

        return {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "positive_ratings": positive_ratings,
            "negative_ratings": negative_ratings,
            "total_rated": total_rated,
            "helpful_rate": round(helpful_rate, 2),
        }

    async def get_conversation_volume(
        self,
        db: Any,
        bot_id: uuid.UUID,
        days_limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate conversation volume grouped by day (date-series) for the past N days.
        """
        logger.info(f"Aggregating conversation volume for bot {bot_id} (days_limit={days_limit})")

        from app.core.config import settings
        from app.core.mongo import mongo_registry
        from app.models.bot_config import BotConfig
        from sqlalchemy import select

        # Resolve MongoDB config
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        bot_config = bot_config_res.scalars().first()
        
        mongo_uri = None
        db_name = "chatbot"
        if bot_config and bot_config.use_custom_mongo:
            mongo_uri = bot_config.mongo_uri or settings.MONGODB_URL
            db_name = bot_config.mongo_db_name or mongo_registry.get_database_name(mongo_uri)
        else:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(mongo_uri)

        mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
        if not mongo_client:
            return []

        conv_coll = mongo_client[db_name]["conversations"]

        # Construct match query
        match_query = {"bot_id": str(bot_id)}
        if days_limit > 0:
            start_date = date.today() - timedelta(days=days_limit - 1)
            start_datetime = datetime.combine(start_date, time.min)
            match_query["created_at"] = {"$gte": start_datetime}

        cursor = conv_coll.find(match_query, {"created_at": 1})
        counts = {}
        async for doc in cursor:
            dt = doc.get("created_at")
            if dt:
                if isinstance(dt, datetime):
                    date_str = dt.date().isoformat()
                elif isinstance(dt, str):
                    date_str = dt.split("T")[0]
                else:
                    date_str = str(dt)
                counts[date_str] = counts.get(date_str, 0) + 1

        volume_data = [
            {"date": d, "count": counts[d]}
            for d in sorted(counts.keys())
        ]

        return volume_data


# Module-level singleton
analytics_aggregation_service = AnalyticsAggregationService()
