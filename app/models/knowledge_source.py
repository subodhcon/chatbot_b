import uuid
import datetime
from enum import Enum as PyEnum

class KnowledgeSourceType(str, PyEnum):
    pdf = "pdf"
    docx = "docx"
    url = "url"

class KnowledgeSourceStatus(str, PyEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class KnowledgeSource:
    """
    KnowledgeSource wrapper representing a knowledge base item in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.bot_id = uuid.UUID(doc["bot_id"]) if isinstance(doc["bot_id"], str) else doc["bot_id"]
        self.source_type = KnowledgeSourceType(doc.get("source_type")) if doc.get("source_type") else None
        self.source_name = doc.get("source_name")
        self.file_path = doc.get("file_path")
        self.url = doc.get("url")
        self.file_size = doc.get("file_size")
        self.status = KnowledgeSourceStatus(doc.get("status", "queued"))
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
        self.updated_at = doc.get("updated_at") or datetime.datetime.utcnow()
