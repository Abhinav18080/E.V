"""Pydantic models for app/api/routes/chat.py."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's message to the assistant")
    thread_id: str | None = Field(
        default=None, description="Existing conversation thread id. Omit to start a new thread."
    )


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    pending_approval_id: str | None = Field(
        default=None,
        description="Set when the agent paused for human approval instead of replying directly.",
    )