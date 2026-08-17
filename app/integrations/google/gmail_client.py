"""
Gmail API client — used by app/mcp/servers/email_server.py.

Same offline-discovery and asyncio.to_thread notes as calendar_client.py
apply here.
"""

import asyncio
import base64
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build

from app.integrations.google.auth import get_credentials


async def list_messages(user_id: str, max_results: int = 20) -> list[dict[str, Any]]:
    """List the user's most recent inbox messages (metadata only, not full body)."""
    credentials = await get_credentials(user_id)
    service = build("gmail", "v1", credentials=credentials, static_discovery=True)

    list_result = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .list(userId="me", maxResults=max_results, labelIds=["INBOX"])
        .execute()
    )

    summaries = []
    for msg_ref in list_result.get("messages", []):
        msg = await asyncio.to_thread(
            lambda mid=msg_ref["id"]: service.users()
            .messages()
            .get(userId="me", id=mid, format="metadata", metadataHeaders=["Subject", "From"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        summaries.append(
            {
                "id": msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "sender": headers.get("From", "(unknown sender)"),
                "snippet": msg.get("snippet", ""),
                "unread": "UNREAD" in msg.get("labelIds", []),
            }
        )
    return summaries


async def send_message(
    user_id: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
) -> dict[str, Any]:
    """
    Send an email from the user's Gmail account.

    NOTE: callers (app/mcp/servers/email_server.py, invoked in turn by
    app/agent/nodes/executor.py) are responsible for only calling this after
    human approval — this function has no notion of approval itself.
    """
    credentials = await get_credentials(user_id)
    service = build("gmail", "v1", credentials=credentials, static_discovery=True)

    message = MIMEText(body)
    message["to"] = ", ".join(to)
    message["subject"] = subject
    if cc:
        message["cc"] = ", ".join(cc)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    sent = await asyncio.to_thread(
        lambda: service.users().messages().send(userId="me", body={"raw": raw}).execute()
    )

    return {"message_id": sent["id"], "status": "sent"}