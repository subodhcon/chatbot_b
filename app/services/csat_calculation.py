import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession



logger = logging.getLogger("app.services.csat_calculation")


class CSATCalculationService:
    """
    Service layer to calculate Customer Satisfaction (CSAT) score
    based on visitor thumbs up / thumbs down feedback.
    """

    async def calculate_csat(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Calculate CSAT percentage for a given bot, with optional date range boundaries.
        Formula: (Positive Ratings / Total Ratings) * 100
        Returns:
            float: CSAT percentage value (e.g. 85.5) or 0.0 if no ratings exist.
        """
        logger.info(f"Calculating CSAT for bot {bot_id}")

        # Get bot conversations from MongoDB
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
        rating_coll = mongo_client[db_name]["feedback_ratings"]
        
        # Fetch conversation IDs
        cursor = conv_coll.find({"bot_id": str(bot_id)}, {"_id": 1})
        conv_ids = [doc["_id"] async for doc in cursor]
        
        if not conv_ids:
            return 0.0
            
        # Build query for ratings
        query = {"conversation_id": {"$in": conv_ids}}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            query["created_at"] = date_filter
            
        # Count positive (thumbs_up)
        query["rating"] = "thumbs_up"
        positive_count = await rating_coll.count_documents(query)
        
        # Count negative (thumbs_down)
        query["rating"] = "thumbs_down"
        negative_count = await rating_coll.count_documents(query)
        
        total_ratings = positive_count + negative_count
        if total_ratings == 0:
            return 0.0
            
        csat_percentage = (positive_count / total_ratings) * 100
        return round(csat_percentage, 2)


# Module-level singleton
csat_calculation_service = CSATCalculationService()
