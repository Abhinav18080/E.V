"""
Human-in-the-loop approval endpoints.

When the agent graph wants to take a side-effecting action (send an email,
create a calendar event, etc.), the approval_gate node will:
  1. write a pending ApprovalRequest here (via create_pending_approval, called
     from app.agent.nodes.approval_gate — not built yet)
  2. interrupt the graph run
  3. wait for a human decision via POST /approvals/{id}/decision below, which
     resumes the graph with the decision

For now this router is self-contained and fully functional against Redis;
the graph-resume half of the loop is a TODO until app/agent/graph.py exists.
"""

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserDep, RedisDep

router = APIRouter()

APPROVAL_KEY_PREFIX = "approval:"
APPROVAL_INDEX_KEY_PREFIX = "approvals_by_user:"
APPROVAL_TTL_SECONDS = 60 * 60 * 24 * 3  # 3 days


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class ApprovalRequest(BaseModel):
    id: str
    thread_id: str
    action_type: str = Field(..., description="e.g. 'send_email', 'create_calendar_event'")
    summary: str = Field(..., description="Human-readable description of the pending action")
    payload: dict[str, Any] = Field(..., description="The actual action arguments, for execution on approval")
    status: ApprovalStatus = ApprovalStatus.pending
    created_at: datetime
    decided_at: datetime | None = None


class ApprovalDecision(BaseModel):
    approve: bool
    reason: str | None = None


def _approval_key(approval_id: str) -> str:
    return f"{APPROVAL_KEY_PREFIX}{approval_id}"


def _user_index_key(user_id: str) -> str:
    return f"{APPROVAL_INDEX_KEY_PREFIX}{user_id}"


async def create_pending_approval(
    redis_client: RedisDep,
    user_id: str,
    thread_id: str,
    action_type: str,
    summary: str,
    payload: dict[str, Any],
) -> ApprovalRequest:
    """
    Called by app.agent.nodes.approval_gate (once built) when the graph wants
    to pause for human confirmation before a side-effecting action.
    """
    approval = ApprovalRequest(
        id=str(uuid.uuid4()),
        thread_id=thread_id,
        action_type=action_type,
        summary=summary,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    await redis_client.set(
        _approval_key(approval.id), approval.model_dump_json(), ex=APPROVAL_TTL_SECONDS
    )
    await redis_client.sadd(_user_index_key(user_id), approval.id)
    return approval


@router.get("", response_model=list[ApprovalRequest])
async def list_approvals(
    user_id: CurrentUserDep,
    redis_client: RedisDep,
    status_filter: ApprovalStatus | None = None,
) -> list[ApprovalRequest]:
    approval_ids = await redis_client.smembers(_user_index_key(user_id))
    approvals: list[ApprovalRequest] = []
    for approval_id in approval_ids:
        raw = await redis_client.get(_approval_key(approval_id))
        if raw:
            approval = ApprovalRequest(**json.loads(raw))
            if status_filter is None or approval.status == status_filter:
                approvals.append(approval)
    return sorted(approvals, key=lambda a: a.created_at, reverse=True)


@router.get("/{approval_id}", response_model=ApprovalRequest)
async def get_approval(approval_id: str, user_id: CurrentUserDep, redis_client: RedisDep) -> ApprovalRequest:
    raw = await redis_client.get(_approval_key(approval_id))
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return ApprovalRequest(**json.loads(raw))


@router.post("/{approval_id}/decision", response_model=ApprovalRequest)
async def decide_approval(
    approval_id: str, decision: ApprovalDecision, user_id: CurrentUserDep, redis_client: RedisDep
) -> ApprovalRequest:
    raw = await redis_client.get(_approval_key(approval_id))
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

    approval = ApprovalRequest(**json.loads(raw))
    if approval.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval already decided (status={approval.status})",
        )

    approval.status = ApprovalStatus.approved if decision.approve else ApprovalStatus.rejected
    approval.decided_at = datetime.now(timezone.utc)
    await redis_client.set(_approval_key(approval.id), approval.model_dump_json(), ex=APPROVAL_TTL_SECONDS)

    # TODO: once app/agent/graph.py exists, resume the paused graph run here:
    #
    #   from app.agent.graph import get_agent_graph
    #   graph = get_agent_graph()
    #   await graph.ainvoke(
    #       None,  # resume rather than start fresh
    #       config={"configurable": {"thread_id": approval.thread_id}},
    #   )
    #
    # If rejected, the resumed graph should skip the action and tell the user
    # why (using decision.reason) rather than silently dropping it.

    return approval