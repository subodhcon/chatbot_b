import uuid
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.ingestion_job import IngestionJob, IngestionJobStatus


class IngestionJobRepository(BaseRepository[IngestionJob]):
    """
    Repository layer for managing IngestionJob records.
    """

    def __init__(self) -> None:
        super().__init__(IngestionJob)

    async def get_job(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
    ) -> Optional[IngestionJob]:
        """
        Retrieve a single ingestion job by its ID.
        """
        return await self.get_async(db, job_id)

    async def get_job_by_source(
        self,
        db: AsyncSession,
        source_id: uuid.UUID,
    ) -> Optional[IngestionJob]:
        """
        Retrieve the most recent ingestion job for a given KnowledgeSource.
        Returns the latest job (ordered by started_at/created descending).
        """
        result = await db.execute(
            select(IngestionJob)
            .where(IngestionJob.source_id == source_id)
            .order_by(IngestionJob.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_jobs_by_source(
        self,
        db: AsyncSession,
        source_id: uuid.UUID,
    ) -> List[IngestionJob]:
        """
        Retrieve all ingestion jobs for a given KnowledgeSource.
        """
        result = await db.execute(
            select(IngestionJob)
            .where(IngestionJob.source_id == source_id)
            .order_by(IngestionJob.id.desc())
        )
        return list(result.scalars().all())

    async def get_jobs_by_status(
        self,
        db: AsyncSession,
        status: IngestionJobStatus,
        *,
        limit: int = 50,
    ) -> List[IngestionJob]:
        """
        Retrieve all ingestion jobs with a given status.
        Useful for monitoring queued or processing jobs.
        """
        result = await db.execute(
            select(IngestionJob)
            .where(IngestionJob.status == status)
            .limit(limit)
        )
        return list(result.scalars().all())


# Module-level singleton
ingestion_job_repository = IngestionJobRepository()
