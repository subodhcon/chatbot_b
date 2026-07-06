import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    """
    Standard base class for all SQLAlchemy models.
    Automatically generates tablename from subclass name.
    """
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()

class UUIDPrimaryKeyMixin:
    """
    Mixin that injects a UUID v4 primary key.
    Excellent for multi-tenant and secure SaaS systems.
    """
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )

class TimestampMixin:
    """
    Mixin that injects created_at and updated_at audit columns.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
