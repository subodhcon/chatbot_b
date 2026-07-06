import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.feedback_rating import FeedbackRating, FeedbackRatingValue

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

        # Construct time filters based on feedback submission date
        time_filters = []
        if start_date:
            time_filters.append(FeedbackRating.created_at >= start_date)
        if end_date:
            time_filters.append(FeedbackRating.created_at <= end_date)

        # 1. Count positive ratings (thumbs_up)
        thumbs_up_query = (
            select(func.count(FeedbackRating.id))
            .join(Conversation, FeedbackRating.conversation_id == Conversation.id)
            .where(
                Conversation.bot_id == bot_id,
                FeedbackRating.rating == FeedbackRatingValue.thumbs_up,
                *time_filters
            )
        )
        thumbs_up_res = await db.execute(thumbs_up_query)
        positive_count = thumbs_up_res.scalar_one() or 0

        # 2. Count negative ratings (thumbs_down)
        thumbs_down_query = (
            select(func.count(FeedbackRating.id))
            .join(Conversation, FeedbackRating.conversation_id == Conversation.id)
            .where(
                Conversation.bot_id == bot_id,
                FeedbackRating.rating == FeedbackRatingValue.thumbs_down,
                *time_filters
            )
        )
        thumbs_down_res = await db.execute(thumbs_down_query)
        negative_count = thumbs_down_res.scalar_one() or 0

        total_ratings = positive_count + negative_count
        if total_ratings == 0:
            return 0.0

        csat_percentage = (positive_count / total_ratings) * 100
        return round(csat_percentage, 2)


# Module-level singleton
csat_calculation_service = CSATCalculationService()
