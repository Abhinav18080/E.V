"""
Approval gate node — pauses the graph until a human approves or rejects
state["pending_approval"], using LangGraph's interrupt().

When this node runs, interrupt() suspends graph execution right here and the
current state is persisted via the graph's checkpointer (see get_agent_graph
in app/agent/graph.py). Nothing after this line runs until something resumes
the graph by invoking it again with `Command(resume=<decision>)` against the
same thread_id — see resume_with_decision() in app/agent/graph.py, which
app/api/routes/approvals.py calls once a human hits approve/reject.

The dict passed to interrupt() is what gets surfaced to whatever's waiting
on the paused graph (e.g. returned from the initial ainvoke call that hit
the interrupt); the dict passed back via Command(resume=...) is what
interrupt() returns here.
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

    decision: dict[str, Any] = interrupt(
        {
            "type": "approval_request",
            "approval": pending,
        }
    )

    approved = bool(decision.get("approve", False))
    return {"approval_decision": "approved" if approved else "rejected"}