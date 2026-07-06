import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.bot_version import BotVersion


class BotVersionRepository(BaseRepository[BotVersion]):
    """
    BotVersion-specific data repository layer.
    Versions are write-once snapshots — no update or soft-delete methods.
    """

    def __init__(self) -> None:
        super().__init__(BotVersion)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_version(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        snapshot_json: Dict[str, Any],
    ) -> BotVersion:
        """
        Insert a new version snapshot for the given bot.

        The version_number is calculated automatically as
        (current max version_number for this bot) + 1, starting at 1.
        This is done inside the same async session to avoid race conditions
        in single-tenant use; for high-concurrency multi-tenant workloads a
        DB sequence or advisory lock would be preferable.
        """
        next_number = await self._next_version_number(db, bot_id)
        return await self.create_async(
            db,
            obj_in={
                "bot_id": bot_id,
                "version_number": next_number,
                "snapshot_json": snapshot_json,
            },
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_version(
        self,
        db: AsyncSession,
        version_id: uuid.UUID,
    ) -> Optional[BotVersion]:
        """Fetch a single version by its UUID."""
        return await self.get_async(db, version_id)

    async def get_versions_for_bot(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List[BotVersion]:
        """
        Return all versions for a bot ordered by version_number descending
        (newest first), with pagination support.
        """
        result = await db.execute(
            select(BotVersion)
            .where(BotVersion.bot_id == bot_id)
            .order_by(BotVersion.version_number.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest_version(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> Optional[BotVersion]:
        """Return the most recent version snapshot for the given bot."""
        result = await db.execute(
            select(BotVersion)
            .where(BotVersion.bot_id == bot_id)
            .order_by(BotVersion.version_number.desc())
            .limit(1)
        )
        return result.scalars().first()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _next_version_number(
        self, db: AsyncSession, bot_id: uuid.UUID
    ) -> int:
        """Calculate the next sequential version number for a bot."""
        result = await db.execute(
            select(func.max(BotVersion.version_number)).where(
                BotVersion.bot_id == bot_id
            )
        )
        current_max: Optional[int] = result.scalar()
        return (current_max or 0) + 1


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
bot_version_repository = BotVersionRepository()
