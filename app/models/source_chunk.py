import uuid
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Integer, ForeignKey, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.knowledge_source import KnowledgeSource


class SourceChunk(Base, UUIDPrimaryKeyMixin):
    """
    SourceChunk represents an individual text chunk derived from a KnowledgeSource.
    """
    __tablename__ = "source_chunks"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Knowledge source this chunk belongs to",
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Index of the chunk within the source",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Actual text content of the chunk",
    )

    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of tokens in the content",
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp of chunk creation",
    )

    # Relationships
    knowledge_source: Mapped[Optional["KnowledgeSource"]] = relationship(
        "KnowledgeSource",
        lazy="select",
    )
