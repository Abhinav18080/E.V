"""
LangGraph StateGraph definition — the agent's control flow.

    planner --tool_call--> executor --pending_approval--> approval_gate --(interrupt, resume)--> executor --> responder --> END
    planner --respond----------------------------------------------------------------------------------------> responder --> END
    executor --no pending approval-------------------------------------------------------------------------------------> responder --> END

Node implementations live in app/agent/nodes/*.py — this file only wires
them together and owns graph compilation / resumption.
"""

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.nodes.approval_gate import approval_gate
from app.agent.nodes.executor import executor
from app.agent.nodes.planner import planner
from app.agent.nodes.responder import responder
from app.agent.state import AgentState

# --- Routing -----------------------------------------------------------------


def route_after_planner(state: AgentState) -> str:
    next_action = state.get("next_action")
    if next_action == "tool_call":
        return "executor"
    if next_action == "await_approval":
        return "approval_gate"
    return "responder"


def route_after_executor(state: AgentState) -> str:
    if state.get("pending_approval"):
        return "approval_gate"
    return "responder"


# --- Graph assembly -----------------------------------------------------------


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("responder", responder)

    graph.set_entry_point("planner")

    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "executor": "executor",
            "approval_gate": "approval_gate",
            "responder": "responder",
        },
    )
    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "approval_gate": "approval_gate",
            "responder": "responder",
        },
    )
    # After approval_gate resumes (human decided), go back to executor so it
    # can act on state["approval_decision"].
    graph.add_edge("approval_gate", "executor")
    graph.add_edge("responder", END)

    return graph


@lru_cache
def get_agent_graph() -> CompiledStateGraph:
    """
    Compiled, cached graph instance.

    Uses LangGraph's in-memory checkpointer for now, which is enough for
    local dev but does NOT survive a process restart. Since the approval
    flow depends on being able to resume a paused thread later (possibly
    after the API process restarted), swap this for a persistent checkpointer
    before relying on this outside local dev — e.g. `langgraph-checkpoint-redis`
    (fits the free stack we're already using) or `langgraph-checkpoint-sqlite`.
    """
    checkpointer = MemorySaver()
    return build_graph().compile(checkpointer=checkpointer)


async def start_turn(user_id: str, thread_id: str, state_update: dict[str, Any]) -> dict:
    """
    Kick off (or continue) a conversation turn for a given thread.

    Called from app/api/routes/chat.py. `state_update` should at minimum
    include the new user message under "messages"; missing AgentState keys
    default sensibly since LangGraph merges this into any existing
    checkpointed state for the thread.
    """
    graph = get_agent_graph()
    config = {"configurable": {"thread_id": thread_id}}
    defaults = {
        "user_id": user_id,
        "thread_id": thread_id,
        "next_action": None,
        "tool_call": None,
        "tool_result": None,
        "memory_context": [],
        "pending_approval": None,
        "approval_decision": None,
    }
    return await graph.ainvoke({**defaults, **state_update}, config=config)


async def resume_with_decision(thread_id: str, approved: bool, reason: str | None = None) -> dict:
    """
    Resume a graph run that's paused at approval_gate (see interrupt() in
    app/agent/nodes/approval_gate.py). Called from
    app/api/routes/approvals.py after a human hits approve/reject.
    """
    graph = get_agent_graph()
    config = {"configurable": {"thread_id": thread_id}}
    return await graph.ainvoke(Command(resume={"approve": approved, "reason": reason}), config=config)