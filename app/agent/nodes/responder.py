"""
Responder node — turns the final state into a reply message appended to
`messages`. Runs after planner decides to respond directly, or after
executor has run a tool (or a human rejected it via approval_gate).

TODO: move SYSTEM_PROMPT into app/agent/prompts/ once that folder exists.
"""

from langchain_core.messages import AIMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.agent.state import AgentState
from app.config import get_settings

SYSTEM_PROMPT = (
    "You are a helpful personal assistant. Write a short, natural reply to "
    "the user based on the conversation so far. If a tool result is provided "
    "below, summarize what happened in plain language. If an action was "
    "rejected by the user during approval, acknowledge that without retrying it."
)


def _get_model() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0.3)


async def responder(state: AgentState) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    tool_result = state.get("tool_result")
    if tool_result:
        messages.append(SystemMessage(content=f"Latest tool result: {tool_result}"))

    messages.extend(state["messages"])

    reply = await _get_model().ainvoke(messages)
    return {"messages": [AIMessage(content=reply.content)]}