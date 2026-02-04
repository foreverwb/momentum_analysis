"""
Utilities for optional futu dependency handling.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

FUTU_AVAILABLE = False
FUTU_IMPORT_ERROR: Optional[Exception] = None

OPEN_QUOTE_CONTEXT: Optional[type] = None
OPTION_TYPE: Any = None
RET_OK: Any = None


class _DummyOptionType:
    CALL = "CALL"
    PUT = "PUT"


try:
    from futu import OpenQuoteContext, OptionType, RET_OK as FUTU_RET_OK

    OPEN_QUOTE_CONTEXT = OpenQuoteContext
    OPTION_TYPE = OptionType
    RET_OK = FUTU_RET_OK
    FUTU_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime environment
    FUTU_IMPORT_ERROR = exc
    OPTION_TYPE = _DummyOptionType
    logger.warning("futu_dependency_unavailable", error=str(exc))


def is_futu_dependency_available() -> bool:
    """Return whether futu dependency imports are available."""
    return FUTU_AVAILABLE and OPEN_QUOTE_CONTEXT is not None


def futu_unavailable_reason() -> str:
    """Return dependency error message when futu is unavailable."""
    if FUTU_IMPORT_ERROR is None:
        return "futu dependency unavailable"
    return str(FUTU_IMPORT_ERROR)
