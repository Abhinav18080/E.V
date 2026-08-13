"""
MCP client wrapper used by the agent.

Two levels of API:
  - list_tools(server_url) / call_tool(server_url, ...): thin wrappers around
    a single MCP server, given its URL directly.
  - call(tool_name, arguments): the one app/agent/nodes/executor.py should
    use — resolves the right server via app.mcp.registry, then calls it.

Every call opens a fresh streamable-HTTP connection and closes it when done.
That's simpler and safer for a personal-scale project than pooling
persistent sessions per server, at the cost of a bit of per-call latency —
fine to revisit if that ever matters.
"""

import json
from typing import Any

import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPToolError(Exception):
    """Raised when an MCP tool call returns an error result."""


async def list_tools(server_url: str) -> list[types.Tool]:
    async with streamablehttp_client(f"{server_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def call_tool(server_url: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """
    Call a tool on a specific server and return its content, unwrapped.
    Raises MCPToolError if the server reports the call as an error.
    """
    async with streamablehttp_client(f"{server_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    # Deliberately raise/return *after* the context managers above have
    # exited cleanly, not inside them — raising inside nested anyio-backed
    # `async with` blocks gets wrapped in an ExceptionGroup during their
    # __aexit__ cleanup, which breaks a plain `except MCPToolError` at the
    # call site.
    if result.isError:
        message = _extract_text(result.content) or "Tool call failed with no error detail"
        raise MCPToolError(f"{tool_name}: {message}")

    # structuredContent is set when the tool's return type let FastMCP
    # infer an output schema; otherwise fall back to the text content
    # block, parsing it as JSON when possible so callers get the same
    # dict/list shape either way rather than having to handle both.
    if result.structuredContent is not None:
        return result.structuredContent

    text = _extract_text(result.content)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


async def call(tool_name: str, arguments: dict[str, Any]) -> Any:
    """
    High-level entrypoint — resolves the right server for `tool_name` via
    app.mcp.registry, then calls it there. This is what
    app/agent/nodes/executor.py should call instead of using
    server-specific URLs directly.
    """
    from app.mcp.registry import get_server_url  # local import avoids a circular import

    server_url = get_server_url(tool_name)
    return await call_tool(server_url, tool_name, arguments)


def _extract_text(content: list) -> str | None:
    """MCP tool results return a list of content blocks; join any text ones."""
    texts = [block.text for block in content if isinstance(block, types.TextContent)]
    return "\n".join(texts) if texts else None