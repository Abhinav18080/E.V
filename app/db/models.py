"""
SQLAlchemy models: User, UserSession, ApprovalRecord.

Note on Redis vs DB here: Redis stays the source of truth for hot-path,
short-lived state — the session-token -> user_id lookup on every request
(app/dependencies.py), the live pending-approvals queue
(app/api/routes/approvals.py), and raw conversation buffers
(app/agent/memory/short_term.py). These models are for data that should
survive a Redis flush and be queryable by SQL: the user record itself, a
durable login history, and a durable audit log of approval decisions.

Wiring: app/api/routes/auth.py creates/looks up a User row here on login
(replacing the throwaway uuid it used before this file existed).
app/api/routes/approvals.py's decide_approval() still hasn't been wired to
also write an ApprovalRecord row — that's flagged there as a TODO; the live
Redis entry it works against today already carries everything needed to.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    google_user_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    approval_records: Mapped[list["ApprovalRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """
    Durable login history. The hot-path lookup (mapping a session token to a
    user id on every request) stays in Redis — see SESSION_KEY_PREFIX in
    app/api/routes/auth.py and app/dependencies.py — for speed; this table
    is a queryable record of logins/revocations that survives a Redis flush.
    Stores a hash of the token, never the raw token itself.
    """

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")


class ApprovalRecord(Base):
    """
    Durable audit log of approval decisions. app/api/routes/approvals.py's
    live queue (Redis, with a TTL) is what the UI polls and decides against;
    this table is the permanent "what did the user actually approve, ever"
    history that outlives that TTL.
    """

    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(255), index=True)
    action_type: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # "approved" | "rejected"
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="approval_records")