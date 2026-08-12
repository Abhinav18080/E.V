"""
LangGraph StateGraph definition — the agent's control flow.

    planner --tool_call--> executor --pending_approval--> approval_gate --> executor (resume) --> responder --> END
    planner --respond----------------------------------------------------------------------------> responder --> END
    executor --no pending approval------------------------------------------------------------------------> responder --> END

Node implementations belong in app/agent/nodes/*.py; this file only wires
them together. Each node below is a minimal inline stub for now — replace
with `from app.agent.nodes.<name> import <name>` as each one is built, and
delete the stub.
"""

from functools import lru_cache

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.state import AgentState

# --- Node stubs --------------------------------------------------------------
# TODO: move each of these into app/agent/nodes/<name>.py.


async def planner(state: AgentState) -> dict:
    """
    Decide whether to call a tool, respond directly, or route to approval.

    TODO: replace with a real call to the configured LLM (via
    app.integrations.llm.provider) using state["messages"] and
    state["memory_context"] to decide next_action, and — when the decision
    is "tool_call" — which tool/args to use (stashed on the state for
    executor to read).
    """
    return {"next_action": "respond"}


async def executor(state: AgentState) -> dict:
    """
    Run the tool call chosen by the planner, dispatched through MCP.

    TODO: use app.mcp.client to call the relevant MCP server (calendar,
    email, tasks). If the tool is side-effecting (send_email,
    create_calendar_event, etc.) and hasn't been approved yet, return a
    `pending_approval` dict instead of executing, which routes to
    approval_gate via route_after_executor below.
    """
    return {}


async def approval_gate(state: AgentState) -> dict:
    """
    Pause the graph until a human approves or rejects state["pending_approval"].

    TODO: this is where LangGraph's `interrupt()` gets used to actually
    suspend execution. app/api/routes/approvals.py writes the pending
    approval (via create_pending_approval) and later resumes this thread
    with the human's decision, which should land in state["approval_decision"].
    """
    return {}


async def responder(state: AgentState) -> dict:
    """
    Turn the final state into a reply message appended to `messages`.

    TODO: replace the stub content with a real LLM-generated summary of what
    the executor did (or why the agent is asking for approval / direct reply).
    """
    return {"messages": [AIMessage(content="(stub) agent response — planner/executor not wired up yet")]}


# --- Routing -------------------------------------------------------------


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


# --- Graph assembly --------------------------------------------------------


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
    # After approval_gate resolves (human decides), go back to executor so it
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
    after the API process restarts), swap this for a persistent checkpointer
    before relying on this outside local dev — e.g. `langgraph-checkpoint-redis`
    (fits the free stack we're already using) or `langgraph-checkpoint-sqlite`.
    """
    checkpointer = MemorySaver()
    return build_graph().compile(checkpointer=checkpointer)