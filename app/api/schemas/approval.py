"""Pydantic models for app/api/routes/approvals.py."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    payload: dict[str, Any] = Field(
        ..., description="The actual action arguments, for execution on approval"
    )
    status: ApprovalStatus = ApprovalStatus.pending
    created_at: datetime
    decided_at: datetime | None = None


class ApprovalDecision(BaseModel):
    approve: bool
    reason: str | None = None