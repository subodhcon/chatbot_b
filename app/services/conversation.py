import uuid
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories import conversation_repository
from app.models.widget_session import WidgetSession

logger = logging.getLogger("app.services.conversation")


class ConversationService:
    """
    Orchestrates business logic for widget conversations (WidgetSessions).
    """

    async def create_conversation(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        visitor_session_id: str,
    ) -> WidgetSession:
        """
        Create a new conversation session.
        """
        logger.info(f"Creating new conversation for bot: {bot_id}, session: {visitor_session_id}")
        session = await conversation_repository.create_conversation(
            db,
            bot_id=bot_id,
            visitor_session_id=visitor_session_id,
        )
        
        # Track analytics event
        from app.services.analytics_tracking import analytics_tracking_service
        try:
            await analytics_tracking_service.track_conversation_started(
                db,
                bot_id=bot_id,
                conversation_id=session.id,
            )
        except Exception as e:
            logger.error(f"Failed to track conversation started: {e}", exc_info=True)
            
        return session

    async def get_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
    ) -> Optional[WidgetSession]:
        """
        Retrieve a conversation session by its ID.
        """
        logger.info(f"Fetching conversation session: {conversation_id}")
        return await conversation_repository.get_conversation(db, conversation_id)

    async def get_active_conversation(
        self,
        db: AsyncSession,
        *,
        visitor_session_id: str,
    ) -> Optional[WidgetSession]:
        """
        Get the current active conversation for a given visitor session.
        """
        logger.info(f"Fetching active conversation for session: {visitor_session_id}")
        return await conversation_repository.get_active_conversation(
            db,
            visitor_session_id=visitor_session_id,
        )

    async def close_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
    ) -> Optional[WidgetSession]:
        """
        Close a conversation session.
        """
        logger.info(f"Closing conversation session: {conversation_id}")
        session = await conversation_repository.close_conversation(
            db,
            conversation_id=conversation_id,
        )
        
        if session:
            # Track analytics event
            from app.services.analytics_tracking import analytics_tracking_service
            try:
                await analytics_tracking_service.track_conversation_ended(
                    db,
                    bot_id=session.bot_id,
                    conversation_id=session.id,
                )
            except Exception as e:
                logger.error(f"Failed to track conversation ended: {e}", exc_info=True)
                
        return session

    async def get_or_create_active_conversation(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        visitor_session_id: str,
    ) -> WidgetSession:
        """
        Retrieve the active conversation for the given visitor session.
        If no active conversation exists, create a new one.
        """
        active_conversation = await self.get_active_conversation(
            db,
            visitor_session_id=visitor_session_id,
        )
        if active_conversation is not None:
            logger.info(f"Found active conversation: {active_conversation.id}")
            return active_conversation

        logger.info(f"No active conversation found for session: {visitor_session_id}. Creating new one.")
        return await self.create_conversation(
            db,
            bot_id=bot_id,
            visitor_session_id=visitor_session_id,
        )


conversation_service = ConversationService()
