"""
Structured logging setup.

configure_logging() is idempotent and safe to call from multiple
entrypoints (app/main.py, each app/mcp/servers/*.py, one-off scripts) —
it only installs handlers once even if called repeatedly. Everywhere else
should use get_logger(__name__) instead of stdlib logging.getLogger
directly, so formatting stays consistent and there's one place to add
things like request-id correlation later.
"""

import logging
import sys

from app.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    root.handlers = [handler]

    # Quiet down noisy third-party loggers unless we're actually debugging —
    # httpx/httpcore log every outbound request at INFO, which drowns out
    # our own logs during normal operation.
    if settings.log_level.upper() != "DEBUG":
        for noisy_logger in ("httpx", "httpcore", "google_auth_httplib2"):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)