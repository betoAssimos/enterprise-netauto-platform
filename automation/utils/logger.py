"""
automation/utils/logger.py

Structured logging for the entire platform.
All modules use get_logger(__name__) — never logging.getLogger() directly.
JSON output in CI/production. Human-readable console output in lab.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from automation.config import get_settings


def _add_platform_context(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    cfg = get_settings()
    event_dict.setdefault("environment", cfg.environment)
    event_dict.setdefault("dry_run", cfg.dry_run)
    return event_dict


def configure_logging() -> None:
    """Configure structlog once at process startup. Safe to call multiple times."""
    cfg = get_settings()
    log_level = getattr(logging, cfg.log_level, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_platform_context,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    if sys.stderr.isatty() and cfg.environment == "lab":
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    for noisy in ("paramiko", "urllib3", "asyncssh"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Usage:
        log = get_logger(__name__)
        log.info("deploying config", device="rtr-01")
    """
    return structlog.get_logger(name)


def bind_job_context(job_id: str, **extra: Any) -> None:
    """Bind job-scoped context to all log calls in this thread."""
    structlog.contextvars.bind_contextvars(job_id=job_id, **extra)


def clear_job_context() -> None:
    """Clear all bound context variables. Call at job teardown."""
    structlog.contextvars.clear_contextvars()
