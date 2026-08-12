"""
Shared FastAPI dependencies: DB session, Redis client, and auth.

This is a single-user personal assistant, so auth is intentionally simple:
a session token (issued after the Google OAuth flow completes) is stored in
Redis and passed back as a bearer token or cookie. There's no multi-tenant
user table wired up yet — get_current_user_id() returns a stable dev user id
until app/db/models.py + app/api/routes/auth.py are built out.
"""

from collections.abc import Generator
from typing import Annotated

import redis.asyncio as redis
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db as _get_db
from app.redis_client import get_redis_client

SESSION_KEY_PREFIX = "session:"
DEV_USER_ID = "dev-user"


# --- Config ---
def get_config() -> Settings:
    return get_settings()


ConfigDep = Annotated[Settings, Depends(get_config)]


# --- Database ---
def get_db() -> Generator[Session, None, None]:
    yield from _get_db()


DbDep = Annotated[Session, Depends(get_db)]


# --- Redis ---
def get_redis() -> redis.Redis:
    return get_redis_client()


RedisDep = Annotated[redis.Redis, Depends(get_redis)]


# --- Auth ---
async def get_current_user_id(
    redis_client: RedisDep,
    settings: ConfigDep,
    session_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """
    Resolves the current user from either a session cookie or an
    `Authorization: Bearer <token>` header. Falls back to a fixed dev user
    in development so you're not forced through OAuth on every local run.

    TODO: once app/api/routes/auth.py implements the Google OAuth callback,
    it should write `session:{token} -> user_id` into Redis with a TTL, and
    this function's dev fallback should be gated behind `settings.is_production
    is False` only (already is) — leave that check in place for safety.
    """
    token = session_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        if not settings.is_production:
            return DEV_USER_ID
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = await redis_client.get(f"{SESSION_KEY_PREFIX}{token}")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    return user_id


CurrentUserDep = Annotated[str, Depends(get_current_user_id)]