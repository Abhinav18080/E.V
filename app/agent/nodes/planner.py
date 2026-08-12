"""
Planner node — decides whether the agent should call a tool or respond
directly, and if a tool, which one and with what arguments.

Uses the local Llama 3.1 8B model (via Ollama) with structured output so the
decision comes back as a typed object rather than parsed free text. Prompt
text lives in app/agent/prompts/planner_prompt.py.
"""

from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.agent.prompts.planner_prompt import build_planner_prompt
from app.agent.state import AgentState, ToolCall
from app.config import get_settings


class PlannerDecision(BaseModel):
    next_action: Literal["tool_call", "respond"]
    tool_name: str | None = Field(default=None, description="Required if next_action is 'tool_call'")
    tool_args: dict = Field(default_factory=dict)


def _get_model() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0)


async def planner(state: AgentState) -> dict:
    model = _get_model().with_structured_output(PlannerDecision)

    messages = [SystemMessage(content=build_planner_prompt())]
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