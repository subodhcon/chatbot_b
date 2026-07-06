import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.export_job import ExportJob, ExportJobStatus


class ExportJobRepository(BaseRepository[ExportJob]):
    """
    Repository layer for managing data export jobs.
    """

    def __init__(self) -> None:
        super().__init__(ExportJob)

    async def create_job(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> ExportJob:
        """
        Creates a new export job record.
        """
        obj_in = {
            "bot_id": bot_id,
            "start_date": start_date,
            "end_date": end_date,
            "status": ExportJobStatus.pending,
        }
        return await self.create_async(db, obj_in=obj_in)


# Module-level singleton
export_job_repository = ExportJobRepository()
