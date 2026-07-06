import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from sqlalchemy import ForeignKey, Enum, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base_class import Base, UUIDPrimaryKeyMixin


class ExportJobStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ExportJob(Base, UUIDPrimaryKeyMixin):
    """
    ExportJob represents the metadata and execution status of a bot data export job.
    """
    __tablename__ = "export_jobs"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Bot whose data is being exported",
    )

    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Filter start date of the exported records",
    )

    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Filter end date of the exported records",
    )

    status: Mapped[ExportJobStatus] = mapped_column(
        Enum(
            ExportJobStatus,
            name="export_job_status",
            create_type=True,
        ),
        nullable=False,
        default=ExportJobStatus.pending,
        server_default=ExportJobStatus.pending.value,
        index=True,
        comment="Current execution state of the export process",
    )

    file_path: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="Path to the generated export archive file",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp when the export was requested",
    )
