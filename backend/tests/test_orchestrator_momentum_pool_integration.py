"""
Orchestrator integration test for momentum pool entry.

Requirement:
- mock PriceDataProvider.get_ohlcv with fixed dataframe
- verify output contains total_score / scores / metrics
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.orchestrator import DataOrchestrator


class _ConnectedConnection:
    def is_connected(self) -> bool:
        return True


class _FakePriceProvider:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def get_ohlcv(self, symbol: str, duration: str = "1 Y", bar_size: str = "1 day") -> pd.DataFrame:
        # return copy to avoid cross-call mutation
        return self._df.copy()


def _make_ohlcv(rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    base = np.linspace(100.0, 150.0, rows)
    close = base + np.sin(np.linspace(0, 10, rows))
    high = close + 1.5
    low = close - 1.5
    open_ = close - 0.5
    volume = np.linspace(1_000_000, 2_000_000, rows)

    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.mark.asyncio
async def test_orchestrator_calculate_momentum_pool_score_returns_expected_shape() -> None:
    orchestrator = DataOrchestrator()
    orchestrator._broker_status["ibkr"].is_connected = True
    orchestrator._ibkr_connection = _ConnectedConnection()
    orchestrator._price_provider = _FakePriceProvider(_make_ohlcv())

    result = await orchestrator.calculate_momentum_pool_score(
        symbol="AAPL",
        sector_etf="XLK",
        finviz_data={"beta": 1.2},
        mc_data={"heat_score": 66, "ivr": 45},
        iv_data={"iv30": 0.25},
    )

    assert isinstance(result, dict)
    assert "total_score" in result
    assert "scores" in result
    assert "metrics" in result
    assert isinstance(result["scores"], dict)
    assert isinstance(result["metrics"], dict)
    assert result["total_score"] is not None


@pytest.mark.asyncio
async def test_orchestrator_momentum_pool_returns_structured_error_when_disconnected() -> None:
    orchestrator = DataOrchestrator()

    result = await orchestrator.calculate_momentum_pool_score(symbol="AAPL", sector_etf="XLK")

    assert isinstance(result, dict)
    assert result.get("error") == "IBKR not connected"
    assert "total_score" in result
    assert "scores" in result
    assert "metrics" in result

