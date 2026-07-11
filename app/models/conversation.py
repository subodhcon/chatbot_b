import uuid
import datetime
from typing import Optional

class Conversation:
    """
    Conversation wrapper representing a single MongoDB-backed chat session metadata.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.bot_id = uuid.UUID(doc["bot_id"]) if isinstance(doc["bot_id"], str) else doc["bot_id"]
        self.user_identifier = doc.get("user_identifier", "Anonymous User")
        self.browser_info = doc.get("browser_info")
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
        self.updated_at = doc.get("updated_at") or datetime.datetime.utcnow()
