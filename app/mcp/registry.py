"""
Tool/server registration and discovery.

Tool names follow a `<domain>.<action>` convention (e.g. "calendar.list_events"),
where the domain prefix maps to one of the MCP servers under app/mcp/servers/.
This module owns that mapping, plus dynamic discovery (asking each server what
tools it actually exposes, rather than trusting a hardcoded list).
"""

from dataclasses import dataclass

from app.config import get_settings
from app.mcp.client import list_tools

# Maps a tool name's domain prefix to the settings attribute holding that
# server's URL. Add an entry here whenever a new server is added under
# app/mcp/servers/.
DOMAIN_TO_SETTINGS_ATTR = {
    "calendar": "mcp_calendar_server_url",
    "email": "mcp_email_server_url",
    "tasks": "mcp_tasks_server_url",
    "web_search": "mcp_web_search_server_url",
}


class UnknownToolDomainError(ValueError):
    pass


def get_server_url(tool_name: str) -> str:
    """
    Resolve a tool name like "calendar.create_event" to its server's base URL.
    Raises UnknownToolDomainError if the domain prefix isn't registered.
    """
    domain = tool_name.split(".", 1)[0]
    attr = DOMAIN_TO_SETTINGS_ATTR.get(domain)
    if not attr:
        raise UnknownToolDomainError(
            f"No MCP server registered for domain '{domain}' (tool: {tool_name})"
        )
    return getattr(get_settings(), attr)


@dataclass
class DiscoveredTool:
    name: str
    description: str | None
    input_schema: dict


async def discover_tools() -> dict[str, list[DiscoveredTool]]:
    """
    Ask every registered MCP server what tools it currently exposes. This is
    the dynamic alternative to the hardcoded AVAILABLE_TOOLS list in
    app/agent/prompts/planner_prompt.py — planner.py can call this instead
    once it's ready to build its tool list at request time rather than from
    a static snapshot.

    Servers that are down are skipped (with an empty list) rather than
    failing the whole discovery call, since a personal-scale deployment may
    not have every server running at all times.
    """
    settings = get_settings()
    results: dict[str, list[DiscoveredTool]] = {}

    for domain, attr in DOMAIN_TO_SETTINGS_ATTR.items():
        server_url = getattr(settings, attr)
        try:
            tools = await list_tools(server_url)
        except Exception:
            # TODO: log this once app/utils/logging.py exists — swallowing
            # entirely is fine for now so one down server doesn't break
            # discovery for the rest.
            tools = []
        results[domain] = [
            DiscoveredTool(name=t.name, description=t.description, input_schema=t.inputSchema)
            for t in tools
        ]

    return results