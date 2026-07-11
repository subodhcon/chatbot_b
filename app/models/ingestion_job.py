import uuid
import datetime
from enum import Enum as PyEnum

class IngestionJobStatus(str, PyEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class IngestionJob:
    """
    IngestionJob wrapper representing a Celery parsing lifecycle in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.source_id = uuid.UUID(doc["source_id"]) if isinstance(doc["source_id"], str) else doc["source_id"]
        self.status = IngestionJobStatus(doc.get("status", "queued"))
        self.progress = doc.get("progress", 0)
        self.error_message = doc.get("error_message")
        self.started_at = doc.get("started_at")
        self.completed_at = doc.get("completed_at")
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
        self.updated_at = doc.get("updated_at") or datetime.datetime.utcnow()
