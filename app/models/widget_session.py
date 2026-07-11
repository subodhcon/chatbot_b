import uuid
import datetime
from enum import Enum as PyEnum

class WidgetSessionStatus(str, PyEnum):
    active = "active"
    closed = "closed"

class WidgetSession:
    """
    WidgetSession wrapper representing a visitor widget session in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.bot_id = uuid.UUID(doc["bot_id"]) if isinstance(doc["bot_id"], str) else doc["bot_id"]
        self.visitor_session_id = doc.get("visitor_session_id")
        self.status = WidgetSessionStatus(doc.get("status", "active"))
        self.started_at = doc.get("started_at") or datetime.datetime.utcnow()
        self.updated_at = doc.get("updated_at") or datetime.datetime.utcnow()
