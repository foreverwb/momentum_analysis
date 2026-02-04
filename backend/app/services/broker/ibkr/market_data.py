"""
IBKR market snapshot data fetching.
"""

from __future__ import annotations

from typing import Optional

import structlog

from .connection import IBKRConnection
from .utils import make_stock_contract

logger = structlog.get_logger(__name__)


class IBKRMarketDataFetcher:
    """Fetch current market price snapshots from IBKR."""

    def __init__(self, connection: IBKRConnection):
        self.connection = connection

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Return current price from IBKR snapshot, or None when unavailable.
        """
        def _fetch(ib_client):
            contract = make_stock_contract(symbol)
            if contract is None:
                return None

            try:
                ib_client.qualifyContracts(contract)
                ticker = ib_client.reqMktData(contract, "", snapshot=True)
                ib_client.sleep(2)

                price = self._extract_price(ticker)
                return float(price) if price is not None else None
            finally:
                try:
                    ib_client.cancelMktData(contract)
                except Exception:
                    pass

        try:
            return self.connection.run_with_client(_fetch)
        except Exception as exc:
            logger.warning("ibkr_get_current_price_failed", symbol=symbol, error=str(exc))
            return None

    @staticmethod
    def _extract_price(ticker) -> Optional[float]:
        if ticker is None:
            return None

        candidates = []
        last = getattr(ticker, "last", None)
        close = getattr(ticker, "close", None)
        bid = getattr(ticker, "bid", None)
        ask = getattr(ticker, "ask", None)
        market_price_attr = getattr(ticker, "marketPrice", None)

        candidates.extend([last, close, bid, ask])
        if callable(market_price_attr):
            try:
                candidates.append(market_price_attr())
            except Exception:
                pass
        elif market_price_attr is not None:
            candidates.append(market_price_attr)

        for candidate in candidates:
            try:
                value = float(candidate)
                if value > 0:
                    return value
            except Exception:
                continue

        return None
