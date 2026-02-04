"""
PriceDataProvider unavailable-path tests.

Requirement:
- mock IBKRConnection.is_connected = False
- provider methods return None / {}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.data_providers.price_provider import PriceDataProvider


class _DisconnectedConnection:
    def is_connected(self) -> bool:
        return False


class _FailingHistoricalFetcher:
    def get_ohlcv(self, symbol: str, duration: str = "1 Y", bar_size: str = "1 day") -> Optional[pd.DataFrame]:
        raise AssertionError("historical fetcher should not be called when provider unavailable")

    def get_close_prices(self, symbol: str, duration: str = "1 Y") -> Optional[pd.DataFrame]:
        raise AssertionError("historical fetcher should not be called when provider unavailable")

    def batch_get_ohlcv(
        self,
        symbols: List[str],
        duration: str = "1 Y",
        bar_size: str = "1 day",
    ) -> Dict[str, pd.DataFrame]:
        raise AssertionError("historical fetcher should not be called when provider unavailable")

    def get_vix(self) -> Optional[float]:
        raise AssertionError("historical fetcher should not be called when provider unavailable")


class _FailingMarketFetcher:
    def get_current_price(self, symbol: str) -> Optional[float]:
        raise AssertionError("market fetcher should not be called when provider unavailable")


def _build_provider() -> PriceDataProvider:
    return PriceDataProvider(
        ibkr_connection=_DisconnectedConnection(),
        historical_fetcher=_FailingHistoricalFetcher(),
        market_fetcher=_FailingMarketFetcher(),
    )


def test_price_provider_returns_none_or_empty_when_unavailable() -> None:
    provider = _build_provider()

    assert provider.is_available() is False
    assert provider.get_data("AAPL") is None
    assert provider.get_ohlcv("AAPL") is None
    assert provider.get_close_prices("AAPL") is None
    assert provider.batch_get_ohlcv(["AAPL", "MSFT"]) == {}
    assert provider.get_current_price("AAPL") is None
    assert provider.get_vix() is None

