import logging
from typing import Any, Dict, Optional, AsyncGenerator
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger("app.redis")

class MockRedisClient:
    """
    In-memory mock Redis client fallback for local development.
    Ensures app runs normally when local Redis instance is offline.
    """
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self.is_mock: bool = True

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self._store[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count

    async def incr(self, key: str) -> int:
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def close(self) -> None:
        pass


# Cached instance
_redis_client: Optional[Any] = None

async def get_redis() -> AsyncGenerator[Any, None]:
    """
    Dependency yielding the global Redis connection or fallback to Mock client.
    """
    global _redis_client
    if _redis_client is None:
        client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
        try:
            # Check connection
            await client.ping()
            _redis_client = client
            logger.info("Connected to Redis successfully.")
        except Exception:
            logger.warning("Redis is offline. Falling back to In-Memory Mock Redis Client.")
            await client.close()
            _redis_client = MockRedisClient()
            
    yield _redis_client

async def close_redis() -> None:
    """
    Close global redis client connection pool.
    """
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
