"""
Integration test for the calendar flow: real subprocess MCP server, real
streamable-HTTP client (app/mcp/client.py), real app/mcp/registry.py
resolution — the actual wire protocol, not tool functions called directly
in-process (that's tests/unit/test_mcp_servers.py).

The one thing this can't cover without real Google OAuth credentials is a
successful list_events/create_event call — that happy path is covered
in-process (with the Google client mocked) in test_mcp_servers.py instead.
What this file verifies is that the whole stack — client -> wire protocol ->
FastMCP server -> our calendar_server tool -> calendar_client -> auth —
correctly propagates a real error end to end.
"""

import pytest

from app.mcp.client import MCPToolError, call_tool, list_tools
from app.mcp.registry import discover_tools, get_server_url


class TestCalendarFlowIntegration:
    def test_registry_resolves_calendar_tools_to_the_right_server(self):
        assert get_server_url("calendar.list_events") == "http://localhost:9001"
        assert get_server_url("calendar.create_event") == "http://localhost:9001"

    async def test_server_advertises_its_tools(self, calendar_mcp_server):
        tools = await list_tools(calendar_mcp_server)
        tool_names = {t.name for t in tools}
        assert {"calendar.list_events", "calendar.create_event"} <= tool_names

    async def test_discover_tools_finds_calendar_server_when_running(self, calendar_mcp_server):
        discovered = await discover_tools()
        calendar_tool_names = {t.name for t in discovered["calendar"]}
        assert "calendar.list_events" in calendar_tool_names

    async def test_list_events_without_credentials_surfaces_as_mcp_tool_error(self, calendar_mcp_server):
        with pytest.raises(MCPToolError, match="No Google credentials stored"):
            await call_tool(
                calendar_mcp_server,
                "calendar.list_events",
                {"user_id": "pytest:no-such-user", "start": "2026-01-01", "end": "2026-01-02"},
            )

    async def test_create_event_without_credentials_surfaces_as_mcp_tool_error(self, calendar_mcp_server):
        with pytest.raises(MCPToolError, match="No Google credentials stored"):
            await call_tool(
                calendar_mcp_server,
                "calendar.create_event",
                {
                    "user_id": "pytest:no-such-user",
                    "summary": "Test event",
                    "start": "2026-01-01T10:00:00Z",
                    "end": "2026-01-01T11:00:00Z",
                },
            )