import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.conversation import Message


class MessageRepository(BaseRepository[Message]):
    """
    Repository layer for managing conversation messages (Message).
    """

    def __init__(self) -> None:
        super().__init__(Message)

    async def create_message(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        sender: str,
        content: str,
    ) -> Message:
        """
        Create a new message in a conversation.
        """
        obj_in = {
            "conversation_id": conversation_id,
            "sender": sender,
            "content": content,
        }
        return await self.create_async(db, obj_in=obj_in)

    async def get_messages(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Message]:
        """
        Retrieve all messages in a conversation in chronological order.
        """
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_messages(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        *,
        limit: int = 10,
    ) -> List[Message]:
        """
        Retrieve the most recent messages in a conversation.
        Returns the messages in chronological order.
        """
        # Fetch descending to get the newest messages up to the limit
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        # Reverse them to restore chronological order
        messages.reverse()
        return messages


# Module-level singleton
message_repository = MessageRepository()
