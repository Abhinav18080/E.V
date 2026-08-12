"""
POST /chat — the main agent entrypoint.

Conversation turns are appended to a per-thread list in Redis so history
survives across requests (short-term memory). The actual model call is
wired to app.agent.graph once that's built — see TODO below.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from app.dependencies import CurrentUserDep, RedisDep

router = APIRouter()

THREAD_KEY_PREFIX = "thread:"
THREAD_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def _thread_key(thread_id: str) -> str:
    return f"{THREAD_KEY_PREFIX}{thread_id}"


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: CurrentUserDep, redis_client: RedisDep) -> ChatResponse:
    thread_id = request.thread_id or str(uuid.uuid4())
    key = _thread_key(thread_id)

    user_turn = ChatMessage(
        role="user",
        content=request.message,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    await redis_client.rpush(key, user_turn.model_dump_json())
    await redis_client.expire(key, THREAD_TTL_SECONDS)

    # TODO: replace this stub with a real invocation of the LangGraph agent:
    #
    #   from app.agent.graph import get_agent_graph
    #   graph = get_agent_graph()
    #   result = await graph.ainvoke(
    #       {"messages": await _load_history(redis_client, thread_id), "user_id": user_id},
    #       config={"configurable": {"thread_id": thread_id}},
    #   )
    #   if result.get("pending_approval"):
    #       return ChatResponse(thread_id=thread_id, reply="", pending_approval_id=result["pending_approval"]["id"])
    #   reply = result["messages"][-1].content
    #
    # Until app/agent/graph.py exists, fail loudly rather than fake a response.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Agent graph not wired up yet — see TODO in app/api/routes/chat.py",
    )


@router.get("/{thread_id}/history", response_model=list[ChatMessage])
async def get_thread_history(thread_id: str, user_id: CurrentUserDep, redis_client: RedisDep) -> list[ChatMessage]:
    raw = await redis_client.lrange(_thread_key(thread_id), 0, -1)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return [ChatMessage(**json.loads(item)) for item in raw]