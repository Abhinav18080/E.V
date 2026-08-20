"""
Shared pytest fixtures.

Async tests rely on pytest-asyncio in "auto" mode (see [tool.pytest.ini_options]
in pyproject.toml), so `async def test_...` functions work without an
`@pytest.mark.asyncio` marker.

Two fixture families live here:
  - redis_client: a real Redis client (see app/redis_client.py) — most of
    this codebase's actual logic IS its Redis interactions (short-term
    memory, approvals, tasks), so these tests hit real Redis rather than
    mocking it. Requires `redis-server` running locally (`make up` starts
    it via Docker Compose).
  - {name}_mcp_server fixtures: run a real MCP server module as a subprocess
    on its default port and yield its base URL, for integration tests that
    want to exercise the actual streamable-HTTP wire protocol rather than
    calling tool functions in-process. Module-scoped, so a whole test file
    shares one running server instance instead of restarting it per test.
"""

import socket
import subprocess
import sys
import time
from collections.abc import Generator

import pytest

from app.redis_client import get_redis_client

TEST_KEY_PREFIX = "pytest:"


@pytest.fixture
async def redis_client():
    """Real Redis client. Cleans up any keys under TEST_KEY_PREFIX after each test —
    tests that write outside that prefix (e.g. real feature keys like "tasks:{user}")
    are responsible for their own cleanup, since blanket-deleting those could clash
    with a real dev instance running on the same Redis."""
    client = get_redis_client()
    yield client
    async for key in client.scan_iter(f"{TEST_KEY_PREFIX}*"):
        await client.delete(key)


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Nothing is listening on localhost:{port} after {timeout}s")


def _mcp_server_fixture(module: str, port: int) -> Generator[str, None, None]:
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield f"http://localhost:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def tasks_mcp_server():
    yield from _mcp_server_fixture("app.mcp.servers.tasks_server", 9003)


@pytest.fixture(scope="module")
def calendar_mcp_server():
    yield from _mcp_server_fixture("app.mcp.servers.calendar_server", 9001)


@pytest.fixture(scope="module")
def email_mcp_server():
    yield from _mcp_server_fixture("app.mcp.servers.email_server", 9002)


@pytest.fixture(scope="module")
def web_search_mcp_server():
    yield from _mcp_server_fixture("app.mcp.servers.web_search_server", 9004)