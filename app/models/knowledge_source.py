import uuid
from enum import Enum as PyEnum
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class KnowledgeSourceType(str, PyEnum):
    pdf = "pdf"
    docx = "docx"
    url = "url"


class KnowledgeSourceStatus(str, PyEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class KnowledgeSource(Base, UUIDPrimaryKeyMixin):
    """
    KnowledgeSource model representing knowledge base items uploaded to train the bots.
    """
    __tablename__ = "knowledge_sources"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Bot this knowledge source belongs to",
    )

    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        Enum(
            KnowledgeSourceType,
            name="knowledge_source_type",
            create_type=True,
        ),
        nullable=False,
        index=True,
        comment="Type of knowledge source: pdf, docx, or url",
    )

    source_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human readable name of the source (e.g. filename or web title)",
    )

    file_path: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="Path to file on disk (for docx, pdf)",
    )

    url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
        comment="Scraped URL (for web sources)",
    )

    file_size: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Size of source file in bytes",
    )

    status: Mapped[KnowledgeSourceStatus] = mapped_column(
        Enum(
            KnowledgeSourceStatus,
            name="knowledge_source_status",
            create_type=True,
        ),
        nullable=False,
        default=KnowledgeSourceStatus.queued,
        server_default=KnowledgeSourceStatus.queued.value,
        index=True,
        comment="Current processing status: queued, processing, completed, failed",
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp of source creation",
    )

    # Relationships
    bot: Mapped[Optional["Bot"]] = relationship(
        "Bot",
        lazy="select",
    )
