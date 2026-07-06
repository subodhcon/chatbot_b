import uuid
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Text, Boolean, Float, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class BotConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Live configuration record for a Bot — one row per bot (1-to-1).

    Stores the active operational settings that control how the bot
    behaves at runtime. When a new version is published these values
    are snapshotted into BotVersion.snapshot_json for history.
    """

    __tablename__ = "bot_configs"

    # ------------------------------------------------------------------
    # Relationship back to Bot
    # ------------------------------------------------------------------

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        unique=True,           # enforces the 1-to-1 at the DB level
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Identity & persona
    # ------------------------------------------------------------------

    system_prompt: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="System-level prompt that shapes the bot's persona and behaviour",
    )

    welcome_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="First message shown to users when a conversation starts",
    )

    # ------------------------------------------------------------------
    # LLM settings
    # ------------------------------------------------------------------

    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="gpt-4o-mini",
        comment="LLM model identifier, e.g. gpt-4o-mini, claude-3-haiku",
    )

    temperature: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.7,
        comment="Sampling temperature (0.0 = deterministic, 2.0 = creative)",
    )

    max_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1024,
        comment="Maximum tokens the LLM is allowed to generate per response",
    )

    # ------------------------------------------------------------------
    # Retrieval / knowledge-base settings
    # ------------------------------------------------------------------

    top_k: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        comment="Number of knowledge-base chunks retrieved per query",
    )

    similarity_threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.75,
        comment="Minimum cosine similarity score for a chunk to be used",
    )

    # ------------------------------------------------------------------
    # Behaviour flags
    # ------------------------------------------------------------------

    is_streaming: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Stream token-by-token responses to the client",
    )

    fallback_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Message shown when the bot cannot answer a query",
    )

    tone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="professional",
        comment="Conversational tone: professional, friendly, casual, formal",
    )

    gdpr_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether GDPR PII masking is enabled for exports",
    )


    # ------------------------------------------------------------------
    # Arbitrary extension bag — add new settings without migrations
    # ------------------------------------------------------------------

    extra_config: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Freeform JSONB bag for future settings not yet modelled as columns",
    )

    # ------------------------------------------------------------------
    # Relationship
    # ------------------------------------------------------------------

    bot: Mapped["Bot"] = relationship(
        "Bot",
        back_populates="config",
        lazy="select",
    )
