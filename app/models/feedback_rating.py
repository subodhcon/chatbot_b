import uuid
import datetime
from enum import Enum as PyEnum

class FeedbackRatingValue(str, PyEnum):
    thumbs_up = "thumbs_up"
    thumbs_down = "thumbs_down"

class FeedbackRating:
    """
    FeedbackRating wrapper representing a message rating in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.conversation_id = uuid.UUID(doc["conversation_id"]) if isinstance(doc["conversation_id"], str) else doc["conversation_id"]
        self.message_id = uuid.UUID(doc["message_id"]) if isinstance(doc["message_id"], str) else doc["message_id"]
        self.rating = FeedbackRatingValue(doc.get("rating")) if doc.get("rating") else None
        self.feedback_text = doc.get("feedback_text")
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
