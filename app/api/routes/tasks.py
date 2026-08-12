"""
Task/todo endpoints.

Unlike calendar/email, this doesn't depend on an external API, so it's fully
functional now: tasks are stored as JSON in a per-user Redis hash. This is
fine for a personal-scale project; if you outgrow it, move to app/db/models.py
(SQLAlchemy) without changing this router's public shape.
"""

import json
import uuid
from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import RedisDep, CurrentUserDep

router = APIRouter()


def _tasks_key(user_id: str) -> str:
    return f"tasks:{user_id}"


class TaskStatus(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: str | None = None
    due_date: datetime | None = None
    source: str | None = Field(
        default=None, description="Where this task came from, e.g. 'agent', 'email', 'manual'"
    )


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: datetime | None = None
    status: TaskStatus | None = None


class Task(BaseModel):
    id: str
    title: str
    description: str | None = None
    due_date: datetime | None = None
    status: TaskStatus = TaskStatus.todo
    source: str | None = None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[Task])
async def list_tasks(user_id: CurrentUserDep, redis_client: RedisDep) -> list[Task]:
    raw = await redis_client.hvals(_tasks_key(user_id))
    tasks = [Task(**json.loads(t)) for t in raw]
    return sorted(tasks, key=lambda t: t.created_at, reverse=True)


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(request: TaskCreate, user_id: CurrentUserDep, redis_client: RedisDep) -> Task:
    now = datetime.now(timezone.utc)
    task = Task(
        id=str(uuid.uuid4()),
        title=request.title,
        description=request.description,
        due_date=request.due_date,
        source=request.source,
        created_at=now,
        updated_at=now,
    )
    await redis_client.hset(_tasks_key(user_id), task.id, task.model_dump_json())
    return task


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: str, request: TaskUpdate, user_id: CurrentUserDep, redis_client: RedisDep
) -> Task:
    key = _tasks_key(user_id)
    raw = await redis_client.hget(key, task_id)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task = Task(**json.loads(raw))
    update_data = request.model_dump(exclude_unset=True)
    updated = task.model_copy(update={**update_data, "updated_at": datetime.now(timezone.utc)})

    await redis_client.hset(key, task_id, updated.model_dump_json())
    return updated


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, user_id: CurrentUserDep, redis_client: RedisDep) -> None:
    deleted = await redis_client.hdel(_tasks_key(user_id), task_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")