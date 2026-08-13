"""
MCP server exposing task/todo tools.

Unlike calendar/email, this doesn't depend on an external API — it's fully
functional, reading/writing the same Redis-backed store as the REST API
(app/api/routes/tasks.py), keyed the same way ("tasks:{user_id}") so a task
created by the agent shows up via GET /tasks and vice versa.

Run directly:      python -m app.mcp.servers.tasks_server
Or via Compose:     docker compose up mcp-tasks
"""

import json
import uuid
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from app.redis_client import get_redis_client

mcp = FastMCP("tasks-server", host="0.0.0.0", port=9003)


def _tasks_key(user_id: str) -> str:
    return f"tasks:{user_id}"


@mcp.tool(name="tasks.list")
async def list_tasks(user_id: str) -> list[dict]:
    """List all of the user's tasks, most recently created first."""
    redis_client = get_redis_client()
    raw = await redis_client.hvals(_tasks_key(user_id))
    tasks = [json.loads(t) for t in raw]
    return sorted(tasks, key=lambda t: t["created_at"], reverse=True)


@mcp.tool(name="tasks.create")
async def create_task(
    user_id: str,
    title: str,
    description: str | None = None,
    due_date: str | None = None,
    source: str = "agent",
) -> dict:
    """Create a task/todo item for the user. `due_date`, if given, should be ISO 8601."""
    redis_client = get_redis_client()
    now = datetime.now(timezone.utc).isoformat()
    task = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "due_date": due_date,
        "status": "todo",
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    await redis_client.hset(_tasks_key(user_id), task["id"], json.dumps(task))
    return task


if __name__ == "__main__":
    mcp.run(transport="streamable-http")