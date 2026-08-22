"""
Approval gate node — pauses the graph until a human approves or rejects
state["pending_approval"], using LangGraph's interrupt().

Before pausing, this persists the pending approval to the Redis-backed
queue in app/api/routes/approvals.py (create_pending_approval), so it's
visible via GET /approvals independently of the paused graph run — that's
what a frontend polls to show "things waiting on you". create_pending_approval
is idempotent per thread_id specifically because of this call site: LangGraph
re-runs a node's code from the top on every resume, up to wherever
interrupt() was called (confirmed empirically — see the comment on
create_pending_approval), so without that idempotency this would create a
fresh duplicate approval record on every resume.

interrupt() itself then pauses graph execution right here; the current
state is persisted via the graph's checkpointer (see get_agent_graph in
app/agent/graph.py). Nothing after this line runs until something resumes
the graph with Command(resume=<decision>) against the same thread_id — see
resume_with_decision() in app/agent/graph.py, which
app/api/routes/approvals.py's decide_approval() calls once a human hits
approve/reject.
"""

from typing import Any

from langgraph.types import interrupt

from app.agent.state import AgentState


async def approval_gate(state: AgentState) -> dict:
    pending = state.get("pending_approval")
    if not pending:
        # Shouldn't normally happen given route_after_executor only sends us
        # here when pending_approval is set — fail safe rather than hang.
        return {}

    # Local imports: app.api.routes.approvals lives in the API layer, and
    # importing it at module load time would risk a circular import if that
    # layer ever imports from app.agent at its own module level. Safe here
    # since this only runs inside the node call, after both modules have
    # already finished loading.
    from app.api.routes.approvals import create_pending_approval
    from app.redis_client import get_redis_client

    approval = await create_pending_approval(
        redis_client=get_redis_client(),
        user_id=state["user_id"],
        thread_id=state["thread_id"],
        action_type=pending["action_type"],
        summary=pending["summary"],
        payload=pending["payload"],
    )
    pending_with_id = {**pending, "id": approval.id}

    decision: dict[str, Any] = interrupt(
        {
            "type": "approval_request",
            "approval": pending_with_id,
        }
    )

    approved = bool(decision.get("approve", False))
    return {
        "approval_decision": "approved" if approved else "rejected",
        "pending_approval": pending_with_id,
    }