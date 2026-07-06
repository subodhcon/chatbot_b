import os
import csv
import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
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

        # 1. Query messages, conversation parent data, and optional feedback ratings
        query = (
            select(
                Message.conversation_id,
                Message.created_at,
                Message.sender,
                Message.content,
                FeedbackRating.rating,
            )
            .join(Conversation, Message.conversation_id == Conversation.id)
            .outerjoin(FeedbackRating, Message.id == FeedbackRating.message_id)
            .where(
                Conversation.bot_id == bot_id,
                Conversation.created_at >= start_date,
                Conversation.created_at <= end_date,
            )
            .order_by(Conversation.created_at.asc(), Message.created_at.asc())
        )

        result = await db.execute(query)
        rows = result.all()

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
