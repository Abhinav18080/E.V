"""
Short-term memory — a Redis-backed conversation buffer.

This is separate from LangGraph's own checkpointer (see get_agent_graph in
app/agent/graph.py, which persists the full AgentState per thread for
resuming interrupted runs). This module is a lighter, framework-agnostic
read path for "recent messages in this thread" — used by
app/api/routes/chat.py's history endpoint, and available to any node that
wants recent context without going through the graph's checkpoint machinery.

NOTE: app/api/routes/chat.py currently has its own inline Redis list logic
for thread history, predating this module. Worth consolidating onto this
module so there's one source of truth — flagged rather than done here to
keep this change scoped to the memory layer.
"""

import json
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.redis_client import get_redis_client

THREAD_KEY_PREFIX = "thread:"
THREAD_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

_ROLE_TO_CLASS: dict[str, type[BaseMessage]] = {
    "human": HumanMessage,
    "ai": AIMessage,
    "system": SystemMessage,
}
_CLASS_TO_ROLE = {cls: role for role, cls in _ROLE_TO_CLASS.items()}


def _thread_key(thread_id: str) -> str:
    return f"{THREAD_KEY_PREFIX}{thread_id}"


def _serialize(message: BaseMessage) -> str:
    role = _CLASS_TO_ROLE.get(type(message), "human")
    return json.dumps(
        {
            "role": role,
            "content": message.content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


def _deserialize(raw: str) -> BaseMessage:
    data = json.loads(raw)
    cls = _ROLE_TO_CLASS.get(data["role"], HumanMessage)
    return cls(content=data["content"])


async def append_message(thread_id: str, message: BaseMessage) -> None:
    redis_client = get_redis_client()
    key = _thread_key(thread_id)
    await redis_client.rpush(key, _serialize(message))
    await redis_client.expire(key, THREAD_TTL_SECONDS)


async def get_recent_messages(thread_id: str, limit: int = 50) -> list[BaseMessage]:
    """Returns up to `limit` most recent messages, oldest first."""
    redis_client = get_redis_client()
    raw = await redis_client.lrange(_thread_key(thread_id), -limit, -1)
    return [_deserialize(r) for r in raw]


async def clear_thread(thread_id: str) -> None:
    redis_client = get_redis_client()
    await redis_client.delete(_thread_key(thread_id))