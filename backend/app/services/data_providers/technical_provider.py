"""
Technical data provider.

This provider assembles technical indicator outputs from price data.
It does not perform business scoring or sector/industry comparisons.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

import pandas as pd
import structlog

from .base import DataProvider
from .price_provider import PriceDataProvider

logger = structlog.get_logger(__name__)

_TECH_IMPORT_ERROR: Optional[Exception] = None

try:
    from ..calculators.technical import (
        analyze_technical,
        calculate_max_drawdown,
        calculate_returns,
        calculate_rsi,
    )
except Exception as exc:  # pragma: no cover - depends on runtime environment
    _TECH_IMPORT_ERROR = exc
    analyze_technical = None  # type: ignore[assignment]
    calculate_max_drawdown = None  # type: ignore[assignment]
    calculate_returns = None  # type: ignore[assignment]
    calculate_rsi = None  # type: ignore[assignment]


class TechnicalDataProvider(DataProvider):
    """Provider for technical-analysis-oriented data products."""

    def __init__(self, price_provider: PriceDataProvider):
        self.price_provider = price_provider

    def is_available(self) -> bool:
        return self.price_provider.is_available()

    def get_data(self, symbol: str, **kwargs) -> Optional[Dict[str, Any]]:
        return self.get_technical_analysis(
            symbol=symbol,
            duration=kwargs.get("duration", "1 Y"),
        )

    def get_technical_analysis(
        self,
        symbol: str,
        duration: str = "1 Y",
    ) -> Optional[Dict[str, Any]]:
        if not self.is_available():
            logger.warning("technical_provider_unavailable", method="get_technical_analysis", symbol=symbol)
            return None

        if analyze_technical is None:
            logger.warning(
                "technical_provider_dependency_unavailable",
                method="get_technical_analysis",
                error=str(_TECH_IMPORT_ERROR),
            )
            return None

        df = self.price_provider.get_ohlcv(symbol=symbol, duration=duration, bar_size="1 day")
        if df is None or df.empty:
            return None

        try:
            analysis = analyze_technical(df, symbol=symbol)
            if analysis is None:
                return None
            return self._normalize_analysis_output(analysis)
        except Exception as exc:
            logger.warning("technical_provider_analysis_failed", symbol=symbol, error=str(exc))
            return None

    def get_momentum_metrics(
        self,
        symbol: str,
        duration: str = "90 D",
    ) -> Optional[Dict[str, Optional[float]]]:
        if not self.is_available():
            logger.warning("technical_provider_unavailable", method="get_momentum_metrics", symbol=symbol)
            return None

        df = self.price_provider.get_ohlcv(symbol=symbol, duration=duration, bar_size="1 day")
        if df is None or df.empty or "close" not in df.columns:
            return None

        prices = pd.to_numeric(df["close"], errors="coerce").dropna()
        if prices.empty:
            return None

        metrics: Dict[str, Optional[float]] = {
            "return_5d": self._safe_return(prices, 5),
            "return_20d": self._safe_return(prices, 20),
            "return_63d": self._safe_return(prices, 63),
            "rsi": self._safe_rsi(prices),
            "max_drawdown_20d": self._safe_max_drawdown(prices, 20),
        }
        return metrics

    @staticmethod
    def _normalize_analysis_output(result: Any) -> Dict[str, Any]:
        if is_dataclass(result):
            return asdict(result)
        if isinstance(result, dict):
            return result
        if hasattr(result, "__dict__"):
            return dict(vars(result))
        return {"value": result}

    @staticmethod
    def _safe_return(prices: pd.Series, period: int) -> Optional[float]:
        if len(prices) < period + 1 or calculate_returns is None:
            return None
        try:
            return float(calculate_returns(prices, period))
        except Exception:
            return None

    @staticmethod
    def _safe_rsi(prices: pd.Series) -> Optional[float]:
        if len(prices) < 2 or calculate_rsi is None:
            return None
        try:
            rsi_series = calculate_rsi(prices, window=14)
            if len(rsi_series) == 0:
                return None
            value = rsi_series.iloc[-1]
            if pd.isna(value):
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _safe_max_drawdown(prices: pd.Series, window: int) -> Optional[float]:
        if len(prices) < window or calculate_max_drawdown is None:
            return None
        try:
            return float(calculate_max_drawdown(prices, window=window))
        except Exception:
            return None

