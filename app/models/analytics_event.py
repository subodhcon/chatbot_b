import uuid
import datetime
from enum import Enum as PyEnum

class AnalyticsEventType(str, PyEnum):
    conversation_started = "conversation_started"
    message_sent = "message_sent"
    bot_response = "bot_response"
    feedback_submitted = "feedback_submitted"

class AnalyticsEvent:
    """
    AnalyticsEvent wrapper representing an interaction log event in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.bot_id = uuid.UUID(doc["bot_id"]) if isinstance(doc["bot_id"], str) else doc["bot_id"]
        self.conversation_id = uuid.UUID(doc["conversation_id"]) if isinstance(doc["conversation_id"], str) else doc["conversation_id"]
        self.event_type = AnalyticsEventType(doc.get("event_type")) if doc.get("event_type") else None
        self.metadata_ = doc.get("metadata", {})
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
