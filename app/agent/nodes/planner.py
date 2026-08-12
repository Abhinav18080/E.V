"""
Planner node — decides whether the agent should call a tool or respond
directly, and if a tool, which one and with what arguments.

Uses the local Llama 3.1 8B model (via Ollama) with structured output so the
decision comes back as a typed object rather than parsed free text.

TODO:
  - Move SYSTEM_PROMPT into app/agent/prompts/planner_prompt.py once the
    prompts/ folder is built, so prompts can be iterated on independently
    of the node logic.
  - Replace the hardcoded AVAILABLE_TOOLS list below with a dynamic list
    from app.mcp.registry once the MCP servers exist, so planner always
    knows exactly what's actually available rather than a static guess.
"""

from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.agent.state import AgentState, ToolCall
from app.config import get_settings

AVAILABLE_TOOLS = [
    {"name": "calendar.list_events", "description": "List upcoming calendar events in a date range"},
    {
        "name": "calendar.create_event",
        "description": "Create a calendar event (side-effecting, requires human approval)",
    },
    {"name": "email.list_inbox", "description": "List recent inbox messages"},
    {"name": "email.send", "description": "Send an email (side-effecting, requires human approval)"},
    {"name": "tasks.list", "description": "List the user's tasks/todos"},
    {"name": "tasks.create", "description": "Create a task/todo item"},
]

SYSTEM_PROMPT = (
    "You are the planning component of a personal assistant agent. Given the "
    "conversation so far, decide whether to call one of the available tools "
    "or respond to the user directly.\n\n"
    "Available tools:\n"
    + "\n".join(f"- {t['name']}: {t['description']}" for t in AVAILABLE_TOOLS)
    + "\n\nIf the user's request can be answered directly without a tool, set "
    "next_action='respond'. Otherwise set next_action='tool_call' and specify "
    "tool_name (must exactly match one of the names above) and tool_args."
)


class PlannerDecision(BaseModel):
    next_action: Literal["tool_call", "respond"]
    tool_name: str | None = Field(default=None, description="Required if next_action is 'tool_call'")
    tool_args: dict = Field(default_factory=dict)


def _get_model() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0)


async def planner(state: AgentState) -> dict:
    model = _get_model().with_structured_output(PlannerDecision)

    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    if state.get("memory_context"):
        messages.append(
            SystemMessage(content="Relevant memory:\n" + "\n".join(state["memory_context"]))
        )
    messages.extend(state["messages"])

    decision: PlannerDecision = await model.ainvoke(messages)

    tool_call: ToolCall | None = None
    if decision.next_action == "tool_call" and decision.tool_name:
        tool_call = {"name": decision.tool_name, "args": decision.tool_args}

    return {"next_action": decision.next_action, "tool_call": tool_call}