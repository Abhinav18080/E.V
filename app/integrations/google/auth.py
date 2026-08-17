"""
Google OAuth2 credential loading + refresh.

Distinct from app/api/routes/auth.py, which handles the interactive HTTP
OAuth login/callback flow. This module is the read side: given a user_id,
produce valid (refreshed if necessary) credentials for calendar_client.py /
gmail_client.py / drive_client.py to use, reading the token that
routes/auth.py stored in Redis after login and writing back any refresh.
"""

import asyncio
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.redis_client import get_redis_client

GOOGLE_TOKENS_KEY_PREFIX = "google_tokens:"


class GoogleAuthError(Exception):
    """Raised when a user has no stored Google credentials (needs to log in)."""


def _tokens_key(user_id: str) -> str:
    return f"{GOOGLE_TOKENS_KEY_PREFIX}{user_id}"


async def get_credentials(user_id: str) -> Credentials:
    """
    Load this user's Google credentials, refreshing the access token first
    if it's expired. Raises GoogleAuthError if the user hasn't completed the
    OAuth flow yet (see GET /auth/login in app/api/routes/auth.py).
    """
    redis_client = get_redis_client()
    raw = await redis_client.get(_tokens_key(user_id))
    if not raw:
        raise GoogleAuthError(
            f"No Google credentials stored for user '{user_id}' — they need to "
            "complete the OAuth flow via GET /auth/login first."
        )

    credentials = Credentials.from_authorized_user_info(json.loads(raw))

    if credentials.expired and credentials.refresh_token:
        # credentials.refresh() is a blocking network call — run it off the
        # event loop rather than stalling every other in-flight request.
        await asyncio.to_thread(credentials.refresh, Request())
        await redis_client.set(_tokens_key(user_id), credentials.to_json())

    return credentials