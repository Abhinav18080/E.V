"""
Redis-backed rate limiting.

Two ways to use this:
  - check_rate_limit(...) directly, for guarding outbound calls to
    quota-limited free APIs (e.g. web_search.search, or the Google APIs'
    daily quotas) from inside a workflow or node.
  - rate_limit(...) as a FastAPI dependency, for guarding endpoints
    directly — see the usage example in its docstring.

Implemented as a fixed-window counter (INCR + EXPIRE) rather than a sliding
window or token bucket: simpler, one Redis round-trip per check, and
"slightly bursty at window boundaries" is a fine tradeoff for a
personal-scale project. Revisit if this ever needs to be precise.
"""

from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.dependencies import CurrentUserDep, RedisDep
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def check_rate_limit(redis_client: Redis, key: str, max_requests: int, window_seconds: int) -> bool:
    """
    Increment the counter for `key` and return whether this request is
    still within the limit. The key's TTL is (re)set only on the first
    increment in a window, so the window is anchored to first-request time
    rather than sliding.
    """
    full_key = f"rate_limit:{key}"
    count = await redis_client.incr(full_key)
    if count == 1:
        await redis_client.expire(full_key, window_seconds)
    return count <= max_requests


def rate_limit(max_requests: int, window_seconds: int, scope: str = "default"):
    """
    FastAPI dependency factory. Usage:

        @router.post(
            "",
            dependencies=[Depends(rate_limit(20, 60, scope="chat"))],
        )
        async def chat(...): ...

    Keyed by (scope, user_id) so different endpoints don't share a budget
    unless you want them to (pass the same `scope` to make them share one).
    Not currently applied to any route — add the dependency to a router in
    app/api/routes/ when you want one enforced.
    """

    async def dependency(user_id: CurrentUserDep, redis_client: RedisDep) -> None:
        allowed = await check_rate_limit(redis_client, f"{scope}:{user_id}", max_requests, window_seconds)
        if not allowed:
            logger.warning("Rate limit exceeded: scope=%s user_id=%s", scope, user_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: max {max_requests} requests per {window_seconds}s",
            )

    return dependency