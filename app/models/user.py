from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.bot import Bot
    from app.models.bot_manager import BotManager

class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    User model representing platform users, tenants, or dashboard administrators.
    Inherits UUID v4 primary keys and audit timestamps.
    """
    __tablename__ = "users"

    name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True
    )
    
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )
    
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    
    is_active: Mapped[bool] = mapped_column(
        Boolean(),
        default=True,
        nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(50),
        default="user",
        nullable=False
    )

    bots: Mapped[List[Bot]] = relationship(
        "Bot",
        back_populates="creator",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # Relationship — bots managed by this user
    managed_bots: Mapped[List["BotManager"]] = relationship(
        "BotManager",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
