import uuid
from typing import Any, Dict, Optional, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.bot_config import BotConfig


class BotConfigRepository(BaseRepository[BotConfig]):
    """
    BotConfig-specific data repository layer.

    BotConfig has a strict 1-to-1 relationship with Bot.
    This repository therefore centres around bot_id rather than
    the config's own primary key — callers always look up a config
    via the owning bot, not by config UUID.
    """

    def __init__(self) -> None:
        super().__init__(BotConfig)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_config(
        self,
        db: AsyncSession,
        *,
        obj_in: Dict[str, Any],
    ) -> BotConfig:
        """
        Create a new configuration record for a Bot.

        `obj_in` must contain `bot_id`. All other fields are optional
        and will fall back to model-level defaults (model_name, temperature,
        max_tokens, top_k, similarity_threshold, is_streaming).

        Raises IntegrityError if a config for the given bot_id already exists
        (the UNIQUE constraint on bot_id prevents duplicate configs).
        """
        return await self.create_async(db, obj_in=obj_in)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_config(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> Optional[BotConfig]:
        """
        Fetch the live configuration for a given Bot UUID.
        Returns None if no config has been created for this bot yet.
        """
        result = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        return result.scalars().first()

    async def get_config_by_id(
        self,
        db: AsyncSession,
        config_id: uuid.UUID,
    ) -> Optional[BotConfig]:
        """
        Fetch a config row by its own primary key.
        Rarely needed — prefer get_config(bot_id) in most cases.
        """
        return await self.get_async(db, config_id)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_config(
        self,
        db: AsyncSession,
        *,
        db_obj: BotConfig,
        obj_in: Union[Dict[str, Any], Any],
    ) -> BotConfig:
        """
        Apply a partial update to an existing BotConfig record.

        `obj_in` can be a plain dict or a Pydantic schema that supports
        `.model_dump(exclude_unset=True)` — BaseRepository handles both.

        Typical call pattern:
            config = await bot_config_repository.get_config(db, bot_id)
            updated = await bot_config_repository.update_config(
                db, db_obj=config, obj_in={"temperature": 0.9}
            )
        """
        return await self.update_async(db, db_obj=db_obj, obj_in=obj_in)

    # ------------------------------------------------------------------
    # Convenience: get_or_create
    # ------------------------------------------------------------------

    async def get_or_create_config(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> tuple[BotConfig, bool]:
        """
        Return the existing config for `bot_id`, or create a default one.

        Returns:
            (config, created) where `created` is True when a new row was inserted.

        Useful when a service needs a guaranteed config object without
        having to check existence first.
        """
        existing = await self.get_config(db, bot_id)
        if existing is not None:
            return existing, False

        config = await self.create_config(db, obj_in={"bot_id": bot_id})
        return config, True


# ---------------------------------------------------------------------------
# Module-level singleton — import this in services / routers
# ---------------------------------------------------------------------------
bot_config_repository = BotConfigRepository()
