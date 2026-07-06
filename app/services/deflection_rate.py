import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select, func, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.analytics_event import AnalyticsEvent

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

        # Construct time filters
        time_filters = []
        if start_date:
            time_filters.append(Conversation.created_at >= start_date)
        if end_date:
            time_filters.append(Conversation.created_at <= end_date)

        # 1. Total conversations count
        total_query = select(func.count(Conversation.id)).where(
            Conversation.bot_id == bot_id,
            *time_filters
        )
        total_res = await db.execute(total_query)
        total_conversations = total_res.scalar_one() or 0

        if total_conversations == 0:
            return 0.0

        # 2. Escalated conversations count
        # Extensible design: Escalation is identified by event types logging handovers
        escalated_query = (
            select(func.count(func.distinct(Conversation.id)))
            .join(AnalyticsEvent, AnalyticsEvent.conversation_id == Conversation.id)
            .where(
                Conversation.bot_id == bot_id,
                func.cast(AnalyticsEvent.event_type, String).in_([
                    "escalation_triggered",
                    "human_handover",
                    "agent_requested"
                ]),
                *time_filters
            )
        )
        escalated_res = await db.execute(escalated_query)
        escalated_conversations = escalated_res.scalar_one() or 0

        deflected_conversations = total_conversations - escalated_conversations
        deflection_rate = (deflected_conversations / total_conversations) * 100

        return round(deflection_rate, 2)


# Module-level singleton
deflection_rate_service = DeflectionRateService()
