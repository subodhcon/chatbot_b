import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.models.knowledge_source import KnowledgeSourceType, KnowledgeSourceStatus
from app.models.ingestion_job import IngestionJobStatus

class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    source_type: KnowledgeSourceType
    source_name: str
    file_path: Optional[str] = None
    url: Optional[str] = None
    file_size: Optional[int] = None
    status: KnowledgeSourceStatus
    created_at: datetime

class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    status: IngestionJobStatus
    progress: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class KnowledgeUploadResponse(BaseModel):
    knowledge_source: KnowledgeSourceResponse
    ingestion_job: IngestionJobResponse

class IngestionStatusResponse(BaseModel):
    """Combined response for a knowledge source and its latest ingestion job."""
    knowledge_source: KnowledgeSourceResponse
    ingestion_job: Optional[IngestionJobResponse] = None

class UrlCrawlRequest(BaseModel):
    url: str = Field(..., max_length=500, description="The start URL to crawl from")
    depth: int = Field(1, ge=0, le=2, description="The crawl recursion depth (0 to 2)")

class UrlCrawlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    start_url: str
    crawl_depth: int
    status: str
    created_at: datetime

class BulkDeleteRequest(BaseModel):
    source_ids: list[uuid.UUID] = Field(..., description="List of knowledge source IDs to delete")


