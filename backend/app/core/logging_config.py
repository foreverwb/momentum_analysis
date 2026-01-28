"""Logging configuration for structured logging with structlog."""

from __future__ import annotations

import logging
import os
import sys
from typing import List

import structlog

_CONFIGURED = False


def _get_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return logging._nameToLevel.get(level_name, logging.INFO)


def _get_renderer():
    log_format = os.getenv("LOG_FORMAT", "console").lower()
    if log_format == "json":
        return structlog.processors.JSONRenderer()
    return structlog.processors.KeyValueRenderer(
        key_order=["T", "level", "logger", "event"]
    )


def _get_pre_chain() -> List[structlog.types.Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=True, key="T"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def configure_logging() -> None:
    """Configure standard logging and structlog once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = _get_log_level()
    pre_chain = _get_pre_chain()
    renderer = _get_renderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=pre_chain,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)

    for logger_name in ("uvicorn", "uvicorn.error"):
        lib_logger = logging.getLogger(logger_name)
        lib_logger.handlers.clear()
        lib_logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=True, key="T"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True
