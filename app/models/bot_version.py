import uuid
from datetime import datetime
from sqlalchemy import Integer, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin


class BotVersion(Base, UUIDPrimaryKeyMixin):
    """
    Immutable snapshot of a Bot's configuration at a point in time.
    Each row captures the full configuration state so previous versions
    can be restored or audited without data loss.

    Intentionally excludes TimestampMixin.updated_at — versions are
    write-once and should never be mutated after creation.
    """

    __tablename__ = "bot_versions"

    __table_args__ = (
        # Ensure version numbers are unique per bot
        UniqueConstraint("bot_id", "version_number", name="uq_bot_versions_bot_id_version"),
    )

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    snapshot_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Full configuration snapshot of the bot at this version",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship — which bot this version belongs to
    bot: Mapped["Bot"] = relationship(  # type: ignore[name-defined]
        "Bot",
        back_populates="versions",
        lazy="select",
    )
