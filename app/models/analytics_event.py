import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from sqlalchemy import ForeignKey, DateTime, func, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base_class import Base, UUIDPrimaryKeyMixin


class AnalyticsEventType(str, PyEnum):
    conversation_started = "conversation_started"
    message_sent = "message_sent"
    bot_response = "bot_response"
    feedback_submitted = "feedback_submitted"


class AnalyticsEvent(Base, UUIDPrimaryKeyMixin):
    """
    AnalyticsEvent tracks visitor interaction logs (e.g. session start, messages, session close)
    for dashboard analysis.
    """
    __tablename__ = "analytics_events"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Bot this tracking event belongs to",
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Conversation session this event is associated with",
    )

    event_type: Mapped[AnalyticsEventType] = mapped_column(
        Enum(
            AnalyticsEventType,
            name="analytics_event_type",
            create_type=True,
        ),
        nullable=False,
        index=True,
        comment="Type of event: conversation_started, message_sent, bot_response, feedback_submitted"
    )

    # We name the Python property metadata_ to avoid conflict with SQLAlchemy Base.metadata.
    # The database column itself is named "metadata".
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Arbitrary event payload / metadata",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="Timestamp of when the event occurred",
    )

