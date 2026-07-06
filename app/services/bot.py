import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.bot import Bot
from app.models.bot_config import BotConfig
from app.models.bot_version import BotVersion
from app.repositories.bot import bot_repository
from app.repositories.bot_config import bot_config_repository
from app.repositories.bot_version import bot_version_repository

logger = logging.getLogger("app.services.bot")

# Business rules
MAX_BOTS_PER_ADMIN = 10


def _generate_slug(name: str) -> str:
    """
    Derive a URL-safe slug from a bot name.

    Steps:
      1. Lowercase the name.
      2. Replace any run of non-alphanumeric characters with a single hyphen.
      3. Strip leading/trailing hyphens.
      4. Append a short random hex suffix to avoid collisions.

    Example: "My Support Bot!" -> "my-support-bot-a3f1"
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    suffix = uuid.uuid4().hex[:6]
    return f"{base}-{suffix}"


class BotService:
    """
    BotService orchestrates all bot lifecycle operations.

    Responsibilities:
      - Enforce business rules (bot cap, required fields, uniqueness).
      - Auto-generate slugs from bot names.
      - Delegate persistence to BotRepository and BotConfigRepository.
      - Create a default BotConfig row whenever a new Bot is created.

    Does NOT know about HTTP — raise ValueError / PermissionError for
    business violations; let the router/API layer translate to HTTP codes.
    """

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_bot(
        self,
        db: AsyncSession,
        *,
        name: str,
        created_by: uuid.UUID,
        avatar_url: Optional[str] = None,
        is_active: bool = True,
    ) -> Bot:
        """
        Create a new Bot owned by `created_by`, then create its default config.

        Business rules enforced:
          - `name` must be non-empty.
          - The owning user may not exceed MAX_BOTS_PER_ADMIN active bots.

        Returns the newly created Bot instance (config is committed separately
        but within the same request session).
        """
        # Rule 1: name is required
        name = name.strip()
        if not name:
            raise ValueError("Bot name is required.")

        # Rule 2: max bots per admin
        existing_bots = await bot_repository.get_all_bots(
            db, created_by=created_by
        )
        if len(existing_bots) >= MAX_BOTS_PER_ADMIN:
            logger.warning(
                f"Bot limit reached for user {created_by}: "
                f"{len(existing_bots)}/{MAX_BOTS_PER_ADMIN}"
            )
            raise PermissionError(
                f"Maximum bot limit reached. "
                f"You may not create more than {MAX_BOTS_PER_ADMIN} bots."
            )

        # Auto-generate a unique slug
        slug = _generate_slug(name)

        bot_in: Dict[str, Any] = {
            "name": name,
            "slug": slug,
            "created_by": created_by,
            "is_active": is_active,
        }
        if avatar_url is not None:
            bot_in["avatar_url"] = avatar_url

        logger.info(f"Creating bot '{name}' (slug={slug}) for user {created_by}")
        bot = await bot_repository.create_bot(db, obj_in=bot_in)

        # Create default configuration immediately after the bot row exists
        await bot_config_repository.create_config(
            db, obj_in={"bot_id": bot.id}
        )
        logger.info(f"Default config created for bot {bot.id}")

        return bot

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_bot(
        self, db: AsyncSession, bot_id: uuid.UUID
    ) -> Bot:
        """
        Fetch a Bot by its UUID. Raises ValueError if not found.
        """
        bot = await bot_repository.get_bot(db, bot_id)
        if bot is None:
            raise ValueError(f"Bot with id '{bot_id}' does not exist.")
        return bot

    async def get_bot_by_slug(
        self, db: AsyncSession, slug: str
    ) -> Bot:
        """
        Fetch a Bot by its slug. Raises ValueError if not found.
        """
        bot = await bot_repository.get_bot_by_slug(db, slug)
        if bot is None:
            raise ValueError(f"Bot with slug '{slug}' does not exist.")
        return bot

    async def get_all_bots(
        self,
        db: AsyncSession,
        *,
        created_by: Optional[uuid.UUID] = None,
        active_only: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Bot]:
        """
        Return a paginated list of Bots with optional owner and status filters.
        """
        return await bot_repository.get_all_bots(
            db,
            created_by=created_by,
            active_only=active_only,
            skip=skip,
            limit=limit,
        )

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
        Return a list of bots assigned to a specific user manager.
        """
        return await bot_repository.get_managed_bots(
            db,
            user_id=user_id,
            skip=skip,
            limit=limit,
            active_only=active_only,
        )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_bot(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        obj_in: Union[Dict[str, Any], Any],
    ) -> Bot:
        """
        Apply a partial update to a Bot.

        If `name` is being changed, a new slug is auto-generated to stay
        in sync with the display name.

        Raises ValueError if the bot does not exist or if the new name
        is explicitly set to an empty string.
        """
        bot = await self.get_bot(db, bot_id)

        # Normalise input to dict for inspection
        if isinstance(obj_in, dict):
            update_data: Dict[str, Any] = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        # Validate and regenerate slug when name changes
        if "name" in update_data:
            new_name = update_data["name"].strip()
            if not new_name:
                raise ValueError("Bot name cannot be empty.")
            update_data["name"] = new_name
            update_data["slug"] = _generate_slug(new_name)
            logger.info(
                f"Bot {bot_id} renamed to '{new_name}', new slug: {update_data['slug']}"
            )

        return await bot_repository.update_bot(db, db_obj=bot, obj_in=update_data)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_bot(
        self, db: AsyncSession, *, bot_id: uuid.UUID
    ) -> Bot:
        """
        Hard-delete a Bot by UUID.

        The DB-level CASCADE removes the associated bot_configs and
        bot_versions rows automatically.

        Raises ValueError if the bot does not exist.
        """
        # Verify existence before attempting delete
        await self.get_bot(db, bot_id)

        deleted = await bot_repository.delete_bot(db, bot_id=bot_id)
        logger.info(f"Bot {bot_id} deleted.")
        return deleted  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    async def get_config(
        self, db: AsyncSession, bot_id: uuid.UUID
    ) -> BotConfig:
        """
        Fetch the live configuration for a bot.

        Raises ValueError if the bot or its config does not exist.
        Use this when the config is expected to be present (i.e. after
        create_bot has run).
        """
        # Confirm the bot itself exists first for a clear error message
        await self.get_bot(db, bot_id)

        config = await bot_config_repository.get_config(db, bot_id)
        if config is None:
            raise ValueError(f"No configuration found for bot '{bot_id}'.")
        return config

    async def update_config(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        obj_in: Union[Dict[str, Any], Any],
    ) -> BotConfig:
        """
        Update the live configuration for a bot.

        Raises ValueError if the bot or its config does not exist.
        """
        config = await self.get_config(db, bot_id)
        updated = await bot_config_repository.update_config(
            db, db_obj=config, obj_in=obj_in
        )
        logger.info(f"Config updated for bot {bot_id}")
        return updated

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    async def get_version_history(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 30,
    ) -> List[BotVersion]:
        """
        Return paginated version snapshots for a bot, newest first.

        Default limit is 30 to match the API specification. Callers can
        override both skip and limit for custom pagination windows.

        Raises ValueError if the bot does not exist.
        """
        await self.get_bot(db, bot_id)  # existence check
        return await bot_version_repository.get_versions_for_bot(
            db,
            bot_id,
            skip=skip,
            limit=limit,
        )

    async def restore_version(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> tuple[BotConfig, BotVersion]:
        """
        Restore the live bot configuration from a historical version snapshot.

        History is append-only — this operation NEVER modifies or deletes
        any existing BotVersion row. Instead it:

          1. Fetches the target historical BotVersion.
          2. Validates it belongs to the correct bot.
          3. Applies the snapshot fields to the live BotConfig.
          4. Creates a brand-new BotVersion with the same snapshot data
             plus a `restored_from_version` field for audit traceability.

        Returns (updated_config, new_version).

        Raises:
          ValueError  — if the bot, config, or target version does not exist.
          PermissionError — if the version belongs to a different bot.
        """
        # 1. Verify bot + config exist
        await self.get_bot(db, bot_id)
        config = await self.get_config(db, bot_id)

        # 2. Fetch the target version
        target_version = await bot_version_repository.get_version(db, version_id)
        if target_version is None:
            raise ValueError(f"Version '{version_id}' does not exist.")

        # 3. Ensure the version belongs to this bot
        if target_version.bot_id != bot_id:
            raise PermissionError(
                f"Version '{version_id}' does not belong to bot '{bot_id}'."
            )

        # 4. Extract config fields from the snapshot
        snap: Dict[str, Any] = target_version.snapshot_json

        # Map snapshot keys → BotConfig column names (snapshot uses same names)
        restorable_fields = {
            "welcome_message", "fallback_message", "tone", "system_prompt",
            "model_name", "temperature", "max_tokens", "top_k",
            "similarity_threshold", "is_streaming", "extra_config",
            "gdpr_enabled",
        }
        restore_data = {k: v for k, v in snap.items() if k in restorable_fields}

        # 5. Apply to live config
        updated_config = await bot_config_repository.update_config(
            db, db_obj=config, obj_in=restore_data
        )
        logger.info(
            f"Config for bot {bot_id} restored from version "
            f"v{target_version.version_number} ({version_id})"
        )

        # 6. Create a NEW version entry (history stays intact)
        new_snapshot: Dict[str, Any] = {
            **restore_data,
            # Audit field — records where this restore came from
            "restored_from_version": target_version.version_number,
            "restored_from_version_id": str(version_id),
        }
        new_version = await bot_version_repository.create_version(
            db,
            bot_id=bot_id,
            snapshot_json=new_snapshot,
        )
        logger.info(
            f"Restore snapshot written as v{new_version.version_number} "
            f"for bot {bot_id}"
        )

        return updated_config, new_version

    async def update_config_with_snapshot(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        obj_in: Union[Dict[str, Any], Any],
    ) -> tuple[BotConfig, BotVersion]:
        """
        Update the live config AND immediately create an immutable version snapshot.

        Operation order:
          1. Apply the config changes.
          2. Serialize the full updated config to a JSONB snapshot dict.
          3. Write a new BotVersion row (auto-incremented version_number).

        Returns (updated_config, new_version) so callers can return both
        objects in the API response if desired.

        Raises ValueError if the bot or its config does not exist.
        """
        # 1. Apply config changes
        updated_config = await self.update_config(db, bot_id=bot_id, obj_in=obj_in)

        # 2. Build snapshot dict from the updated config row
        snapshot: Dict[str, Any] = {
            "welcome_message": updated_config.welcome_message,
            "fallback_message": updated_config.fallback_message,
            "tone": updated_config.tone,
            "system_prompt": updated_config.system_prompt,
            "model_name": updated_config.model_name,
            "temperature": updated_config.temperature,
            "max_tokens": updated_config.max_tokens,
            "top_k": updated_config.top_k,
            "similarity_threshold": updated_config.similarity_threshold,
            "is_streaming": updated_config.is_streaming,
            "extra_config": updated_config.extra_config,
            "gdpr_enabled": updated_config.gdpr_enabled,
        }

        # 3. Persist the version snapshot
        version = await bot_version_repository.create_version(
            db,
            bot_id=bot_id,
            snapshot_json=snapshot,
        )
        logger.info(
            f"Version snapshot v{version.version_number} created for bot {bot_id}"
        )

        return updated_config, version


# ---------------------------------------------------------------------------
# Module-level singleton — import this in routers / endpoints
# ---------------------------------------------------------------------------
bot_service = BotService()
