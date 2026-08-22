"""
POST /chat — the main agent entrypoint.

Delegates reasoning to the LangGraph agent (app.agent.graph.start_turn).
The graph's own checkpointer already accumulates messages per thread_id
across calls (via AgentState's add_messages reducer), so this endpoint only
needs to pass the new user message, not the full history, on each call.

Conversation history for GET /{thread_id}/history is read from
app.agent.memory.short_term — a separate, framework-agnostic Redis buffer
(distinct from the graph's checkpointer) that both this endpoint and any
agent node can read without touching LangGraph's checkpoint internals.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import start_turn
from app.agent.memory.short_term import append_message, get_recent_messages
from app.api.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from app.dependencies import CurrentUserDep

router = APIRouter()

_ROLE_LABELS = {"HumanMessage": "user", "AIMessage": "assistant", "SystemMessage": "system"}


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: CurrentUserDep) -> ChatResponse:
    thread_id = request.thread_id or str(uuid.uuid4())

    user_message = HumanMessage(content=request.message)
    await append_message(thread_id, user_message)

    result = await start_turn(
        user_id=user_id,
        thread_id=thread_id,
        state_update={"messages": [user_message]},
    )

    if "__interrupt__" in result:
        interrupt_payload = result["__interrupt__"][0].value
        approval_id = interrupt_payload["approval"]["id"]
        return ChatResponse(
            thread_id=thread_id,
            reply="I need your approval before doing that — check pending_approval_id.",
            pending_approval_id=approval_id,
        )

    reply_message = result["messages"][-1]
    await append_message(thread_id, AIMessage(content=reply_message.content))

    return ChatResponse(thread_id=thread_id, reply=reply_message.content)


@router.get("/{thread_id}/history", response_model=list[ChatMessage])
async def get_thread_history(thread_id: str, user_id: CurrentUserDep) -> list[ChatMessage]:
    messages = await get_recent_messages(thread_id, limit=200)
    if not messages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    return [
        ChatMessage(
            role=_ROLE_LABELS.get(type(m).__name__, "user"),
            content=m.content,
            timestamp=m.additional_kwargs.get("timestamp", ""),
        )
        for m in messages
    ]