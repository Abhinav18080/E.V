"""
Redis connection singleton, plus pub/sub helpers.

Used for:
  - state: short-term agent memory (app/agent/memory/short_term.py),
    thread summaries (app/agent/memory/summarizer.py), the pending-approvals
    queue and OAuth state (app/api/routes/approvals.py, auth.py)
  - cache: session-token -> user_id lookups (app/dependencies.py)
  - pub/sub: publish_event()/subscribe() below, for pushing real-time
    updates (e.g. "an approval is waiting on you") to anything listening —
    not consumed by anything yet since there's no WebSocket/SSE route to
    relay them to a client, but the plumbing is here for when one exists.
"""

import json
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

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


def user_channel(user_id: str) -> str:
    """Channel name for a given user's real-time events. Keeps the naming
    convention in one place rather than scattering f-strings across callers."""
    return f"user:{user_id}:events"


async def publish_event(channel: str, event: dict[str, Any]) -> None:
    """
    Publish a JSON-serializable event to a channel. Fire-and-forget — if
    nothing is subscribed right now, the event is simply dropped (Redis
    pub/sub has no persistence/replay), which is fine for "notify anyone
    currently watching" use cases like an approval request appearing.
    """
    client = get_redis_client()
    await client.publish(channel, json.dumps(event))


async def subscribe(channel: str) -> AsyncGenerator[dict[str, Any], None]:
    """
    Subscribe to a channel and yield each published event as a parsed dict.
    Intended for a future WebSocket/SSE route to consume, e.g.:

        async for event in subscribe(user_channel(user_id)):
            await websocket.send_json(event)

    The generator runs until the caller stops iterating (e.g. the client
    disconnects) or the connection is cancelled — it doesn't unsubscribe on
    its own otherwise.
    """
    client = get_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()