"""
Google OAuth flow.

GET /auth/login   -> redirects the user to Google's consent screen
GET /auth/callback -> exchanges the auth code for tokens, creates a session,
                       and sets the session cookie that app.dependencies
                       reads to resolve the current user.

Google API tokens (access + refresh) are stored server-side (Redis for now,
keyed by user_id) so app.integrations.google.* clients can use them later
without the user re-authenticating on every request.
"""

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from app.config import get_settings
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

    # TODO: once app/db/models.py has a User table, look up/create the user
    # by their Google profile (fetch via `credentials` + googleapiclient) and
    # use its real id here instead of minting a bare uuid each login.
    user_id = str(uuid.uuid4())

    await redis_client.set(
        f"{GOOGLE_TOKENS_KEY_PREFIX}{user_id}",
        credentials.to_json(),
    )

    session_token = secrets.token_urlsafe(32)
    await redis_client.set(
        f"{SESSION_KEY_PREFIX}{session_token}", user_id, ex=SESSION_TTL_SECONDS
    )

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
        "authenticated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/logout")
async def logout(request: Request, response: Response, redis_client: RedisDep) -> dict:
    token = request.cookies.get("session_token")
    if token:
        await redis_client.delete(f"{SESSION_KEY_PREFIX}{token}")
    response.delete_cookie("session_token")
    return {"status": "logged_out"}