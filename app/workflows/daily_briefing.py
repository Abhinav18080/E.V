"""
Daily briefing workflow — pulls together today's calendar events, unread
inbox messages, and open tasks into one short summary.

Nothing calls generate_briefing() on a schedule yet — see the note at the
bottom of this file for how to wire that up.
"""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.integrations.llm.model_config import RESPONDER_CONFIG
from app.integrations.llm.provider import get_chat_model
from app.mcp.client import call as call_mcp_tool

BRIEFING_SYSTEM_PROMPT = (
    "You write a short, friendly daily briefing for a personal assistant "
    "user. Summarize their day in 3-5 sentences: what's on the calendar, "
    "anything urgent in their inbox, and tasks that are due or overdue. Be "
    "concise and skip sections that have nothing to report."
)


def _unwrap(result: Any) -> list | None:
    """MCP list-returning tools sometimes come back as {"result": [...]}; normalize."""
    if isinstance(result, dict) and "result" in result:
        return result["result"]
    return result


async def _safe_call(tool_name: str, args: dict[str, Any]) -> list:
    """
    Best-effort tool call — a tool-level error (MCPToolError, e.g. Google
    auth not set up yet) or a connection-level failure (server not running,
    network issue) should degrade this section of the briefing to empty
    rather than taking the whole briefing down.
    """
    try:
        return _unwrap(await call_mcp_tool(tool_name, args)) or []
    except Exception:
        # TODO: log this once app/utils/logging.py exists, so a genuinely
        # down server is visible somewhere even though it's non-fatal here.
        return []


async def gather_briefing_data(user_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59)

    events = await _safe_call(
        "calendar.list_events",
        {"user_id": user_id, "start": now.isoformat(), "end": end_of_day.isoformat()},
    )
    inbox = await _safe_call("email.list_inbox", {"user_id": user_id, "max_results": 10})
    tasks = await _safe_call("tasks.list", {"user_id": user_id})

    return {
        "events": events,
        "unread_emails": [m for m in inbox if m.get("unread")],
        "open_tasks": [t for t in tasks if t.get("status") != "done"],
    }


async def generate_briefing(user_id: str) -> str:
    """
    Build today's briefing: gather calendar/email/task data, then have the
    LLM turn it into a short natural-language summary.
    """
    data = await gather_briefing_data(user_id)

    if not data["events"] and not data["unread_emails"] and not data["open_tasks"]:
        return "Nothing on your plate today — no events, unread mail, or open tasks."

    context = (
        f"Today's calendar events: {data['events']}\n"
        f"Unread emails: {data['unread_emails']}\n"
        f"Open tasks: {data['open_tasks']}"
    )

    model = get_chat_model(RESPONDER_CONFIG)
    reply = await model.ainvoke(
        [SystemMessage(content=BRIEFING_SYSTEM_PROMPT), HumanMessage(content=context)]
    )
    return reply.content


# NOTE: nothing currently triggers generate_briefing() on a schedule.
# Simplest free options, in rough order of effort:
#   1. A cron job (or a sidecar container running a `sleep`+`curl` loop)
#      hitting a new POST /briefing route — that route doesn't exist yet,
#      add one under app/api/routes/ if you want this reachable over HTTP.
#   2. APScheduler running in-process inside app/main.py's lifespan, calling
#      generate_briefing() directly and pushing the result somewhere (email,
#      a stored "briefing:{user_id}:{date}" Redis key for the frontend to
#      poll, etc).