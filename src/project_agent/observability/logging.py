from __future__ import annotations

import logging as stdlib_logging
import time
from typing import cast

import structlog

from project_agent.observability.sanitization import sanitize_event_dict

_LOG_LEVELS = {
    "DEBUG": stdlib_logging.DEBUG,
    "INFO": stdlib_logging.INFO,
    "WARNING": stdlib_logging.WARNING,
    "ERROR": stdlib_logging.ERROR,
    "CRITICAL": stdlib_logging.CRITICAL,
}


def configure_structured_logging(*, log_level: str) -> None:
    """Configure idempotent stdout JSON logging for the current process."""

    normalized = log_level.strip().upper()
    try:
        minimum_level = _LOG_LEVELS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported log level: {log_level!r}") from exc

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            sanitize_event_dict,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(minimum_level),
        cache_logger_on_first_use=False,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return the process structured logger."""

    return cast(structlog.stdlib.BoundLogger, structlog.get_logger())


def bind_log_context(**fields: object) -> None:
    """Bind request/job scoped fields to the current context only."""

    structlog.contextvars.bind_contextvars(**fields)


def clear_log_context() -> None:
    """Clear request/job scoped structured-log context."""

    structlog.contextvars.clear_contextvars()


def elapsed_ms(start_ns: int) -> float:
    """Return elapsed monotonic time in milliseconds."""

    return (time.perf_counter_ns() - start_ns) / 1_000_000
