import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from sqlalchemy import Integer, ForeignKey, Enum, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base_class import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class UrlCrawlStatus(str, PyEnum):
    pending = "pending"
    crawling = "crawling"
    completed = "completed"
    failed = "failed"


class UrlCrawl(Base, UUIDPrimaryKeyMixin):
    """
    UrlCrawl represents the config and execution status of a URL crawl process.
    """
    __tablename__ = "url_crawls"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Bot associated with this crawl",
    )

    start_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Initial seed URL to start crawling from",
    )

    crawl_depth: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Max recursion depth for crawler",
    )

    status: Mapped[UrlCrawlStatus] = mapped_column(
        Enum(
            UrlCrawlStatus,
            name="url_crawl_status",
            create_type=True,
        ),
        nullable=False,
        default=UrlCrawlStatus.pending,
        server_default=UrlCrawlStatus.pending.value,
        index=True,
        comment="Current execution status of the crawl",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp when the crawl request was initiated",
    )

    # Relationships
    bot: Mapped["Bot"] = relationship(
        "Bot",
        back_populates="crawls",
        lazy="select",
    )
