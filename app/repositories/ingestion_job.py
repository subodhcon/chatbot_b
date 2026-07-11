import uuid
from typing import Optional, List
from app.repositories.mongo_base import MongoBaseRepository
from app.models.ingestion_job import IngestionJob, IngestionJobStatus


class IngestionJobRepository(MongoBaseRepository):
    """
    Repository layer for managing IngestionJob records in MongoDB.
    """

    def __init__(self) -> None:
        super().__init__("ingestion_jobs", IngestionJob)

    async def get_job(
        self,
        db,
        job_id: uuid.UUID,
    ) -> Optional[IngestionJob]:
        """
        Retrieve a single ingestion job by its ID.
        """
        return await self.get_async(db, job_id)

    async def get_job_by_source(
        self,
        db,
        source_id: uuid.UUID,
    ) -> Optional[IngestionJob]:
        """
        Retrieve the most recent ingestion job for a given KnowledgeSource.
        """
        coll = await self.get_collection()
        # Find the latest document sorted by created_at descending
        doc = await coll.find_one(
            {"source_id": str(source_id)},
            sort=[("created_at", -1)]
        )
        return IngestionJob(doc) if doc else None

    async def get_jobs_by_source(
        self,
        db,
        source_id: uuid.UUID,
    ) -> List[IngestionJob]:
        """
        Retrieve all ingestion jobs for a given KnowledgeSource.
        """
        coll = await self.get_collection()
        cursor = coll.find({"source_id": str(source_id)}).sort([("created_at", -1)])
        results = []
        async for doc in cursor:
            results.append(IngestionJob(doc))
        return results

    async def get_jobs_by_status(
        self,
        db,
        status: IngestionJobStatus,
        *,
        limit: int = 50,
    ) -> List[IngestionJob]:
        """
        Retrieve all ingestion jobs with a given status.
        """
        coll = await self.get_collection()
        status_val = status.value if hasattr(status, "value") else status
        cursor = coll.find({"status": status_val}).limit(limit)
        results = []
        async for doc in cursor:
            results.append(IngestionJob(doc))
        return results


# Module-level singleton
ingestion_job_repository = IngestionJobRepository()
