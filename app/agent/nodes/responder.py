"""
Responder node — turns the final state into a reply message appended to
`messages`. Runs after planner decides to respond directly, or after
executor has run a tool (or a human rejected it via approval_gate). Prompt
text lives in app/agent/prompts/system.py and tool_use_prompt.py.
"""

from langchain_core.messages import AIMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.agent.prompts.system import BASE_SYSTEM_PROMPT
from app.agent.prompts.tool_use_prompt import RESPONDER_TOOL_RESULT_PROMPT
from app.agent.state import AgentState
from app.config import get_settings


def _get_model() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0.3)


async def responder(state: AgentState) -> dict:
    messages = [SystemMessage(content=BASE_SYSTEM_PROMPT)]

    tool_result = state.get("tool_result")
    if tool_result:
        messages.append(SystemMessage(content=RESPONDER_TOOL_RESULT_PROMPT))
        messages.append(SystemMessage(content=f"Tool result: {tool_result}"))

    messages.extend(state["messages"])

    reply = await _get_model().ainvoke(messages)
    return {"messages": [AIMessage(content=reply.content)]}