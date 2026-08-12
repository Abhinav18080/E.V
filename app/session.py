"""
SQLAlchemy engine/session setup.

Full models (User, ApprovalRequest, TaskRecord, etc.) live in app/db/models.py,
which we'll add when we build out approvals + task coordination. This module
only owns the connection plumbing.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# check_same_thread is only needed for SQLite; harmless to set generically here
# since we default to sqlite for local dev.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency — yields a DB session and guarantees it's closed
    after the request, even if an exception is raised.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()