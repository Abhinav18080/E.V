# Architecture

## Overview

The assistant is a FastAPI app fronting a [LangGraph](https://langchain-ai.github.io/langgraph/)
state machine. The graph is the agent's "brain" — it decides whether to answer directly,
call a tool, or pause for human approval. Tools themselves aren't called directly by the
graph; they're exposed as [MCP](https://modelcontextprotocol.io) servers, one per domain
(calendar, email, tasks, web search), and the graph talks to them over MCP like any other
MCP client would.

```
┌─────────────┐      ┌──────────────────┐      ┌────────────────────┐
│   FastAPI    │─────▶│   Agent Graph     │─────▶│   MCP Servers       │
│ (app/api/)   │      │ (app/agent/)      │      │ (app/mcp/servers/)  │
└─────────────┘      └──────────────────┘      └────────────────────┘
       │                      │                          │
       │                      │                          ▼
       │                      │                 ┌────────────────────┐
       │                      │                 │  Google APIs /      │
       │                      │                 │  Redis (tasks) /    │
       │                      │                 │  DuckDuckGo         │
       │                      │                 │ (app/integrations/) │
       │                      ▼                          
       │             ┌──────────────────┐
       └────────────▶│  Redis + SQLite   │
                      │ (state, cache,    │
                      │  durable records) │
                      └──────────────────┘
```

## Layers

### `app/api/` — HTTP surface
FastAPI routes and Pydantic schemas. Routes are thin: they validate input, call into the
agent graph or MCP tools, and shape the response. `chat.py` is the main entrypoint —
everything else (`calendar.py`, `email.py`, `tasks.py`) is a direct REST alternative for a
future frontend that wants to render data without going through the conversational agent.

### `app/agent/` — the LangGraph state machine
- **`state.py`** — `AgentState`, the TypedDict that flows through every node.
- **`graph.py`** — wires the nodes together and owns compilation (`get_agent_graph()`) and
  turn-taking (`start_turn()`, `resume_with_decision()`).
- **`nodes/`** — `planner` (decide what to do) → `executor` (do it, via MCP) →
  `approval_gate` (pause for side-effecting actions) → `responder` (reply). See
  [`approval_flow.md`](./approval_flow.md) for the full walkthrough of that loop.
- **`prompts/`** — prompt text, kept separate from node logic.
- **`memory/`** — `short_term.py` (Redis conversation buffer), `long_term.py` (Chroma
  vector store for durable facts/preferences), `summarizer.py` (rolling summary for long
  threads).

### `app/mcp/` — tool servers and the client that calls them
Each server in `app/mcp/servers/` is a standalone `FastMCP` app exposing a small set of
tools over streamable HTTP. `app/mcp/client.py` is what the agent's `executor` node uses
to call them; `app/mcp/registry.py` maps a tool name's `<domain>.<action>` prefix to the
right server URL and supports dynamic tool discovery. See
[`mcp_tools.md`](./mcp_tools.md) for the full tool list.

Running each server as its own process (rather than importing tool logic directly into
the agent) means they can be deployed, scaled, or swapped independently, and it's what
lets `app/agent/nodes/executor.py` stay provider-agnostic — it doesn't know or care
whether `calendar.create_event` is backed by Google Calendar or something else, as long
as an MCP server answers to that name.

### `app/integrations/` — the actual external-API wrappers
- **`google/`** — OAuth credential loading/refresh (`auth.py`, distinct from the
  interactive login flow in `app/api/routes/auth.py`) and thin API clients
  (`calendar_client.py`, `gmail_client.py`, `drive_client.py`). MCP servers call these;
  nothing else should.
- **`llm/`** — `provider.py` returns a configured LangChain chat model based on
  `LLM_PROVIDER` (ollama/groq/gemini), so nodes never construct a model directly.

### `app/workflows/` — higher-level flows built on the graph
Multi-step processes that compose the pieces above rather than duplicating them:
- **`trip_planner.py`** — research (read-only) and itinerary drafting happen directly;
  turning a day into a real calendar event is delegated back to `start_turn()` so it goes
  through the same approval flow as any chat message.
- **`daily_briefing.py`** — pulls calendar/email/tasks together into one summary.
- **`task_coordinator.py`** — cross-tool sync (actionable emails → tasks, upcoming
  events → prep tasks), idempotent via a Redis-tracked set of processed IDs.

### `app/db/` — durable, queryable records
SQLAlchemy models (`User`, `UserSession`, `ApprovalRecord`) for data that should survive
a Redis flush and be queryable by SQL. **Redis remains the source of truth for hot-path
state** — session-token lookups, the live pending-approvals queue, raw conversation
buffers — these tables are the durable/audit layer underneath, not a replacement.
Alembic migrations live in `app/db/migrations/`.

### `app/utils/` — cross-cutting concerns
`logging.py` (structured logging setup), `retry.py` (tenacity presets scoped to what
each integration actually raises), `rate_limit.py` (Redis fixed-window limiter, usable
as a FastAPI dependency or called directly).

## Data stores and what lives where

| Store | Holds | Why |
|---|---|---|
| Redis | Session tokens, Google OAuth tokens, conversation buffers, thread summaries, pending approvals, rate-limit counters, tasks | Hot path — everything here is read/written on nearly every request |
| SQLite/Postgres (via SQLAlchemy) | `User`, `UserSession`, `ApprovalRecord` | Durable, queryable, survives a Redis flush |
| Chroma (local, embedded) | Long-term memory facts/preferences | Semantic search over durable user context |

## Why MCP instead of calling tools directly

It would be simpler, in the short term, for `executor.py` to just import
`calendar_client.list_events` and call it. Going through MCP instead means:
- Tools are discoverable at runtime (`app/mcp/registry.py`'s `discover_tools()`) rather
  than hardcoded into the planner's prompt.
- Each tool domain can be deployed/restarted independently — `docker-compose.yml` runs
  each server as its own container.
- The agent's tool-calling code is identical whether a tool happens to be backed by
  Google's API, Redis, or DuckDuckGo — see `app/mcp/client.py`'s `call()`.

## Free-tier stack

Every piece of this runs without a paid API: Llama 3.1 8B via local Ollama (swappable to
Groq/Gemini's free tiers via `LLM_PROVIDER`), Redis via Docker, Chroma embedded locally,
DuckDuckGo search via `ddgs` (no key), and Google Calendar/Gmail's free API tier. See the
stack table in the project README for the full breakdown.