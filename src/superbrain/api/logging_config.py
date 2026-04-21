"""Structured-logging setup.

``structlog`` produces JSON on stdout; stdlib logging is wired into the same
pipeline so anything ``uvicorn`` or third-party code emits shows up too.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str) -> None:
    """Configure structlog + stdlib logging for the API process.

    Idempotent: calling twice is safe. Designed so tests can swap log levels
    per-app without polluting each other.

    :param level: log level name (e.g. ``"INFO"``)
    """
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(numeric)
