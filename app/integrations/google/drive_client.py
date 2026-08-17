"""
Google Drive client — optional.

Not wired into any MCP server yet (there's no "drive.*" entry in
AVAILABLE_TOOLS in app/agent/prompts/planner_prompt.py, and no
app/mcp/servers/drive_server.py). Included since the project structure
calls for it, and it's a natural next step if you want the agent to read
trip documents, packing lists, itineraries, etc. from the user's Drive —
add a drive_server.py MCP server that calls into this module, then add
"drive.list_files" / "drive.read_file" to AVAILABLE_TOOLS.
"""

import asyncio
from typing import Any

from googleapiclient.discovery import build

from app.integrations.google.auth import get_credentials


async def list_files(user_id: str, query: str | None = None, max_results: int = 20) -> list[dict[str, Any]]:
    """List files in the user's Drive, optionally filtered by a Drive API query string."""
    credentials = await get_credentials(user_id)
    service = build("drive", "v3", credentials=credentials, static_discovery=True)

    result = await asyncio.to_thread(
        lambda: service.files()
        .list(q=query, pageSize=max_results, fields="files(id, name, mimeType, webViewLink)")
        .execute()
    )
    return result.get("files", [])


async def read_file_text(user_id: str, file_id: str) -> str:
    """Read a Google Doc's plain-text content by exporting it as text/plain."""
    credentials = await get_credentials(user_id)
    service = build("drive", "v3", credentials=credentials, static_discovery=True)

    content = await asyncio.to_thread(
        lambda: service.files().export(fileId=file_id, mimeType="text/plain").execute()
    )
    return content.decode() if isinstance(content, bytes) else content