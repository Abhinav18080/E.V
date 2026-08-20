"""
Integration test for the email flow — same shape as test_calendar_flow.py:
real subprocess MCP server, real wire protocol client, real registry
resolution. See that file's module docstring for why the happy path
(a successful send/list) is covered elsewhere (test_mcp_servers.py, with
the Google client mocked) rather than here.
"""

import pytest

from app.mcp.client import MCPToolError, call_tool, list_tools
from app.mcp.registry import discover_tools, get_server_url


class TestEmailFlowIntegration:
    def test_registry_resolves_email_tools_to_the_right_server(self):
        assert get_server_url("email.list_inbox") == "http://localhost:9002"
        assert get_server_url("email.send") == "http://localhost:9002"

    async def test_server_advertises_its_tools(self, email_mcp_server):
        tools = await list_tools(email_mcp_server)
        tool_names = {t.name for t in tools}
        assert {"email.list_inbox", "email.send"} <= tool_names

    async def test_discover_tools_finds_email_server_when_running(self, email_mcp_server):
        discovered = await discover_tools()
        email_tool_names = {t.name for t in discovered["email"]}
        assert "email.send" in email_tool_names

    async def test_list_inbox_without_credentials_surfaces_as_mcp_tool_error(self, email_mcp_server):
        with pytest.raises(MCPToolError, match="No Google credentials stored"):
            await call_tool(email_mcp_server, "email.list_inbox", {"user_id": "pytest:no-such-user"})

    async def test_send_without_credentials_surfaces_as_mcp_tool_error(self, email_mcp_server):
        with pytest.raises(MCPToolError, match="No Google credentials stored"):
            await call_tool(
                email_mcp_server,
                "email.send",
                {
                    "user_id": "pytest:no-such-user",
                    "to": ["friend@example.com"],
                    "subject": "Test",
                    "body": "Test body",
                },
            )