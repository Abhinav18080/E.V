"""
MCP server exposing Google Calendar tools.

Tool bodies are stubs until app/integrations/google/calendar_client.py
exists — each raises NotImplementedError, which FastMCP surfaces to callers
as a tool error (app/mcp/client.py turns that into an MCPToolError).

Run directly:      python -m app.mcp.servers.calendar_server
Or via Compose:     docker compose up mcp-calendar
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calendar-server", host="0.0.0.0", port=9001)


@mcp.tool(name="calendar.list_events")
async def list_events(user_id: str, start: str, end: str) -> list[dict]:
    """List the user's calendar events between `start` and `end` (ISO 8601 datetimes)."""
    # TODO: wire to app.integrations.google.calendar_client.list_events(user_id, start, end)
    raise NotImplementedError("Google Calendar integration not wired up yet")


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
    # TODO: wire to app.integrations.google.calendar_client.create_event(...)
    raise NotImplementedError("Google Calendar integration not wired up yet")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")