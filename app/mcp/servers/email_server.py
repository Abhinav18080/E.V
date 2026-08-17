"""
MCP server exposing Gmail tools.

Run directly:      python -m app.mcp.servers.email_server
Or via Compose:     docker compose up mcp-email
"""

from mcp.server.fastmcp import FastMCP

from app.integrations.google import gmail_client

mcp = FastMCP("email-server", host="0.0.0.0", port=9002)


@mcp.tool(name="email.list_inbox")
async def list_inbox(user_id: str, max_results: int = 20) -> list[dict]:
    """List the user's most recent inbox messages."""
    return await gmail_client.list_messages(user_id, max_results)


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
    return await gmail_client.send_message(user_id, to, subject, body, cc)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")