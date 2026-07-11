import uuid
import datetime
from enum import Enum as PyEnum

class UrlCrawlStatus(str, PyEnum):
    pending = "pending"
    crawling = "crawling"
    completed = "completed"
    failed = "failed"

class UrlCrawl:
    """
    UrlCrawl wrapper representing crawling metadata in MongoDB.
    """
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.bot_id = uuid.UUID(doc["bot_id"]) if isinstance(doc["bot_id"], str) else doc["bot_id"]
        self.start_url = doc.get("start_url")
        self.crawl_depth = doc.get("crawl_depth", 1)
        self.status = UrlCrawlStatus(doc.get("status", "pending"))
        self.created_at = doc.get("created_at") or datetime.datetime.utcnow()
