"""
MCP server exposing a web search tool.

Fully functional and free: uses the `ddgs` package (DuckDuckGo search, no
API key required) rather than a paid search API. Useful for trip-planning
research — "what's the best time of year to visit Kyoto" etc.

Run directly:      python -m app.mcp.servers.web_search_server
Or via Compose:     docker compose up mcp-web-search
"""

from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web-search-server", host="0.0.0.0", port=9004)


@mcp.tool(name="web_search.search")
async def search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web and return the top results as {title, url, snippet}."""
    with DDGS() as ddgs:
        raw_results = list(ddgs.text(query, max_results=max_results))

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
        }
        for r in raw_results
    ]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")