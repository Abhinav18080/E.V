# AI Personal Assistant

An agentic personal assistant that plans trips, manages your calendar, sends emails, and
coordinates tasks across multiple tools — built entirely on a free, local-first stack.

## What it does
- Plans multi-step trips (research → itinerary → calendar events)
- Reads/writes your Google Calendar
- Drafts and sends email via Gmail
- Tracks and coordinates tasks across tools
- Pauses for **human approval** before any side-effecting action (sending email, creating
  calendar events, booking anything)
- Remembers context across sessions (short-term via Redis, long-term via a local vector store)

## What you'll learn
- **MCP** — exposing tools (calendar, email, tasks) as MCP servers the agent can call
- **Tool orchestration** — routing between tools via a LangGraph state machine
- **Memory** — short-term conversation buffers + long-term semantic memory
- **Human approval** — interrupting a running graph and resuming after user confirmation
- **Stateful workflows** — multi-turn, multi-step flows that persist across requests

## Tech stack (100% free tier)
| Layer | Tool |
|---|---|
| LLM | Llama 3.1 8B via [Ollama](https://ollama.com) (local, free) |
| Orchestration | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| Tool protocol | [MCP](https://modelcontextprotocol.io) |
| Calendar/Email | Google Calendar API + Gmail API (free tier) |
| Backend | FastAPI |
| State/cache | Redis (local Docker) |
| Long-term memory | Chroma (local, embedded) |

## Getting started

### 1. Prerequisites
- Python 3.11+
- Docker + Docker Compose
- [Ollama](https://ollama.com/download) installed locally
- A Google Cloud project with Calendar API + Gmail API enabled, and OAuth client credentials

### 2. Pull the model
```bash
ollama pull llama3.1:8b
```

### 3. Set up environment
```bash
cp .env.example .env
# fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
```

### 4. Install dependencies
```bash
make install
```

### 5. Start supporting services (Redis, Chroma)
```bash
make up
```

### 6. Run the app
```bash
make dev
```

The API will be available at `http://localhost:8000`. Interactive docs at
`http://localhost:8000/docs`.

## Project structure
See `docs/architecture.md` for the full breakdown of `app/agent`, `app/mcp`,
`app/integrations`, and `app/workflows`.

## Human-in-the-loop approvals
Any action the agent classifies as side-effecting (sending an email, creating a calendar
event, etc.) triggers a LangGraph interrupt. The pending action is stored in Redis and
surfaced via `GET /approvals`; you approve or reject via `POST /approvals/{id}/decision`,
which resumes the graph from where it paused.

## Running tests
```bash
make test
```