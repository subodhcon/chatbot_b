import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.widget_session import WidgetSession, WidgetSessionStatus


class ConversationRepository(BaseRepository[WidgetSession]):
    """
    Repository layer for managing widget conversation sessions (WidgetSession).
    """

    def __init__(self) -> None:
        super().__init__(WidgetSession)

    async def create_conversation(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        visitor_session_id: str,
        status: WidgetSessionStatus = WidgetSessionStatus.active,
    ) -> WidgetSession:
        """
        Create a new conversation session (WidgetSession).
        """
        obj_in = {
            "bot_id": bot_id,
            "visitor_session_id": visitor_session_id,
            "status": status,
        }
        return await self.create_async(db, obj_in=obj_in)

    async def get_conversation(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
    ) -> Optional[WidgetSession]:
        """
        Retrieve a conversation session by its ID.
        """
        return await self.get_async(db, conversation_id)

    async def get_active_conversation(
        self,
        db: AsyncSession,
        visitor_session_id: str,
    ) -> Optional[WidgetSession]:
        """
        Retrieve the active conversation session for a given visitor session ID.
        """
        result = await db.execute(
            select(WidgetSession).where(
                WidgetSession.visitor_session_id == visitor_session_id,
                WidgetSession.status == WidgetSessionStatus.active,
            )
        )
        return result.scalars().first()

    async def close_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
    ) -> Optional[WidgetSession]:
        """
        Close an active conversation session by setting its status to closed.
        """
        conversation = await self.get_conversation(db, conversation_id)
        if conversation:
            conversation = await self.update_async(
                db,
                db_obj=conversation,
                obj_in={"status": WidgetSessionStatus.closed},
            )
        return conversation


# Module-level singleton
conversation_repository = ConversationRepository()
