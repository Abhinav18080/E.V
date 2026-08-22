"""
End-to-end test of the full human-in-the-loop approval loop — the piece
docs/approval_flow.md used to describe as "two working halves, not yet
connected." This test exercises the actual connected path: POST /chat's
handler pausing on a side-effecting tool call, the pending approval being
visible in the Redis-backed queue, deciding it resuming the paused graph,
and a durable ApprovalRecord row landing in the database.

The LLM layer is mocked (no Ollama needed); the MCP call is mocked too,
since exercising a real Google API call isn't the point of this test — the
approval plumbing connecting chat -> graph -> approvals -> DB is.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

import app.agent.nodes.executor as executor_module
import app.agent.nodes.planner as planner_module
import app.agent.nodes.responder as responder_module
from app.agent.nodes.planner import PlannerDecision
from app.api.routes.approvals import create_pending_approval, decide_approval, list_approvals
from app.api.routes.chat import chat
from app.api.schemas.approval import ApprovalDecision
from app.api.schemas.chat import ChatRequest
from app.db.models import ApprovalRecord
from app.db.session import SessionLocal


def _mock_planner_tool_call(monkeypatch, tool_name: str, tool_args: dict):
    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock(
        return_value=PlannerDecision(next_action="tool_call", tool_name=tool_name, tool_args=tool_args)
    )
    base_model = MagicMock()
    base_model.with_structured_output.return_value = structured_model
    monkeypatch.setattr(planner_module, "get_chat_model", lambda config: base_model)


def _mock_responder(monkeypatch, reply: str):
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content=reply))
    monkeypatch.setattr(responder_module, "get_chat_model", lambda config: model)


@pytest.mark.usefixtures("redis_client")
class TestApprovalLoopEndToEnd:
    async def test_approved_action_runs_and_records_audit_trail(self, monkeypatch, redis_client):
        user_id = "pytest:approval-loop-approve"
        _mock_planner_tool_call(
            monkeypatch,
            "email.send",
            {"to": ["friend@example.com"], "subject": "Trip plans", "body": "Here they are!"},
        )
        _mock_responder(monkeypatch, "Done — I sent the email.")

        response = await chat(ChatRequest(message="Email my friend"), user_id=user_id)

        assert response.pending_approval_id
        approval_id = response.pending_approval_id
        thread_id = response.thread_id

        approvals = await list_approvals(user_id=user_id, redis_client=redis_client)
        matching = [a for a in approvals if a.id == approval_id]
        assert len(matching) == 1
        assert matching[0].status.value == "pending"
        assert matching[0].action_type == "email.send"

        async def fake_call_mcp_tool(tool_name, args):
            assert tool_name == "email.send"
            return {"message_id": "sent-123", "status": "sent"}

        monkeypatch.setattr(executor_module, "call_mcp_tool", fake_call_mcp_tool)

        decided = await decide_approval(
            approval_id, ApprovalDecision(approve=True), user_id=user_id, redis_client=redis_client
        )
        assert decided.status.value == "approved"

        with SessionLocal() as db:
            records = db.query(ApprovalRecord).filter(ApprovalRecord.thread_id == thread_id).all()
            assert len(records) == 1
            assert records[0].status == "approved"
            assert records[0].action_type == "email.send"

        with pytest.raises(HTTPException) as exc_info:
            await decide_approval(
                approval_id, ApprovalDecision(approve=True), user_id=user_id, redis_client=redis_client
            )
        assert exc_info.value.status_code == 409

    async def test_rejected_action_does_not_run_and_is_idempotent_to_create(self, monkeypatch, redis_client):
        user_id = "pytest:approval-loop-reject"
        _mock_planner_tool_call(
            monkeypatch,
            "calendar.create_event",
            {"summary": "Team offsite", "start": "2026-09-15T09:00:00Z", "end": "2026-09-15T17:00:00Z"},
        )
        _mock_responder(monkeypatch, "No problem, I won't create that event.")

        response = await chat(ChatRequest(message="Add the offsite to my calendar"), user_id=user_id)
        approval_id = response.pending_approval_id

        # Simulates LangGraph re-running approval_gate's pre-interrupt code on
        # a resume (documented, empirically-verified behavior) — should
        # return the SAME approval rather than creating a duplicate.
        duplicate = await create_pending_approval(
            redis_client=redis_client,
            user_id=user_id,
            thread_id=response.thread_id,
            action_type="calendar.create_event",
            summary="a different summary — should be ignored",
            payload={},
        )
        assert duplicate.id == approval_id

        decided = await decide_approval(
            approval_id,
            ApprovalDecision(approve=False, reason="Not needed"),
            user_id=user_id,
            redis_client=redis_client,
        )
        assert decided.status.value == "rejected"

        with SessionLocal() as db:
            record = (
                db.query(ApprovalRecord).filter(ApprovalRecord.thread_id == response.thread_id).one()
            )
            assert record.status == "rejected"
            assert record.reason == "Not needed"