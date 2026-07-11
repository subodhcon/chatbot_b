import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import String, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.bot_version import BotVersion
    from app.models.bot_config import BotConfig
    from app.models.bot_manager import BotManager


class Bot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Bot model representing a chatbot created by a user.
    Inherits UUID v4 primary key and audit timestamps.
    """

    __tablename__ = "bots"

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        index=True,
        nullable=False,
    )

    avatar_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean(),
        default=True,
        nullable=False,
    )

    # Foreign key — references the user who created this bot
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationship — back-reference on User.bots
    creator: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        back_populates="bots",
        lazy="select",
    )

    # Relationship — all versions (snapshots) of this bot
    versions: Mapped[List["BotVersion"]] = relationship(  # type: ignore[name-defined]
        "BotVersion",
        back_populates="bot",
        cascade="all, delete-orphan",
        order_by="BotVersion.version_number",
        lazy="select",
    )

    # Relationship — live configuration (one-to-one)
    config: Mapped[Optional["BotConfig"]] = relationship(  # type: ignore[name-defined]
        "BotConfig",
        back_populates="bot",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="select",
    )



    # Relationship — all managers associated with this bot
    managers: Mapped[List["BotManager"]] = relationship(
        "BotManager",
        back_populates="bot",
        cascade="all, delete-orphan",
        lazy="select",
    )
