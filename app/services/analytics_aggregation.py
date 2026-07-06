import uuid
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from sqlalchemy import select, func, Date, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.feedback_rating import FeedbackRating, FeedbackRatingValue
from app.models.analytics_event import AnalyticsEvent, AnalyticsEventType

logger = logging.getLogger("app.services.analytics_aggregation")


class AnalyticsAggregationService:
    """
    Service layer providing unified aggregation interfaces for bot performance dashboards.
    """

    async def get_bot_summary_metrics(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate total conversations, total messages, and positive/negative rating counts
        for a given bot within an optional time range.
        """
        logger.info(f"Aggregating summary metrics for bot {bot_id}")

        # Construct time filters
        time_filters = []
        if start_date:
            time_filters.append(Conversation.created_at >= start_date)
        if end_date:
            time_filters.append(Conversation.created_at <= end_date)

        # 1. Total Conversations
        conv_query = select(func.count(Conversation.id)).where(
            Conversation.bot_id == bot_id,
            *time_filters
        )
        conv_res = await db.execute(conv_query)
        total_conversations = conv_res.scalar_one() or 0

        # 2. Total Messages
        msg_query = (
            select(func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.bot_id == bot_id,
                *time_filters
            )
        )
        msg_res = await db.execute(msg_query)
        total_messages = msg_res.scalar_one() or 0

        # 3. Thumbs Up Ratings
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
        positive_ratings = thumbs_up_res.scalar_one() or 0

        # 4. Thumbs Down Ratings
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
        negative_ratings = thumbs_down_res.scalar_one() or 0

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
        db: AsyncSession,
        bot_id: uuid.UUID,
        days_limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate conversation volume grouped by day (date-series) for the past N days.
        """
        logger.info(f"Aggregating conversation volume for bot {bot_id} (days_limit={days_limit})")

        # Select casted date and count of conversations
        date_expr = func.cast(Conversation.created_at, Date)
        query = (
            select(date_expr, func.count(Conversation.id))
            .where(Conversation.bot_id == bot_id)
        )

        if days_limit > 0:
            from datetime import timedelta, time
            start_date = date.today() - timedelta(days=days_limit - 1)
            start_datetime = datetime.combine(start_date, time.min)
            query = query.where(Conversation.created_at >= start_datetime)

        query = query.group_by(date_expr).order_by(date_expr.asc())

        res = await db.execute(query)
        rows = res.all()

        volume_data = [
            {"date": str(row[0]), "count": row[1]}
            for row in rows
        ]

        return volume_data


# Module-level singleton
analytics_aggregation_service = AnalyticsAggregationService()
