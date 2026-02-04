"""
Price data provider for IBKR-backed market/historical data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

from .base import DataProvider

logger = structlog.get_logger(__name__)

_IBKR_IMPORT_ERROR: Optional[Exception] = None

try:
    from ..broker.ibkr.connection import IBKRConnection
    from ..broker.ibkr.historical_data import IBKRHistoricalDataFetcher
    from ..broker.ibkr.market_data import IBKRMarketDataFetcher
except Exception as exc:  # pragma: no cover - depends on runtime environment
    _IBKR_IMPORT_ERROR = exc
    IBKRConnection = Any  # type: ignore[assignment]
    IBKRHistoricalDataFetcher = Any  # type: ignore[assignment]
    IBKRMarketDataFetcher = Any  # type: ignore[assignment]


class PriceDataProvider(DataProvider):
    """
    Unified price-data provider facade.

    This provider does not calculate technical indicators or scores.
    """

    def __init__(
        self,
        ibkr_connection: Optional[Any] = None,
        historical_fetcher: Optional[Any] = None,
        market_fetcher: Optional[Any] = None,
    ):
        self.ibkr_connection = ibkr_connection
        self.historical_fetcher = historical_fetcher
        self.market_fetcher = market_fetcher

        if self.historical_fetcher is None and self.ibkr_connection is not None:
            self.historical_fetcher = self._build_historical_fetcher(self.ibkr_connection)
        if self.market_fetcher is None and self.ibkr_connection is not None:
            self.market_fetcher = self._build_market_fetcher(self.ibkr_connection)

    def is_available(self) -> bool:
        if self.ibkr_connection is None:
            return False
        try:
            return bool(self.ibkr_connection.is_connected())
        except Exception as exc:
            logger.warning("price_provider_connection_check_failed", error=str(exc))
            return False

    def get_data(self, symbol: str, **kwargs) -> Optional[pd.DataFrame]:
        return self.get_ohlcv(
            symbol=symbol,
            duration=kwargs.get("duration", "1 Y"),
            bar_size=kwargs.get("bar_size", "1 day"),
        )

    def get_ohlcv(
        self,
        symbol: str,
        duration: str = "1 Y",
        bar_size: str = "1 day",
    ) -> Optional[pd.DataFrame]:
        if not self.is_available() or self.historical_fetcher is None:
            logger.warning("price_provider_unavailable", method="get_ohlcv", symbol=symbol)
            return None

        try:
            return self.historical_fetcher.get_ohlcv(
                symbol=symbol,
                duration=duration,
                bar_size=bar_size,
            )
        except Exception as exc:
            logger.warning("price_provider_get_ohlcv_failed", symbol=symbol, error=str(exc))
            return None

    def get_close_prices(self, symbol: str, duration: str = "1 Y") -> Optional[pd.DataFrame]:
        if not self.is_available() or self.historical_fetcher is None:
            logger.warning("price_provider_unavailable", method="get_close_prices", symbol=symbol)
            return None

        try:
            return self.historical_fetcher.get_close_prices(symbol=symbol, duration=duration)
        except Exception as exc:
            logger.warning("price_provider_get_close_prices_failed", symbol=symbol, error=str(exc))
            return None

    def batch_get_ohlcv(
        self,
        symbols: List[str],
        duration: str = "1 Y",
        bar_size: str = "1 day",
    ) -> Dict[str, pd.DataFrame]:
        if not self.is_available() or self.historical_fetcher is None:
            logger.warning("price_provider_unavailable", method="batch_get_ohlcv")
            return {}

        try:
            data = self.historical_fetcher.batch_get_ohlcv(
                symbols=symbols,
                duration=duration,
                bar_size=bar_size,
            )
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("price_provider_batch_get_ohlcv_failed", error=str(exc))
            return {}

    def get_current_price(self, symbol: str) -> Optional[float]:
        if not self.is_available() or self.market_fetcher is None:
            logger.warning("price_provider_unavailable", method="get_current_price", symbol=symbol)
            return None

        try:
            return self.market_fetcher.get_current_price(symbol=symbol)
        except Exception as exc:
            logger.warning("price_provider_get_current_price_failed", symbol=symbol, error=str(exc))
            return None

    def get_vix(self) -> Optional[float]:
        if not self.is_available() or self.historical_fetcher is None:
            logger.warning("price_provider_unavailable", method="get_vix")
            return None

        try:
            return self.historical_fetcher.get_vix()
        except Exception as exc:
            logger.warning("price_provider_get_vix_failed", error=str(exc))
            return None

    @staticmethod
    def _build_historical_fetcher(connection: Any) -> Optional[Any]:
        if _IBKR_IMPORT_ERROR is not None:
            logger.warning("price_provider_ibkr_import_unavailable", error=str(_IBKR_IMPORT_ERROR))
            return None
        try:
            return IBKRHistoricalDataFetcher(connection)
        except Exception as exc:
            logger.warning("price_provider_create_historical_fetcher_failed", error=str(exc))
            return None

    @staticmethod
    def _build_market_fetcher(connection: Any) -> Optional[Any]:
        if _IBKR_IMPORT_ERROR is not None:
            logger.warning("price_provider_ibkr_import_unavailable", error=str(_IBKR_IMPORT_ERROR))
            return None
        try:
            return IBKRMarketDataFetcher(connection)
        except Exception as exc:
            logger.warning("price_provider_create_market_fetcher_failed", error=str(exc))
            return None

