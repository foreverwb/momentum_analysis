"""
Utilities for optional ib_insync dependency handling.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

IB_INSYNC_AVAILABLE = False
IB_CLASS: Optional[type] = None
STOCK_CLASS: Optional[type] = None
INDEX_CLASS: Optional[type] = None
IB_UTIL: Any = None

try:
    from ib_insync import IB, Index, Stock, util

    IB_CLASS = IB
    STOCK_CLASS = Stock
    INDEX_CLASS = Index
    IB_UTIL = util
    IB_INSYNC_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime env
    logger.warning("ibkr_ib_insync_unavailable", error=str(exc))


def is_ibkr_dependency_available() -> bool:
    """Return whether `ib_insync` imports are available."""
    return IB_INSYNC_AVAILABLE


def format_ibkr_stock_symbol(symbol: str) -> str:
    """
    Normalize stock symbol for IBKR contract construction.

    IBKR uses space-separated class suffixes for some US tickers
    (e.g. BRK.B -> BRK B, BF.B -> BF B).
    """
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return ""
    if "." not in normalized:
        return normalized
    head, *tail = [part for part in normalized.split(".") if part]
    if not head or not tail:
        return normalized
    return " ".join([head, *tail])


def make_stock_contract(symbol: str, exchange: str = "SMART", currency: str = "USD") -> Any:
    """Create a Stock contract if dependency is available."""
    if not STOCK_CLASS:
        return None
    normalized_symbol = format_ibkr_stock_symbol(symbol)
    if not normalized_symbol:
        return None
    return STOCK_CLASS(normalized_symbol, exchange, currency)


def make_index_contract(symbol: str, exchange: str = "CBOE", currency: str = "USD") -> Any:
    """Create an Index contract if dependency is available."""
    if not INDEX_CLASS:
        return None
    return INDEX_CLASS(symbol, exchange, currency)
