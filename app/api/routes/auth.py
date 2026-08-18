"""
Google OAuth flow.

GET /auth/login   -> redirects the user to Google's consent screen
GET /auth/callback -> exchanges the auth code for tokens, looks up/creates
                       the User row, creates a session, and sets the
                       session cookie that app.dependencies reads to
                       resolve the current user.

Google API tokens (access + refresh) are stored server-side (Redis for now,
keyed by user_id) so app.integrations.google.* clients can use them later
without the user re-authenticating on every request. The User record itself
lives in the DB (app/db/models.py) — Redis holds the hot-path session-token
lookup and the tokens, not the durable identity.
"""

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import get_settings
from app.db.models import User, UserSession
from app.db.session import SessionLocal
from app.dependencies import RedisDep

router = APIRouter()

SESSION_KEY_PREFIX = "session:"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days
GOOGLE_TOKENS_KEY_PREFIX = "google_tokens:"
OAUTH_STATE_KEY_PREFIX = "oauth_state:"
OAUTH_STATE_TTL_SECONDS = 60 * 10  # 10 minutes


def _build_flow() -> Flow:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set — see .env.example",
        )
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=settings.google_scopes_list,
        redirect_uri=settings.google_redirect_uri,
    )


def _get_or_create_user(email: str, google_user_id: str, display_name: str | None) -> User:
    """
    Look up the User by google_user_id (falling back to email, in case a
    user's Google account id ever changes but their email doesn't), or
    create one. Synchronous — SQLAlchemy's Session isn't async here, so
    callers run this via asyncio.to_thread rather than blocking the event
    loop directly.
    """
    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter((User.google_user_id == google_user_id) | (User.email == email))
            .first()
        )
        if user:
            # Keep google_user_id/display_name current in case either changed.
            user.google_user_id = google_user_id
            user.display_name = display_name
            db.commit()
            db.refresh(user)
            return user

        user = User(email=email, google_user_id=google_user_id, display_name=display_name)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _record_session(user_id: str, session_token: str, expires_at: datetime) -> None:
    """Durable login-history row — see UserSession's docstring in app/db/models.py."""
    with SessionLocal() as db:
        db.add(
            UserSession(
                user_id=user_id,
                session_token_hash=hashlib.sha256(session_token.encode()).hexdigest(),
                expires_at=expires_at,
            )
        )
        db.commit()


@router.get("/login")
async def login(redis_client: RedisDep) -> RedirectResponse:
    flow = _build_flow()
    state = secrets.token_urlsafe(24)
    auth_url, _ = flow.authorization_url(
        access_type="offline",       # request a refresh token
        include_granted_scopes="true",
        prompt="consent",            # ensures a refresh token on repeat logins too
        state=state,
    )
    # Bind this state to the OAuth attempt so /callback can reject CSRF/replay
    await redis_client.set(f"{OAUTH_STATE_KEY_PREFIX}{state}", "1", ex=OAUTH_STATE_TTL_SECONDS)
    return RedirectResponse(auth_url)


@router.get("/callback")
async def callback(request: Request, response: Response, redis_client: RedisDep) -> dict:
    state = request.query_params.get("state")
    if not state or not await redis_client.get(f"{OAUTH_STATE_KEY_PREFIX}{state}"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")
    await redis_client.delete(f"{OAUTH_STATE_KEY_PREFIX}{state}")

    flow = _build_flow()
    flow.fetch_token(authorization_response=str(request.url))
    credentials = flow.credentials

    # Fetch the user's Google profile (needs the userinfo.email/profile
    # scopes added in app/config.py's GOOGLE_SCOPES) so we can look up/create
    # a real User row instead of minting a throwaway id each login.
    userinfo_service = build("oauth2", "v2", credentials=credentials, static_discovery=True)
    profile = await asyncio.to_thread(lambda: userinfo_service.userinfo().get().execute())

    user = await asyncio.to_thread(
        _get_or_create_user, profile["email"], profile["id"], profile.get("name")
    )
    user_id = user.id

    await redis_client.set(
        f"{GOOGLE_TOKENS_KEY_PREFIX}{user_id}",
        credentials.to_json(),
    )

    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)
    await redis_client.set(
        f"{SESSION_KEY_PREFIX}{session_token}", user_id, ex=SESSION_TTL_SECONDS
    )
    await asyncio.to_thread(_record_session, user_id, session_token, expires_at)

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
    )
    return {
        "status": "authenticated",
        "user_id": user_id,
        "email": user.email,
        "authenticated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/logout")
async def logout(request: Request, response: Response, redis_client: RedisDep) -> dict:
    token = request.cookies.get("session_token")
    if token:
        await redis_client.delete(f"{SESSION_KEY_PREFIX}{token}")
    response.delete_cookie("session_token")
    return {"status": "logged_out"}