"""
MCP server exposing Gmail tools.

Tool bodies are stubs until app/integrations/google/gmail_client.py exists —
each raises NotImplementedError, which FastMCP surfaces to callers as a tool
error (app/mcp/client.py turns that into an MCPToolError).

Run directly:      python -m app.mcp.servers.email_server
Or via Compose:     docker compose up mcp-email
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("email-server", host="0.0.0.0", port=9002)


@mcp.tool(name="email.list_inbox")
async def list_inbox(user_id: str, max_results: int = 20) -> list[dict]:
    """List the user's most recent inbox messages."""
    # TODO: wire to app.integrations.google.gmail_client.list_messages(user_id, max_results)
    raise NotImplementedError("Gmail integration not wired up yet")


@mcp.tool(name="email.send")
async def send(
    user_id: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
) -> dict:
    """
    Send an email.

    NOTE: this is only ever invoked by app/agent/nodes/executor.py after a
    human has approved the action via the approval flow — this server has
    no independent notion of approval, it just sends.
    """
    # TODO: wire to app.integrations.google.gmail_client.send_message(...)
    raise NotImplementedError("Gmail integration not wired up yet")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")