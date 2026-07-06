import uuid
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.analytics_event import AnalyticsEvent


class AnalyticsEventRepository(BaseRepository[AnalyticsEvent]):
    """
    Repository layer for logging visitor conversation telemetry events.
    """

    def __init__(self) -> None:
        super().__init__(AnalyticsEvent)

    async def log_event(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        conversation_id: uuid.UUID,
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsEvent:
        """
        Inserts a new telemetry event entry.
        """
        obj_in = {
            "bot_id": bot_id,
            "conversation_id": conversation_id,
            "event_type": event_type,
            "metadata_": metadata or {},
        }
        return await self.create_async(db, obj_in=obj_in)


# Module-level singleton
analytics_event_repository = AnalyticsEventRepository()
