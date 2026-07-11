import uuid
import datetime
from enum import Enum as PyEnum

class ExportJobStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class ExportJob:
    """
    ExportJob wrapper representing data export metadata in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.bot_id = uuid.UUID(doc["bot_id"]) if isinstance(doc["bot_id"], str) else doc["bot_id"]
        self.start_date = doc.get("start_date")
        self.end_date = doc.get("end_date")
        self.status = ExportJobStatus(doc.get("status", "pending"))
        self.file_path = doc.get("file_path")
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
