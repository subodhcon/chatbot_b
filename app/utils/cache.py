import json
import logging
from typing import Any, Optional

logger = logging.getLogger("app.cache")


async def get_cached_val(redis_client, key: str) -> Optional[Any]:
    """
    Retrieve and deserialize a cached JSON value from Redis.
    """
    try:
        val = await redis_client.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.error(f"Failed to read from Redis cache for key '{key}': {e}")
    return None


async def set_cached_val(
    redis_client, key: str, value: Any, expire_seconds: int = 300
) -> None:
    """
    Serialize and store a JSON value in Redis with an expiration window.
    """
    try:
        await redis_client.set(key, json.dumps(value), ex=expire_seconds)
    except Exception as e:
        logger.error(f"Failed to write to Redis cache for key '{key}': {e}")


async def invalidate_cache(redis_client, key: str) -> None:
    """
    Evict a key from the Redis cache.
    """
    try:
        await redis_client.delete(key)
        logger.info(f"Cache key evicted: '{key}'")
    except Exception as e:
        logger.error(f"Failed to invalidate Redis cache key '{key}': {e}")
