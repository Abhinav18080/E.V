"""
Task coordinator workflow — cross-tool orchestration that keeps tasks in
sync with what's happening elsewhere: turning actionable emails into tasks,
and creating prep tasks ahead of upcoming calendar events.

Both directions are idempotent via a Redis set of already-processed source
ids, so re-running this (e.g. on a schedule, alongside daily_briefing.py)
doesn't create duplicate tasks.
"""

from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.integrations.llm.model_config import PLANNER_CONFIG
from app.integrations.llm.provider import get_chat_model
from app.mcp.client import call as call_mcp_tool
from app.redis_client import get_redis_client

PROCESSED_EMAILS_KEY_PREFIX = "task_coordinator:processed_emails:"
PROCESSED_EVENTS_KEY_PREFIX = "task_coordinator:processed_events:"

EMAIL_TRIAGE_PROMPT = (
    "Does this email require the recipient to take a concrete action (reply "
    "with something, complete something, send something by a deadline)? If "
    "yes, extract a short, actionable task title. If it's purely "
    "informational (a newsletter, a notification, a receipt), no action is "
    "needed."
)


class EmailTriageResult(BaseModel):
    actionable: bool
    task_title: str | None = Field(default=None, description="Required if actionable is true")


def _unwrap(result: Any) -> list | None:
    """MCP list-returning tools sometimes come back as {"result": [...]}; normalize."""
    if isinstance(result, dict) and "result" in result:
        return result["result"]
    return result


async def sync_tasks_from_inbox(user_id: str, max_emails: int = 10) -> list[dict[str, Any]]:
    """
    Scan the user's unread inbox and create a task for any email that looks
    actionable. Returns the tasks created this run (empty if nothing new,
    or if email.list_inbox isn't reachable — e.g. before Google auth is
    wired up for this user).
    """
    redis_client = get_redis_client()
    processed_key = f"{PROCESSED_EMAILS_KEY_PREFIX}{user_id}"

    try:
        inbox = _unwrap(
            await call_mcp_tool("email.list_inbox", {"user_id": user_id, "max_results": max_emails})
        )
    except Exception:
        # Covers both a clean MCPToolError and connection-level failures
        # (server not running). Either way, nothing to sync this run.
        return []

    model = get_chat_model(PLANNER_CONFIG).with_structured_output(EmailTriageResult)
    created: list[dict[str, Any]] = []

    for message in inbox or []:
        if not message.get("unread"):
            continue
        if await redis_client.sismember(processed_key, message["id"]):
            continue

        triage: EmailTriageResult = await model.ainvoke(
            [
                SystemMessage(content=EMAIL_TRIAGE_PROMPT),
                HumanMessage(
                    content=(
                        f"Subject: {message['subject']}\n"
                        f"From: {message['sender']}\n"
                        f"Snippet: {message['snippet']}"
                    )
                ),
            ]
        )

        if triage.actionable and triage.task_title:
            task = await call_mcp_tool(
                "tasks.create",
                {
                    "user_id": user_id,
                    "title": triage.task_title,
                    "description": f"From email: {message['subject']} ({message['sender']})",
                    "source": "email",
                },
            )
            created.append(task)

        await redis_client.sadd(processed_key, message["id"])

    return created


async def create_prep_tasks_for_upcoming_events(
    user_id: str, lookahead_days: int = 3, prep_lead_time_hours: int = 24
) -> list[dict[str, Any]]:
    """
    For each upcoming calendar event, create a "Prepare for: <event>" task
    if one doesn't already exist for it. `prep_lead_time_hours` is currently
    informational (included in the task description) rather than used to
    compute a due_date — wire that in once task due-dates matter more than
    creation order.
    """
    redis_client = get_redis_client()
    processed_key = f"{PROCESSED_EVENTS_KEY_PREFIX}{user_id}"

    now = datetime.now()
    end = now + timedelta(days=lookahead_days)
    try:
        events = _unwrap(
            await call_mcp_tool(
                "calendar.list_events",
                {"user_id": user_id, "start": now.isoformat(), "end": end.isoformat()},
            )
        )
    except Exception:
        # Covers both a clean MCPToolError and connection-level failures.
        return []

    created: list[dict[str, Any]] = []
    for event in events or []:
        if await redis_client.sismember(processed_key, event["id"]):
            continue

        task = await call_mcp_tool(
            "tasks.create",
            {
                "user_id": user_id,
                "title": f"Prepare for: {event['summary']}",
                "description": f"Event at {event['start']} (create at least {prep_lead_time_hours}h ahead)",
                "source": "calendar",
            },
        )
        created.append(task)
        await redis_client.sadd(processed_key, event["id"])

    return created