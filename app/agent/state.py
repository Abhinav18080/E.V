"""
AgentState — the shared state object that flows through the LangGraph graph.

Every node reads from this state and returns a partial dict update. Keys that
should accumulate across nodes (like `messages`) use LangGraph's reducer
pattern via `Annotated[..., add_messages]`, so a node can just return the new
message(s) rather than manually appending to the existing list.
"""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class PendingApproval(TypedDict):
    """Mirrors app.api.schemas.approval.ApprovalRequest's key fields."""

    id: str
    action_type: str  # e.g. "send_email", "create_calendar_event"
    summary: str
    payload: dict[str, Any]


class AgentState(TypedDict):
    # --- Conversation ---
    # add_messages appends new messages and handles de-duping/merging by id,
    # rather than the node having to manage the list itself.
    messages: Annotated[list[BaseMessage], add_messages]

    # --- Identity / routing ---
    user_id: str
    thread_id: str

    # --- Planning ---
    # Set by the planner node; read by the graph's conditional edges to
    # decide where to route next. See route_after_planner in graph.py.
    next_action: Literal["tool_call", "respond", "await_approval", "end"] | None

    # --- Memory ---
    # Long-term facts/preferences retrieved for this turn from the vector
    # store (app/agent/memory/long_term.py), injected into the planner prompt.
    memory_context: list[str]

    # --- Human approval ---
    # Populated by the executor node when it hits a side-effecting tool call
    # that requires sign-off; cleared once approval_gate resolves it.
    pending_approval: PendingApproval | None

    # The human's decision, written by app/api/routes/approvals.py when it
    # resumes a paused graph run. Consumed by executor to decide whether to
    # actually perform the pending action or report that it was rejected.
    approval_decision: Literal["approved", "rejected"] | None