import os
import uuid
import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("app.services.source_purge")


class SourcePurgeService:
    """
    Handles the complete, explicit teardown of a KnowledgeSource and all its
    derived data:

    1.  Delete chunks from MongoDB.
    2.  KnowledgeSource DB row — ORM delete inside the same transaction.
    3.  Physical file on disk — deleted after the DB commit.
    4.  Redis cache invalidation — SCAN-based sweep for bot-level namespaces.
    """

    async def purge_source(
        self,
        db: AsyncSession,
        redis: Any,
        *,
        source_id: uuid.UUID,
        bot_id: uuid.UUID,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fully purge a KnowledgeSource by ID, including all downstream data.

        Args:
            db:          Async DB session.
            redis:       Redis client (real or MockRedisClient).
            source_id:   UUID of the KnowledgeSource to purge.
            bot_id:      UUID of the owning Bot (used for cache key namespacing).
            file_path:   Disk path to the source file (if any); deleted after DB commit.

        Returns:
            PurgeResult dict:
            {
                "source_id":        str,
                "bot_id":           str,
                "chunks_deleted":   int,
                "vectors_deleted":  int,
                "file_deleted":     bool,
                "cache_keys_cleared": int,
            }
        """
        logger.info(f"[Purge] Starting purge for source_id={source_id}, bot_id={bot_id}")

        # Check if custom MongoDB is used
        from app.models.bot_config import BotConfig
        from app.core.mongo import mongo_registry
        
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        bot_config = bot_config_res.scalars().first()
        
        if bot_config and bot_config.use_custom_mongo:
            from app.core.config import settings
            mongo_uri = bot_config.mongo_uri or settings.MONGODB_URL
            if mongo_uri:
                # Delete from MongoDB using motor client
                mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
                if mongo_client:
                    db_name = bot_config.mongo_db_name or "chatbot"
                    mongo_db = mongo_client[db_name]
                    await mongo_db["chunks"].delete_many({"source_id": str(source_id)})
                    logger.info(f"[Purge] Deleted chunks for source {source_id} from MongoDB")

        # Delete chunks from default MongoDB if not using custom Mongo
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("source_purge", settings.MONGODB_URL)
        chunks_deleted = 0
        vectors_deleted = 0
        
        if mongo_client:
            mongo_db = mongo_client["chatbot"]
            # Fetch source doc for file path
            source_doc = await mongo_db["knowledge_sources"].find_one({"_id": str(source_id)})
            if source_doc:
                if file_path is None:
                    file_path = source_doc.get("file_path")
                
                # Delete KnowledgeSource
                await mongo_db["knowledge_sources"].delete_many({"_id": str(source_id)})
                # Delete IngestionJobs
                await mongo_db["ingestion_jobs"].delete_many({"source_id": str(source_id)})
                # Delete chunks
                if not (bot_config and bot_config.use_custom_mongo):
                    res = await mongo_db["chunks"].delete_many({"source_id": str(source_id)})
                    chunks_deleted = res.deleted_count
                    vectors_deleted = res.deleted_count
        logger.info(f"[Purge] DB transaction committed for source {source_id}")

        # ── Step 4: Delete physical file from disk ───────────────────────────
        file_deleted = False
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True
                logger.info(f"[Purge] Deleted file from disk: {file_path}")
            except Exception as file_err:
                # Non-fatal — log and continue
                logger.warning(f"[Purge] Could not delete file {file_path}: {file_err}")

        # ── Step 5: Invalidate Redis cache keys ───────────────────────────────
        cache_keys_cleared = await self._invalidate_cache(redis, bot_id=bot_id, source_id=source_id)

        result_payload = {
            "source_id": str(source_id),
            "bot_id": str(bot_id),
            "chunks_deleted": chunks_deleted,
            "vectors_deleted": vectors_deleted,
            "file_deleted": file_deleted,
            "cache_keys_cleared": cache_keys_cleared,
        }
        logger.info(f"[Purge] Completed: {result_payload}")
        return result_payload

    async def _invalidate_cache(
        self,
        redis: Any,
        *,
        bot_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> int:
        """
        Scan and delete Redis keys under the standard namespaces:
          - cache:bot:{bot_id}:*
          - cache:source:{source_id}:*

        Uses SCAN to avoid blocking the Redis server.
        Falls back gracefully if the client is a MockRedisClient
        (which stores keys in a plain dict and supports 'delete' but not 'scan').

        Returns the count of deleted cache keys.
        """
        patterns = [
            f"cache:bot:{bot_id}:*",
            f"cache:source:{source_id}:*",
        ]
        total_cleared = 0

        # MockRedisClient does not implement SCAN — handle gracefully
        if getattr(redis, "is_mock", False):
            logger.debug("[Purge] MockRedisClient detected — skipping SCAN-based cache invalidation.")
            return 0

        for pattern in patterns:
            try:
                cursor = 0
                keys_to_delete = []
                while True:
                    cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
                    keys_to_delete.extend(keys)
                    if cursor == 0:
                        break

                if keys_to_delete:
                    deleted = await redis.delete(*keys_to_delete)
                    total_cleared += deleted
                    logger.info(
                        f"[Purge] Cleared {deleted} Redis key(s) matching '{pattern}'"
                    )
                else:
                    logger.debug(f"[Purge] No Redis keys matched pattern '{pattern}'")
            except Exception as cache_err:
                # Non-fatal — cache invalidation failure must never abort a purge
                logger.warning(f"[Purge] Redis cache invalidation failed for pattern '{pattern}': {cache_err}")

        return total_cleared


# Module-level singleton
source_purge_service = SourcePurgeService()
