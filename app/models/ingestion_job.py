import uuid
from enum import Enum as PyEnum
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Integer, ForeignKey, Enum, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge_source import KnowledgeSource


class IngestionJobStatus(str, PyEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class IngestionJob(Base, UUIDPrimaryKeyMixin):
    """
    IngestionJob tracks the background parsing/indexing lifecycle of KnowledgeSources.
    """
    __tablename__ = "ingestion_jobs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Knowledge source this ingestion job processes",
    )

    status: Mapped[IngestionJobStatus] = mapped_column(
        Enum(
            IngestionJobStatus,
            name="ingestion_job_status",
            create_type=True,
        ),
        nullable=False,
        default=IngestionJobStatus.queued,
        server_default=IngestionJobStatus.queued.value,
        index=True,
        comment="Current status of the ingestion execution",
    )

    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Percentage progress of the ingestion execution (0-100)",
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Detailed error message if the job failed",
    )

    started_at: Mapped[Optional[DateTime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of when processing started",
    )

    completed_at: Mapped[Optional[DateTime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of when processing completed or failed",
    )

    # Relationships
    knowledge_source: Mapped[Optional["KnowledgeSource"]] = relationship(
        "KnowledgeSource",
        lazy="select",
    )
