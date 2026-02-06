"""Logging configuration for structured logging with structlog."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any, List

import structlog

_CONFIGURED = False


class _UvicornNoiseFilter(logging.Filter):
    """Filter out routine uvicorn info/debug logs while keeping warnings/errors."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - short and clear
        if record.name.startswith("uvicorn"):
            return record.levelno >= logging.WARNING
        return True


def _get_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return logging._nameToLevel.get(level_name, logging.INFO)


def _get_renderer():
    """
    Choose renderer.
    - plain  (default): only emit the event/message body, no extra key/value clutter.
    - console: key=value format (legacy)
    - json: structured JSON
    """
    log_format = os.getenv("LOG_FORMAT", "plain").lower()

    if log_format == "json":
        return structlog.processors.JSONRenderer()

    if log_format in ("plain", "text"):
        def _plain_renderer(_logger, _name, event_dict):
            event = event_dict.get("event", "")
            return event if isinstance(event, str) else str(event)
        return _plain_renderer

    # fallback to legacy key=value rendering
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
        _decode_unicode_escapes,
    ]


_UNICODE_ESCAPE_RE = re.compile(r"(\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|\\x[0-9a-fA-F]{2})")


def _decode_unicode_escapes(_logger, _name, event_dict: dict) -> dict:
    def _decode(value: Any) -> Any:
        if isinstance(value, str):
            if not _UNICODE_ESCAPE_RE.search(value):
                return value
            try:
                decoded = value.encode("utf-8").decode("unicode_escape")
            except Exception:
                return value
            return decoded
        if isinstance(value, dict):
            return {k: _decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_decode(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_decode(v) for v in value)
        return value

    return _decode(event_dict)


def configure_logging() -> None:
    """Configure standard logging and structlog once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = _get_log_level()
    pre_chain = _get_pre_chain()
    renderer = _get_renderer()
    noise_filter = _UvicornNoiseFilter()

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
        handler.addFilter(noise_filter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            handler.addFilter(noise_filter)

    for logger_name in ("uvicorn", "uvicorn.error"):
        lib_logger = logging.getLogger(logger_name)
        lib_logger.handlers.clear()
        lib_logger.setLevel(logging.WARNING)
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
            _decode_unicode_escapes,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True
