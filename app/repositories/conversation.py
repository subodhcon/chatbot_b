import uuid
from typing import Optional
from app.repositories.mongo_base import MongoBaseRepository
from app.models.widget_session import WidgetSession, WidgetSessionStatus


class ConversationRepository(MongoBaseRepository):
    """
    Repository layer for managing widget conversation sessions (WidgetSession) in MongoDB.
    """

    def __init__(self) -> None:
        super().__init__("widget_sessions", WidgetSession)

    async def create_conversation(
        self,
        db,
        *,
        bot_id: uuid.UUID,
        visitor_session_id: str,
        status: WidgetSessionStatus = WidgetSessionStatus.active,
    ) -> WidgetSession:
        """
        Create a new conversation session (WidgetSession) in MongoDB.
        """
        obj_in = {
            "bot_id": bot_id,
            "visitor_session_id": visitor_session_id,
            "status": status.value if hasattr(status, "value") else status,
        }
        return await self.create_async(db, obj_in=obj_in)

    async def get_conversation(
        self,
        db,
        conversation_id: uuid.UUID,
    ) -> Optional[WidgetSession]:
        """
        Retrieve a conversation session by its ID.
        """
        return await self.get_async(db, conversation_id)

    async def get_active_conversation(
        self,
        db,
        visitor_session_id: str,
    ) -> Optional[WidgetSession]:
        """
        Retrieve the active conversation session for a given visitor session ID.
        """
        coll = await self.get_collection()
        doc = await coll.find_one({
            "visitor_session_id": visitor_session_id,
            "status": WidgetSessionStatus.active.value,
        })
        return WidgetSession(doc) if doc else None

    async def close_conversation(
        self,
        db,
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
                obj_in={"status": WidgetSessionStatus.closed.value},
            )
        return conversation


# Module-level singleton
conversation_repository = ConversationRepository()
