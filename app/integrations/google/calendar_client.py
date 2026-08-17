"""
Google Calendar API client — used by app/mcp/servers/calendar_server.py.

`static_discovery=True` makes build() use the discovery doc bundled with
google-api-python-client instead of fetching it from googleapis.com, so this
only needs network access for the actual Calendar API calls, not for
service setup. Every `.execute()` call is blocking, so each is offloaded via
asyncio.to_thread rather than stalling the event loop.
"""

import asyncio
from typing import Any

from googleapiclient.discovery import build

from app.integrations.google.auth import get_credentials

CALENDAR_ID = "primary"


async def list_events(user_id: str, start: str, end: str) -> list[dict[str, Any]]:
    """List events between `start` and `end` (ISO 8601 datetimes) on the user's primary calendar."""
    credentials = await get_credentials(user_id)
    service = build("calendar", "v3", credentials=credentials, static_discovery=True)

    result = await asyncio.to_thread(
        lambda: service.events()
        .list(calendarId=CALENDAR_ID, timeMin=start, timeMax=end, singleEvents=True, orderBy="startTime")
        .execute()
    )

    return [
        {
            "id": event["id"],
            "summary": event.get("summary", "(no title)"),
            "start": event["start"].get("dateTime", event["start"].get("date")),
            "end": event["end"].get("dateTime", event["end"].get("date")),
            "description": event.get("description"),
            "attendees": [a["email"] for a in event.get("attendees", [])],
        }
        for event in result.get("items", [])
    ]


async def create_event(
    user_id: str,
    summary: str,
    start: str,
    end: str,
    description: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create an event on the user's primary calendar.

    NOTE: callers (app/mcp/servers/calendar_server.py, invoked in turn by
    app/agent/nodes/executor.py) are responsible for only calling this after
    human approval — this function has no notion of approval itself.
    """
    credentials = await get_credentials(user_id)
    service = build("calendar", "v3", credentials=credentials, static_discovery=True)

    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees]

    created = await asyncio.to_thread(
        lambda: service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    )

    return {
        "id": created["id"],
        "summary": created.get("summary"),
        "start": created["start"].get("dateTime"),
        "end": created["end"].get("dateTime"),
        "html_link": created.get("htmlLink"),
    }