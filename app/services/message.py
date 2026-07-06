import uuid
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories import message_repository
from app.models.conversation import Message

logger = logging.getLogger("app.services.message")


class MessageService:
    """
    Orchestrates business logic for saving and retrieving conversation messages.
    """

    async def save_user_message(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        content: str,
    ) -> Message:
        """
        Saves a message sent by the user.
        """
        logger.info(f"Saving user message for conversation: {conversation_id}")
        msg = await message_repository.create_message(
            db,
            conversation_id=conversation_id,
            sender="user",
            content=content,
        )
        
        # Track analytics event
        from app.services.analytics_tracking import analytics_tracking_service
        from app.services.conversation import conversation_service
        try:
            conv = await conversation_service.get_conversation(db, conversation_id=conversation_id)
            if conv:
                await analytics_tracking_service.track_message_sent(
                    db,
                    bot_id=conv.bot_id,
                    conversation_id=conversation_id,
                    sender="user",
                    message_length=len(content),
                )
        except Exception as e:
            logger.error(f"Failed to track user message sent: {e}", exc_info=True)
            
        return msg

    async def save_assistant_message(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        content: str,
    ) -> Message:
        """
        Saves a message sent by the assistant (bot).
        """
        logger.info(f"Saving assistant/bot message for conversation: {conversation_id}")
        msg = await message_repository.create_message(
            db,
            conversation_id=conversation_id,
            sender="bot",
            content=content,
        )
        
        # Track analytics event
        from app.services.analytics_tracking import analytics_tracking_service
        from app.services.conversation import conversation_service
        try:
            conv = await conversation_service.get_conversation(db, conversation_id=conversation_id)
            if conv:
                await analytics_tracking_service.track_bot_response(
                    db,
                    bot_id=conv.bot_id,
                    conversation_id=conversation_id,
                    response_length=len(content),
                )
        except Exception as e:
            logger.error(f"Failed to track assistant response: {e}", exc_info=True)
            
        return msg

    async def fetch_conversation_history(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Message]:
        """
        Retrieves all messages in a conversation in chronological order.
        """
        logger.info(f"Fetching history for conversation: {conversation_id}")
        return await message_repository.get_messages(
            db,
            conversation_id=conversation_id,
            skip=skip,
            limit=limit,
        )

    async def fetch_recent_messages(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        limit: int = 10,
    ) -> List[Message]:
        """
        Retrieves the most recent messages in a conversation in chronological order.
        """
        logger.info(f"Fetching recent messages for conversation: {conversation_id}")
        return await message_repository.get_recent_messages(
            db,
            conversation_id=conversation_id,
            limit=limit,
        )


message_service = MessageService()
