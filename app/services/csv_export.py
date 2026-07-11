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

        # Fetch GDPR setting for this bot
        config_query = select(BotConfig.gdpr_enabled).where(BotConfig.bot_id == bot_id)
        config_res = await db.execute(config_query)
        gdpr_enabled = config_res.scalar() or False

        # 1. Query conversations within range
        conv_query = select(Conversation.id).where(
            Conversation.bot_id == bot_id,
            Conversation.created_at >= start_date,
            Conversation.created_at <= end_date,
        )
        conv_res = await db.execute(conv_query)
        conv_ids = [str(cid) for cid in conv_res.scalars().all()]

        # Query feedback ratings for these conversations
        feedback_map = {}
        if conv_ids:
            feedback_query = select(FeedbackRating.message_id, FeedbackRating.rating).where(
                FeedbackRating.conversation_id.in_([uuid.UUID(cid) for cid in conv_ids])
            )
            feedback_res = await db.execute(feedback_query)
            feedback_map = {str(r.message_id): r.rating for r in feedback_res.all()}

        # Fetch messages from MongoDB
        mongo_messages = []
        if conv_ids:
            from app.core.config import settings
            from app.core.mongo import mongo_registry
            mongo_client = mongo_registry.get_client(str(bot_id), settings.MONGODB_URL)
            if mongo_client:
                messages_coll = mongo_client["chatbot"]["messages"]
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
                content = row.content
                if gdpr_enabled:
                    content = pii_masking_service.mask_text(content)
                writer.writerow([
                    str(row.conversation_id),
                    row.created_at.isoformat(),
                    row.sender,
                    content,
                    row.rating.value if row.rating else "",
                ])


        logger.info(f"Export CSV generated successfully at {file_path}. Exchanged records: {len(rows)}")
        return file_path


# Module-level singleton
csv_export_service = CSVExportService()
