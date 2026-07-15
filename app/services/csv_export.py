import os
import csv
import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.feedback_rating import FeedbackRating
from app.models.bot_config import BotConfig
from app.core.config import settings
from app.services.pii_masking import pii_masking_service

logger = logging.getLogger("app.services.csv_export")


class CSVExportService:
    """
    Service layer responsible for generating UTF-8 compliant CSV exports
    of bot conversation records, messages, and associated feedback ratings.
    """

    async def generate_export(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        start_date: datetime,
        end_date: datetime,
        export_dir: str = "uploads/exports",
    ) -> str:
        """
        Queries and compiles conversations, messages, and ratings into a UTF-8 CSV file.
        Returns:
            str: Absolute or relative file path to the generated CSV.
        """
        logger.info(f"Generating CSV export for bot {bot_id} (Range: {start_date} to {end_date})")

        # Fetch bot config
        config_query = select(BotConfig).where(BotConfig.bot_id == bot_id)
        config_res = await db.execute(config_query)
        bot_config = config_res.scalars().first()
        gdpr_enabled = bot_config.gdpr_enabled if bot_config else False

        # 1. Query conversations within range from MongoDB
        from app.core.config import settings
        from app.core.mongo import mongo_registry

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
            raise RuntimeError("Failed to establish MongoDB client connection.")

        conv_coll = mongo_client[db_name]["conversations"]
        rating_coll = mongo_client[db_name]["feedback_ratings"]

        conv_filter = {
            "bot_id": str(bot_id),
            "created_at": {"$gte": start_date, "$lte": end_date}
        }
        logger.info(f"MongoDB collection query filter: {conv_filter} on {db_name}")
        cursor = conv_coll.find(conv_filter, {"_id": 1})
        conv_ids = [doc["_id"] async for doc in cursor]
        logger.info(f"MongoDB query matched conv_ids: {conv_ids}")

        # Query feedback ratings for these conversations from MongoDB
        feedback_map = {}
        if conv_ids:
            rating_cursor = rating_coll.find({
                "conversation_id": {"$in": conv_ids}
            }, {"message_id": 1, "rating": 1})
            async for r_doc in rating_cursor:
                msg_id = r_doc.get("message_id")
                rating = r_doc.get("rating")
                if msg_id:
                    feedback_map[str(msg_id)] = rating

        # Fetch messages from MongoDB
        mongo_messages = []
        if conv_ids:
            messages_coll = mongo_client[db_name]["messages"]
            cursor = messages_coll.find({
                "conversation_id": {"$in": conv_ids}
            }).sort([("conversation_id", 1), ("created_at", 1)])
            async for doc in cursor:
                mongo_messages.append(doc)

        rows = []
        for doc in mongo_messages:
            msg_id = doc["_id"]
            conv_id = doc["conversation_id"]
            created_at = doc["created_at"]
            sender = doc["sender"]
            content = doc["content"]
            rating = feedback_map.get(str(msg_id))
            rows.append((conv_id, created_at, sender, content, rating))

        # 2. Setup export target directory
        os.makedirs(export_dir, exist_ok=True)
        file_name = f"export_{bot_id}_{uuid.uuid4().hex[:8]}.csv"
        file_path = os.path.join(export_dir, file_name)

        # 3. Write UTF-8-BOM encoded CSV
        # utf-8-sig ensures Excel automatically identifies the encoding correctly
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            
            # Header Columns
            writer.writerow(["conversation_id", "timestamp", "role", "message", "rating"])
            
            # Data Rows
            for row in rows:
                content = row[3]
                if gdpr_enabled:
                    content = pii_masking_service.mask_text(content)
                writer.writerow([
                    str(row[0]),
                    row[1].isoformat() if hasattr(row[1], 'isoformat') else str(row[1]),
                    row[2],
                    content,
                    str(row[4]) if row[4] else "",
                ])


        logger.info(f"Export CSV generated successfully at {file_path}. Exchanged records: {len(rows)}")
        return file_path


# Module-level singleton
csv_export_service = CSVExportService()
