import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from sqlalchemy import ForeignKey, DateTime, func, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base_class import Base, UUIDPrimaryKeyMixin


class FeedbackRatingValue(str, PyEnum):
    thumbs_up = "thumbs_up"
    thumbs_down = "thumbs_down"


class FeedbackRating(Base, UUIDPrimaryKeyMixin):
    """
    FeedbackRating stores thumbs up/down user feedback on messages.
    """
    __tablename__ = "feedback_ratings"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Conversation session this feedback is associated with",
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Specific message inside the conversation that this feedback is for",
    )

    rating: Mapped[FeedbackRatingValue] = mapped_column(
        Enum(
            FeedbackRatingValue,
            name="feedback_rating_value",
            create_type=True,
        ),
        nullable=False,
        index=True,
        comment="Rating value: thumbs_up or thumbs_down",
    )

    feedback_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional detailed text feedback explaining the rating",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="Timestamp when feedback was submitted",
    )
