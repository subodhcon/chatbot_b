import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Conversation model representing a single chat session between a user and a bot.
    """
    __tablename__ = "conversations"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_identifier: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Anonymous User",
        comment="Human readable unique placeholder identifier, e.g. User #8294",
    )

    browser_info: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Metadata about the visitor browser, OS, and viewport sizes",
    )

    # Relationships
    bot: Mapped["Bot"] = relationship(
        "Bot",
        lazy="select",
    )

    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="select",
    )


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Message model representing an individual chat bubble inside a Conversation.
    """
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sender: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Sender identity: 'user' or 'bot'",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Text content of the message",
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
        lazy="select",
    )


# Composite index on Conversations: (bot_id, created_at DESC)
Index(
    "ix_conversations_bot_id_created_at",
    Conversation.bot_id,
    Conversation.created_at.desc(),
)

# Composite index on Messages: (conversation_id, created_at ASC)
Index(
    "ix_messages_conversation_id_created_at",
    Message.conversation_id,
    Message.created_at.asc(),
)
