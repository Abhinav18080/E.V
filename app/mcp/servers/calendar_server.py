"""
MCP server exposing Google Calendar tools.

Run directly:      python -m app.mcp.servers.calendar_server
Or via Compose:     docker compose up mcp-calendar
"""

from mcp.server.fastmcp import FastMCP

from app.integrations.google import calendar_client

mcp = FastMCP("calendar-server", host="0.0.0.0", port=9001)


@mcp.tool(name="calendar.list_events")
async def list_events(user_id: str, start: str, end: str) -> list[dict]:
    """List the user's calendar events between `start` and `end` (ISO 8601 datetimes)."""
    return await calendar_client.list_events(user_id, start, end)


@mcp.tool(name="calendar.create_event")
async def create_event(
    user_id: str,
    summary: str,
    start: str,
    end: str,
    description: str | None = None,
    attendees: list[str] | None = None,
) -> dict:
    """
    Create a calendar event.

    NOTE: this is only ever invoked by app/agent/nodes/executor.py after a
    human has approved the action via the approval flow — this server has
    no independent notion of approval, it just performs the write.
    """
    return await calendar_client.create_event(user_id, summary, start, end, description, attendees)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")