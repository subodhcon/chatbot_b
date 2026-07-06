import uuid
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.ingestion_job import ingestion_job_repository
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.knowledge_source import KnowledgeSource

logger = logging.getLogger("app.services.ingestion")


class IngestionService:
    """
    Service layer for ingestion job status queries.
    Provides business logic around ingestion job progress, status, and errors.
    """

    async def get_job_status(
        self,
        db: AsyncSession,
        *,
        job_id: uuid.UUID,
    ) -> Optional[IngestionJob]:
        """
        Retrieve a single ingestion job by its ID.
        Raises ValueError if the job does not exist.
        """
        job = await ingestion_job_repository.get_job(db, job_id)
        if not job:
            raise ValueError(f"Ingestion job not found: {job_id}")
        return job

    async def get_source_ingestion_status(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
    ) -> Optional[IngestionJob]:
        """
        Retrieve the latest ingestion job for a specific knowledge source.
        Raises ValueError if no job exists for that source.
        """
        job = await ingestion_job_repository.get_job_by_source(db, source_id)
        if not job:
            raise ValueError(f"No ingestion job found for source: {source_id}")
        return job

    async def get_source_ingestion_history(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
    ) -> List[IngestionJob]:
        """
        Retrieve all ingestion jobs for a specific knowledge source,
        ordered newest first. Returns empty list if no jobs exist.
        """
        return await ingestion_job_repository.get_jobs_by_source(db, source_id)

    async def get_knowledge_source_with_status(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
        bot_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """
        Retrieve a KnowledgeSource and its latest ingestion job status.
        Validates that the source belongs to the specified bot.
        Returns a combined dict with source + job data.
        Raises ValueError if source not found or doesn't belong to bot.
        """
        # Fetch source
        result = await db.execute(
            select(KnowledgeSource).where(KnowledgeSource.id == source_id)
        )
        source = result.scalars().first()

        if not source:
            raise ValueError(f"Knowledge source not found: {source_id}")

        if source.bot_id != bot_id:
            raise ValueError(f"Knowledge source does not belong to this bot.")

        # Fetch latest job
        job = await ingestion_job_repository.get_job_by_source(db, source_id)

        return {
            "source": source,
            "job": job,
        }

    async def list_queued_jobs(
        self,
        db: AsyncSession,
        *,
        limit: int = 50,
    ) -> List[IngestionJob]:
        """
        Retrieve all queued ingestion jobs, useful for monitoring.
        """
        return await ingestion_job_repository.get_jobs_by_status(
            db, IngestionJobStatus.queued, limit=limit
        )


# Module-level singleton
ingestion_service = IngestionService()
