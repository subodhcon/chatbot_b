import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select, func, String
from sqlalchemy.ext.asyncio import AsyncSession



logger = logging.getLogger("app.services.deflection_rate")


class DeflectionRateService:
    """
    Service layer to calculate deflection rate of a chatbot
    (conversations resolved without human escalation).
    """

    async def calculate_deflection_rate(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Calculate the percentage of conversations deflected (resolved without escalation)
        for a given bot within an optional time range.
        Formula: ((Total Conversations - Escalated Conversations) / Total Conversations) * 100
        Returns:
            float: Deflection rate percentage (e.g. 92.4) or 0.0 if no conversations exist.
        """
        logger.info(f"Calculating deflection rate for bot {bot_id}")

        # 1. Total conversations count from MongoDB
        query = {"bot_id": str(bot_id)}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            query["created_at"] = date_filter

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
            return 0.0

        conv_coll = mongo_client[db_name]["conversations"]
        events_coll = mongo_client[db_name]["analytics_events"]

        total_conversations = await conv_coll.count_documents(query)
        if total_conversations == 0:
            return 0.0

        # Get conversation IDs
        cursor = conv_coll.find(query, {"_id": 1})
        conv_ids = [doc["_id"] async for doc in cursor]

        # 2. Escalated conversations count
        escalated_conversations = 0
        if conv_ids:
            escalation_types = ["escalation_triggered", "human_handover", "agent_requested"]
            escalated_conversations = len(await events_coll.distinct("conversation_id", {
                "conversation_id": {"$in": conv_ids},
                "event_type": {"$in": escalation_types}
            }))

        deflected_conversations = total_conversations - escalated_conversations
        deflection_rate = (deflected_conversations / total_conversations) * 100

        return round(deflection_rate, 2)


# Module-level singleton
deflection_rate_service = DeflectionRateService()
