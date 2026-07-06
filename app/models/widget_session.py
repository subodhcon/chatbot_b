import uuid
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, ForeignKey, Enum, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class WidgetSessionStatus(str, PyEnum):
    """
    Lifecycle states for a widget visitor session.
    - active:  session is open and the visitor may still be chatting.
    - closed:  session has ended (visitor left, timeout, or explicit close).
    """
    active = "active"
    closed = "closed"


class WidgetSession(Base, UUIDPrimaryKeyMixin):
    """
    Tracks the lifecycle of a single embeddable-widget visitor session.

    Each time a customer's website loads the widget script and a visitor
    opens a chat, one WidgetSession row is created.  It records which bot
    is being used, an opaque visitor identifier (no PII stored), the
    current status, and timestamps so analytics and cleanup jobs can
    operate on stale sessions.

    Distinct from the message-level Conversation / Message models – those
    store the actual chat transcript, whereas WidgetSession stores the
    session lifecycle and visitor metadata.
    """

    __tablename__ = "widget_sessions"

    # ── Foreign key ──────────────────────────────────────────────────────
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Bot this session belongs to",
    )

    # ── Visitor identity ─────────────────────────────────────────────────
    visitor_session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment=(
            "Opaque visitor-supplied or server-generated session token. "
            "No PII – used only to correlate multiple requests within one visit."
        ),
    )

    # ── Status ───────────────────────────────────────────────────────────
    status: Mapped[WidgetSessionStatus] = mapped_column(
        Enum(
            WidgetSessionStatus,
            name="widget_session_status",   # explicit PG enum type name
            create_type=True,
        ),
        nullable=False,
        default=WidgetSessionStatus.active,
        server_default=WidgetSessionStatus.active.value,
        index=True,
        comment="Current lifecycle state of the session",
    )

    # ── Timestamps ───────────────────────────────────────────────────────
    started_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="When the visitor first opened the widget",
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last time this session record was modified",
    )

    # ── Relationships ────────────────────────────────────────────────────
    bot: Mapped[Optional["Bot"]] = relationship(
        "Bot",
        lazy="select",
    )
