import uuid
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.bot import Bot


class BotRepository(BaseRepository[Bot]):
    """
    Bot-specific data repository layer.
    Inherits generic async CRUD operations from BaseRepository.
    All methods are async-only — the project targets async SQLAlchemy.
    """

    def __init__(self) -> None:
        super().__init__(Bot)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_bot(
        self, db: AsyncSession, *, obj_in: Dict[str, Any]
    ) -> Bot:
        """
        Insert a new Bot record into the database.

        `obj_in` should contain at minimum: name, slug, created_by.
        avatar_url and is_active are optional (model defaults apply).
        """
        return await self.create_async(db, obj_in=obj_in)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Optional[Bot]:
        """
        Fetch a single Bot by its UUID primary key.
        Returns None if not found.
        """
        return await self.get_async(db, bot_id)

    async def get_bot_by_slug(self, db: AsyncSession, slug: str) -> Optional[Bot]:
        """
        Fetch a single Bot by its unique slug.
        Useful for public-facing lookups where the slug is known.
        """
        result = await db.execute(select(Bot).where(Bot.slug == slug))
        return result.scalars().first()

    async def get_all_bots(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        created_by: Optional[uuid.UUID] = None,
        active_only: bool = False,
    ) -> List[Bot]:
        """
        Fetch a paginated list of Bots with optional filters.

        Args:
            skip:       Number of rows to skip (offset).
            limit:      Maximum number of rows to return.
            created_by: When provided, restrict results to bots owned
                        by this user UUID.
            active_only: When True, only return bots where is_active=True.
        """
        query = select(Bot)

        if created_by is not None:
            query = query.where(Bot.created_by == created_by)

        if active_only:
            query = query.where(Bot.is_active.is_(True))

        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_managed_bots(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ) -> List[Bot]:
        """
        Fetch all bots assigned to a specific user manager.
        """
        from app.models.bot_manager import BotManager
        query = select(Bot).join(BotManager).where(BotManager.user_id == user_id)

        if active_only:
            query = query.where(Bot.is_active.is_(True))

        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_bot(
        self,
        db: AsyncSession,
        *,
        db_obj: Bot,
        obj_in: Union[Dict[str, Any], Any],
    ) -> Bot:
        """
        Apply a partial update to an existing Bot record.

        `obj_in` can be a plain dict or any Pydantic schema that supports
        `.model_dump(exclude_unset=True)` — BaseRepository handles both.
        """
        return await self.update_async(db, db_obj=db_obj, obj_in=obj_in)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_bot(
        self, db: AsyncSession, *, bot_id: uuid.UUID
    ) -> Optional[Bot]:
        """
        Hard-delete a Bot by UUID.
        Cascades to bot_versions via DB-level ON DELETE CASCADE.
        Returns the deleted object, or None if it did not exist.
        """
        return await self.remove_async(db, id=bot_id)


# ---------------------------------------------------------------------------
# Module-level singleton — import this in services / routers
# ---------------------------------------------------------------------------
bot_repository = BotRepository()
