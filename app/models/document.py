import uuid
import datetime

class Document:
    """
    Document wrapper representing uploaded file metadata in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.filename = doc.get("filename")
        self.file_path = doc.get("file_path")
        self.file_size = doc.get("file_size")
        self.created_by = uuid.UUID(doc["created_by"]) if isinstance(doc["created_by"], str) else doc["created_by"]
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
        self.updated_at = doc.get("updated_at") or datetime.datetime.utcnow()
