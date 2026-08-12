"""
Redis connection singleton.

Used by: short-term agent memory (app/agent/memory/short_term.py), the
approval-gate node (to persist pending approvals), and rate limiting.
"""

from functools import lru_cache

import redis.asyncio as redis

from app.config import get_settings


@lru_cache
def get_redis_pool() -> redis.ConnectionPool:
    settings = get_settings()
    return redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis_client() -> redis.Redis:
    """
    Returns a Redis client backed by the shared connection pool.
    Cheap to call repeatedly — connections are pooled, not re-opened.
    """
    return redis.Redis(connection_pool=get_redis_pool())


async def ping() -> bool:
    client = get_redis_client()
    try:
        return await client.ping()
    except redis.RedisError:
        return False