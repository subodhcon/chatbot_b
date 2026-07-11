import uuid
from typing import Any, Dict, Optional
from app.repositories.mongo_base import MongoBaseRepository
from app.models.analytics_event import AnalyticsEvent


class AnalyticsEventRepository(MongoBaseRepository):
    """
    Repository layer for logging visitor conversation telemetry events in MongoDB.
    """

    def __init__(self) -> None:
        super().__init__("analytics_events", AnalyticsEvent)

    async def log_event(
        self,
        db,
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
            "event_type": event_type.value if hasattr(event_type, "value") else event_type,
            "metadata": metadata or {},
        }
        return await self.create_async(db, obj_in=obj_in)


# Module-level singleton
analytics_event_repository = AnalyticsEventRepository()
