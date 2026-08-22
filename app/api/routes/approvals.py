"""
Human-in-the-loop approval endpoints.

When the agent graph wants to take a side-effecting action (send an email,
create a calendar event, etc.), app.agent.nodes.executor detects it and
app.agent.nodes.approval_gate persists a pending approval here (via
create_pending_approval) before calling LangGraph's interrupt() to pause the
graph run. decide_approval() below is the other half: it updates this
Redis-backed queue AND resumes the paused graph via
app.agent.graph.resume_with_decision(), plus writes a durable ApprovalRecord
row (app/db/models.py) so the decision survives this queue entry's TTL.
See docs/approval_flow.md for the full walkthrough.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.schemas.approval import ApprovalDecision, ApprovalRequest, ApprovalStatus
from app.db.models import ApprovalRecord
from app.db.session import SessionLocal
from app.dependencies import CurrentUserDep, RedisDep

router = APIRouter()

APPROVAL_KEY_PREFIX = "approval:"
APPROVAL_INDEX_KEY_PREFIX = "approvals_by_user:"
APPROVAL_TTL_SECONDS = 60 * 60 * 24 * 3  # 3 days


def _approval_key(approval_id: str) -> str:
    return f"{APPROVAL_KEY_PREFIX}{approval_id}"


def _user_index_key(user_id: str) -> str:
    return f"{APPROVAL_INDEX_KEY_PREFIX}{user_id}"


async def _find_pending_approval_for_thread(
    redis_client: RedisDep, user_id: str, thread_id: str
) -> ApprovalRequest | None:
    approval_ids = await redis_client.smembers(_user_index_key(user_id))
    for approval_id in approval_ids:
        raw = await redis_client.get(_approval_key(approval_id))
        if not raw:
            continue
        approval = ApprovalRequest(**json.loads(raw))
        if approval.thread_id == thread_id and approval.status == ApprovalStatus.pending:
            return approval
    return None


async def create_pending_approval(
    redis_client: RedisDep,
    user_id: str,
    thread_id: str,
    action_type: str,
    summary: str,
    payload: dict[str, Any],
) -> ApprovalRequest:
    """
    Called by app.agent.nodes.approval_gate when the graph wants to pause
    for human confirmation before a side-effecting action.

    Idempotent per thread_id — deliberately so. LangGraph re-runs a node's
    code from the top on every resume, up to wherever interrupt() was
    called (confirmed empirically: a node with code before interrupt() ran
    twice across one pause + one resume in testing). Without this check,
    every resume of a paused thread would create a second, duplicate
    approval record with a fresh id. If a pending approval already exists
    for this thread, it's returned as-is instead of creating a new one.
    """
    existing = await _find_pending_approval_for_thread(redis_client, user_id, thread_id)
    if existing:
        return existing

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


def _record_approval_decision(
    user_id: str,
    thread_id: str,
    action_type: str,
    summary: str,
    payload_json: str,
    status: str,
    reason: str | None,
) -> None:
    """Durable audit-log write — see ApprovalRecord's docstring in app/db/models.py.
    Synchronous (plain SQLAlchemy Session), so callers run this via asyncio.to_thread."""
    with SessionLocal() as db:
        db.add(
            ApprovalRecord(
                user_id=user_id,
                thread_id=thread_id,
                action_type=action_type,
                summary=summary,
                payload_json=payload_json,
                status=status,
                reason=reason,
                decided_at=datetime.now(timezone.utc),
            )
        )
        db.commit()


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

    # Resume the paused graph run with the human's decision. This runs the
    # rest of the turn synchronously — executor performing the real MCP
    # call (if approved) and responder generating the final reply — so this
    # request can take as long as that does. Fine for a personal-scale app;
    # revisit with a background task if that ever becomes noticeable.
    from app.agent.graph import resume_with_decision  # local import avoids a circular import

    await resume_with_decision(approval.thread_id, decision.approve, decision.reason)

    await asyncio.to_thread(
        _record_approval_decision,
        user_id=user_id,
        thread_id=approval.thread_id,
        action_type=approval.action_type,
        summary=approval.summary,
        payload_json=json.dumps(approval.payload),
        status=approval.status.value,
        reason=decision.reason,
    )

    return approval