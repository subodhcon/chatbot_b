from __future__ import annotations
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.bot import Bot
    from app.models.user import User

class BotManager(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "bot_managers"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    role: Mapped[str] = mapped_column(
        String(50), 
        default="editor", 
        nullable=False
    )

    # Relationships
    bot: Mapped["Bot"] = relationship(
        "Bot",
        back_populates="managers",
        lazy="select"
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="managed_bots",
        lazy="select"
    )
