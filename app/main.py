"""
FastAPI entrypoint.

Route modules (app/api/routes/*) are wired in as they're built. For now this
exposes a health check that verifies Redis connectivity, plus app-level
config: CORS, lifespan startup/shutdown, and logging setup.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.redis_client import ping as redis_ping

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up (env=%s, llm_provider=%s)", settings.app_env, settings.llm_provider)
    if not await redis_ping():
        logger.warning("Redis is not reachable at startup — check `make up` / REDIS_URL")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="AI Personal Assistant",
    description="Agentic assistant for trip planning, calendar, email, and task coordination.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    redis_ok = await redis_ping()
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "env": settings.app_env,
        "llm_provider": settings.llm_provider,
    }


# --- Routers ---
# chat/calendar/email return 501 until their underlying integrations
# (agent graph, Google clients) are built — see TODOs in each route module.
from app.api.routes import approvals, auth, calendar, chat, email, tasks

app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
app.include_router(email.router, prefix="/email", tags=["email"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])