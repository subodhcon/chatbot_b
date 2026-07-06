import uuid
import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories import analytics_event_repository
from app.models.analytics_event import AnalyticsEvent, AnalyticsEventType

logger = logging.getLogger("app.services.analytics_tracking")


class AnalyticsTrackingService:
    """
    Orchestrates telemetry event capturing for bot visitor conversation analytics.
    """

    async def track_conversation_started(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        conversation_id: uuid.UUID,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsEvent:
        """
        Record that a new conversation has been started.
        """
        logger.info(f"Tracking conversation started: bot {bot_id}, conv {conversation_id}")
        return await analytics_event_repository.log_event(
            db,
            bot_id=bot_id,
            conversation_id=conversation_id,
            event_type=AnalyticsEventType.conversation_started,
            metadata=metadata,
        )

    async def track_message_sent(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        conversation_id: uuid.UUID,
        sender: str,
        message_length: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsEvent:
        """
        Record that a message was sent (by a user).
        """
        logger.info(f"Tracking message sent: bot {bot_id}, conv {conversation_id}, sender {sender}")
        event_metadata = {
            "sender": sender,
            "message_length": message_length,
            **(metadata or {}),
        }
        return await analytics_event_repository.log_event(
            db,
            bot_id=bot_id,
            conversation_id=conversation_id,
            event_type=AnalyticsEventType.message_sent,
            metadata=event_metadata,
        )

    async def track_bot_response(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        conversation_id: uuid.UUID,
        response_length: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsEvent:
        """
        Record that a bot response was generated and sent.
        """
        logger.info(f"Tracking bot response: bot {bot_id}, conv {conversation_id}")
        event_metadata = {
            "response_length": response_length,
            **(metadata or {}),
        }
        return await analytics_event_repository.log_event(
            db,
            bot_id=bot_id,
            conversation_id=conversation_id,
            event_type=AnalyticsEventType.bot_response,
            metadata=event_metadata,
        )

    async def track_feedback_submitted(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        conversation_id: uuid.UUID,
        rating: int,
        feedback_text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsEvent:
        """
        Record that feedback has been submitted.
        """
        logger.info(f"Tracking feedback submitted: bot {bot_id}, conv {conversation_id}")
        event_metadata = {
            "rating": rating,
            "feedback_text": feedback_text,
            **(metadata or {}),
        }
        return await analytics_event_repository.log_event(
            db,
            bot_id=bot_id,
            conversation_id=conversation_id,
            event_type=AnalyticsEventType.feedback_submitted,
            metadata=event_metadata,
        )


# Module-level singleton
analytics_tracking_service = AnalyticsTrackingService()

