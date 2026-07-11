import uuid
from datetime import datetime
from app.repositories.mongo_base import MongoBaseRepository
from app.models.export_job import ExportJob, ExportJobStatus


class ExportJobRepository(MongoBaseRepository):
    """
    Repository layer for managing data export jobs in MongoDB.
    """

    def __init__(self) -> None:
        super().__init__("export_jobs", ExportJob)

    async def create_job(
        self,
        db,
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
            "status": ExportJobStatus.pending.value if hasattr(ExportJobStatus.pending, "value") else ExportJobStatus.pending,
        }
        return await self.create_async(db, obj_in=obj_in)


# Module-level singleton
export_job_repository = ExportJobRepository()
