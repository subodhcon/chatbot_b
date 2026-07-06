import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.db.base_class import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.source_chunk import SourceChunk


class Embedding(Base, UUIDPrimaryKeyMixin):
    """
    Embedding model to store pgvector embeddings for SourceChunks.
    """
    __tablename__ = "embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Source chunk associated with this embedding",
    )

    embedding_vector: Mapped[list] = mapped_column(
        Vector(1536),
        nullable=False,
        comment="1536-dimensional embedding vector",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp of embedding creation",
    )

    # Relationships
    source_chunk: Mapped[Optional["SourceChunk"]] = relationship(
        "SourceChunk",
        lazy="select",
    )


# HNSW index for cosine distance similarity searches
Index(
    "ix_embeddings_embedding_vector",
    Embedding.embedding_vector,
    postgresql_using="hnsw",
    postgresql_ops={"embedding_vector": "vector_cosine_ops"},
)
