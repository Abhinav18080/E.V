"""
Unit tests for the MCP server tool functions in app/mcp/servers/*.py.

FastMCP's @mcp.tool() decorator returns the original function unchanged, so
these call the tool functions directly (in-process, no network, no
subprocess) rather than going over the wire — that's what the integration
tests in tests/integration/ are for. This file tests each server's own
logic: tasks_server's real Redis-backed CRUD, calendar/email_server's error
propagation and happy-path behavior with the Google client mocked out, and
web_search_server's result shaping with DDGS mocked out.
"""

from unittest.mock import MagicMock, patch

import pytest

import app.mcp.servers.calendar_server as calendar_server
import app.mcp.servers.email_server as email_server
import app.mcp.servers.tasks_server as tasks_server
import app.mcp.servers.web_search_server as web_search_server
from app.integrations.google.auth import GoogleAuthError


class TestTasksServer:
    async def test_create_and_list_round_trip(self, redis_client):
        user_id = "pytest:mcp-tasks-user"
        await redis_client.delete(tasks_server._tasks_key(user_id))

        created = await tasks_server.create_task(user_id, title="Book flights", description="To Kyoto")
        assert created["title"] == "Book flights"
        assert created["status"] == "todo"

        tasks = await tasks_server.list_tasks(user_id)
        assert len(tasks) == 1
        assert tasks[0]["id"] == created["id"]

    async def test_list_is_scoped_per_user(self, redis_client):
        user_a, user_b = "pytest:mcp-tasks-a", "pytest:mcp-tasks-b"
        await redis_client.delete(tasks_server._tasks_key(user_a))
        await redis_client.delete(tasks_server._tasks_key(user_b))

        await tasks_server.create_task(user_a, title="User A's task")

        assert len(await tasks_server.list_tasks(user_a)) == 1
        assert len(await tasks_server.list_tasks(user_b)) == 0


class TestCalendarServer:
    async def test_list_events_without_credentials_raises_google_auth_error(self):
        with pytest.raises(GoogleAuthError, match="No Google credentials stored"):
            await calendar_server.list_events("pytest:no-such-user", "2026-01-01", "2026-01-02")

    async def test_create_event_happy_path_with_mocked_google_client(self):
        fake_created = {
            "id": "evt1",
            "summary": "Dinner",
            "start": {"dateTime": "2026-10-02T19:00:00Z"},
            "end": {"dateTime": "2026-10-02T21:00:00Z"},
            "htmlLink": "http://example.com/evt1",
        }
        fake_service = MagicMock()
        fake_service.events.return_value.insert.return_value.execute.return_value = fake_created

        with patch(
            "app.integrations.google.calendar_client.get_credentials",
            return_value=object(),
        ), patch("app.integrations.google.calendar_client.build", return_value=fake_service):
            result = await calendar_server.create_event(
                "pytest:some-user", "Dinner", "2026-10-02T19:00:00Z", "2026-10-02T21:00:00Z"
            )

        assert result["id"] == "evt1"
        assert result["summary"] == "Dinner"


class TestEmailServer:
    async def test_list_inbox_without_credentials_raises_google_auth_error(self):
        with pytest.raises(GoogleAuthError, match="No Google credentials stored"):
            await email_server.list_inbox("pytest:no-such-user")

    async def test_send_happy_path_with_mocked_google_client(self):
        fake_service = MagicMock()
        fake_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "sent1"
        }

        with patch(
            "app.integrations.google.gmail_client.get_credentials", return_value=object()
        ), patch("app.integrations.google.gmail_client.build", return_value=fake_service):
            result = await email_server.send(
                "pytest:some-user", to=["friend@example.com"], subject="Hi", body="Hello!"
            )

        assert result == {"message_id": "sent1", "status": "sent"}


class TestWebSearchServer:
    async def test_search_shapes_ddgs_results(self):
        fake_results = [
            {"title": "Best time to visit Kyoto", "href": "http://example.com/1", "body": "Spring or fall."},
        ]
        fake_ddgs_instance = MagicMock()
        fake_ddgs_instance.__enter__.return_value.text.return_value = fake_results
        fake_ddgs_instance.__exit__.return_value = False

        with patch.object(web_search_server, "DDGS", return_value=fake_ddgs_instance):
            results = await web_search_server.search("best time to visit Kyoto", max_results=1)

        assert results == [
            {
                "title": "Best time to visit Kyoto",
                "url": "http://example.com/1",
                "snippet": "Spring or fall.",
            }
        ]