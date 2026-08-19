"""
Retry presets built on tenacity (already a dependency — see pyproject.toml)
for the network calls scattered across the codebase. Each preset targets
the failure modes that call site actually sees, rather than one generic
"retry everything" decorator — retrying a 4xx or a semantic tool error
just delays the inevitable and hides a real bug.

None of these are wired into existing call sites yet (app/mcp/client.py,
app/integrations/google/*.py, app/integrations/llm/provider.py) — apply the
matching decorator to a function there when you're ready to make that call
resilient to transient failures, e.g.:

    from app.utils.retry import retry_mcp_call

    @retry_mcp_call()
    async def call_tool(server_url: str, tool_name: str, arguments: dict) -> Any:
        ...
"""

import logging as _logging

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.utils.logging import get_logger

logger = get_logger(__name__)


def retry_network_call(max_attempts: int = 3, exceptions: tuple[type[Exception], ...] = (Exception,)):
    """
    General-purpose retry for transient network failures — exponential
    backoff with jitter so retries from multiple concurrent requests don't
    all land on the same instant. Prefer one of the scoped presets below
    where it fits; reach for this directly only for something new.
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(exceptions),
        before_sleep=before_sleep_log(logger, _logging.WARNING),
        reraise=True,
    )


def retry_mcp_call(max_attempts: int = 3):
    """
    For app/mcp/client.py calls: retry connection-level failures (server
    unreachable, timeout) since those are often transient. Deliberately does
    NOT retry MCPToolError — that means the server responded and the tool
    itself failed (e.g. Google auth not set up for this user), and a retry
    won't fix that.
    """
    import httpx

    return retry_network_call(max_attempts, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout))


def retry_llm_call(max_attempts: int = 3):
    """
    For app/integrations/llm/provider.py-backed calls: retry connection
    failures (Ollama not up yet, a hosted provider's transient 5xx) —
    LangChain chat models generally surface httpx-based connection errors
    under the hood regardless of which provider is active.
    """
    import httpx

    return retry_network_call(max_attempts, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout))


def retry_google_api_call(max_attempts: int = 3):
    """
    For app/integrations/google/*.py calls: retry on 5xx responses and
    connection issues, not on 4xx (those are real errors — bad request,
    expired/invalid auth — that retrying won't fix).
    """

    def _is_retryable(exc: BaseException) -> bool:
        try:
            from googleapiclient.errors import HttpError

            if isinstance(exc, HttpError):
                return exc.resp.status >= 500
        except ImportError:
            pass
        return isinstance(exc, (ConnectionError, TimeoutError))

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, _logging.WARNING),
        reraise=True,
    )