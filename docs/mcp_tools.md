# MCP Tools Reference

Every tool the agent can call is exposed by one of the servers in
`app/mcp/servers/`, each a standalone `FastMCP` app. `app/mcp/registry.py` maps a tool
name's `<domain>.<action>` prefix to the right server; `app/mcp/client.py` is what
actually calls it over streamable HTTP.

## Tool list

| Tool | Server | Port | Side-effecting? | Args |
|---|---|---|---|---|
| `calendar.list_events` | `calendar_server.py` | 9001 | No | `user_id`, `start`, `end` (ISO 8601) |
| `calendar.create_event` | `calendar_server.py` | 9001 | **Yes** | `user_id`, `summary`, `start`, `end`, `description?`, `attendees?` |
| `email.list_inbox` | `email_server.py` | 9002 | No | `user_id`, `max_results?` (default 20) |
| `email.send` | `email_server.py` | 9002 | **Yes** | `user_id`, `to`, `subject`, `body`, `cc?` |
| `tasks.list` | `tasks_server.py` | 9003 | No | `user_id` |
| `tasks.create` | `tasks_server.py` | 9003 | No | `user_id`, `title`, `description?`, `due_date?`, `source?` |
| `web_search.search` | `web_search_server.py` | 9004 | No | `query`, `max_results?` (default 5) |

"Side-effecting" tools are the ones that write to the real world (an actual email sent,
an actual calendar event created) — see [`approval_flow.md`](./approval_flow.md) for how
those get gated behind human approval before running. The list of which tools require
approval lives in `app/agent/nodes/executor.py`'s `SIDE_EFFECTING_TOOLS` set.

## Backing implementation

| Tool domain | Backed by | Free? |
|---|---|---|
| `calendar.*` | Google Calendar API (`app/integrations/google/calendar_client.py`) | Yes, free tier |
| `email.*` | Gmail API (`app/integrations/google/gmail_client.py`) | Yes, free tier |
| `tasks.*` | Redis directly — no external API | Yes, no limits |
| `web_search.*` | DuckDuckGo via the `ddgs` package | Yes, no API key |

`tasks.*` is the only domain with zero external dependency — it reads/writes the same
Redis keys (`tasks:{user_id}`) as the REST API in `app/api/routes/tasks.py`, so a task
created by the agent shows up via `GET /tasks` and vice versa.

## Auth requirements

`calendar.*` and `email.*` tools call `app.integrations.google.auth.get_credentials()`,
which raises `GoogleAuthError` if the user hasn't completed the OAuth flow
(`GET /auth/login`). That error crosses the wire as an `MCPToolError` in
`app/mcp/client.py` — callers should expect it and handle it gracefully (see
`app/workflows/daily_briefing.py`'s `_safe_call` for the pattern: catch broadly, degrade
to an empty result, don't take the whole caller down over one unavailable tool).

## Calling a tool

From application code, always go through the high-level `call()` — don't hardcode a
server URL:

```python
from app.mcp.client import call

result = await call("tasks.create", {"user_id": user_id, "title": "Book flights"})
```

`call()` resolves the server via `app.mcp.registry.get_server_url()`, so it stays correct
even if a server's port changes (update `MCP_*_SERVER_URL` in `.env`, nothing else).

## Running the servers

- All four via Docker Compose: `docker compose up mcp-calendar mcp-email mcp-tasks mcp-web-search`
- All four locally without Docker: `make mcp-all` (or `./scripts/run_local_mcp_servers.sh`)
- One at a time for local dev: `make mcp-calendar`, `make mcp-email`, `make mcp-tasks`, or
  `python -m app.mcp.servers.web_search_server` directly

## Adding a new tool

1. Add the function to the relevant server in `app/mcp/servers/`, decorated with
   `@mcp.tool(name="domain.action")`. FastMCP infers the input schema from the function's
   type hints.
2. If it's a new domain (a new server file), register its URL in `app/config.py`
   (`Settings`), `.env.example`, and `app/mcp/registry.py`'s `DOMAIN_TO_SETTINGS_ATTR`.
3. Add it to `AVAILABLE_TOOLS` in `app/agent/prompts/planner_prompt.py` so the planner
   knows it exists, and to `TOOL_ARG_SCHEMAS` in
   `app/agent/prompts/tool_use_prompt.py` so the planner knows its argument shape.
4. If it writes real-world data (sends something, creates something, deletes something),
   add its name to `SIDE_EFFECTING_TOOLS` in `app/agent/nodes/executor.py` so it's gated
   behind human approval — see [`approval_flow.md`](./approval_flow.md).

Longer term, step 3 can be replaced by `app.mcp.registry.discover_tools()`, which already
queries each running server for its actual tool list — `planner.py` currently uses the
static list instead since that's simpler while there are only a handful of tools.