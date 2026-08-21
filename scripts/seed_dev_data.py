"""
Seed dev environment with sample data — a dev User row, a few tasks, a
pending approval, and a sample conversation thread — so `make dev` gives
you something to look at immediately instead of an empty app.

Safe to re-run: the dev User row is only created once (subsequent runs
skip it), but tasks/approvals/threads get fresh ids each run, so re-running
adds more sample data rather than erroring.

Usage:
    python scripts/seed_dev_data.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

# So `import app...` works regardless of the working directory this is run
# from — this file lives at scripts/, so go up one level to the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.agent.memory.short_term import append_message, clear_thread  # noqa: E402
from app.api.routes.approvals import create_pending_approval  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.dependencies import DEV_USER_ID  # noqa: E402
from app.mcp.servers.tasks_server import create_task  # noqa: E402
from app.redis_client import get_redis_client  # noqa: E402

DEV_USER_EMAIL = "dev@example.com"


def seed_db_user() -> None:
    """
    Create the dev user row if it doesn't already exist.

    create_all() is here too so this script works standalone even before
    you've run `make migrate` — it only creates tables that don't exist yet,
    so it won't conflict with Alembic-managed schema if migrations have
    already run.
    """
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        existing = db.get(User, DEV_USER_ID)
        if existing:
            print(f"User '{DEV_USER_ID}' already exists, skipping.")
            return
        db.add(User(id=DEV_USER_ID, email=DEV_USER_EMAIL, display_name="Dev User"))
        db.commit()
        print(f"Created User row for '{DEV_USER_ID}' ({DEV_USER_EMAIL}).")


async def seed_tasks() -> None:
    sample_tasks = [
        ("Book flights to Kyoto", "Window seat if possible", "agent"),
        ("Renew passport", "Expires in 4 months", "manual"),
        ("Reply to Alex about dinner plans", None, "email"),
    ]
    for title, description, source in sample_tasks:
        task = await create_task(DEV_USER_ID, title=title, description=description, source=source)
        print(f"Created task: {task['title']} ({task['id']})")


async def seed_pending_approval() -> None:
    redis_client = get_redis_client()
    thread_id = f"seed-{uuid.uuid4()}"
    approval = await create_pending_approval(
        redis_client=redis_client,
        user_id=DEV_USER_ID,
        thread_id=thread_id,
        action_type="email.send",
        summary="Send trip itinerary to friend@example.com",
        payload={
            "to": ["friend@example.com"],
            "subject": "Kyoto trip itinerary",
            "body": "Here's the plan for our trip...",
        },
    )
    print(f"Created pending approval: {approval.id} ({approval.summary})")


async def seed_conversation_thread() -> None:
    thread_id = f"seed-thread-{uuid.uuid4()}"
    await clear_thread(thread_id)
    await append_message(thread_id, HumanMessage(content="Can you help me plan a trip to Kyoto?"))
    await append_message(thread_id, AIMessage(content="Sure! How many days are you thinking, and when?"))
    await append_message(thread_id, HumanMessage(content="5 days in October"))
    print(f"Seeded conversation thread: {thread_id}")


async def main() -> None:
    print(f"Seeding dev data for user_id='{DEV_USER_ID}'...\n")
    seed_db_user()
    await seed_tasks()
    await seed_pending_approval()
    await seed_conversation_thread()
    print("\nDone. Try: GET /tasks, GET /approvals — both work against the dev-mode auth fallback.")


if __name__ == "__main__":
    asyncio.run(main())