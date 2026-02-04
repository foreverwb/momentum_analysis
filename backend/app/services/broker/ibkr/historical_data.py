"""
IBKR historical data fetching.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

from .connection import IBKRConnection
from .utils import IB_UTIL, make_index_contract, make_stock_contract

logger = structlog.get_logger(__name__)

OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class IBKRHistoricalDataFetcher:
    """Fetch OHLCV and close-price series from IBKR."""

    def __init__(self, connection: IBKRConnection):
        self.connection = connection

    def get_ohlcv(
        self,
        symbol: str,
        duration: str = "1 Y",
        bar_size: str = "1 day",
    ) -> Optional[pd.DataFrame]:
        """
        Return DataFrame[date, open, high, low, close, volume], or None.
        """
        def _fetch(ib_client: Any) -> Optional[pd.DataFrame]:
            contract = make_stock_contract(symbol)
            if contract is None:
                return None

            self.connection.clear_last_error()
            ib_client.qualifyContracts(contract)
            try:
                bars = ib_client.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                    timeout=20,
                )
            except Exception as exc:
                self.connection.record_error(message=str(exc))
                return None

            if not bars:
                last_error = self.connection.get_last_error(max_age_seconds=15)
                if isinstance(last_error, dict):
                    logger.warning(
                        "ibkr_historical_data_unavailable",
                        symbol=symbol,
                        duration=duration,
                        bar_size=bar_size,
                        error_code=last_error.get("code"),
                        error=last_error.get("message"),
                    )
                return None

            df = self._bars_to_dataframe(bars)
            if df is None or df.empty:
                return None
            return df

        try:
            return self.connection.run_with_client(_fetch)
        except Exception as exc:
            logger.warning(
                "ibkr_get_ohlcv_failed",
                symbol=symbol,
                duration=duration,
                bar_size=bar_size,
                error=str(exc),
            )
            return None

    def get_close_prices(self, symbol: str, duration: str = "1 Y") -> Optional[pd.DataFrame]:
        """
        Return DataFrame[date, {symbol}], or None.
        """
        df = self.get_ohlcv(symbol=symbol, duration=duration, bar_size="1 day")
        if df is None:
            return None

        result = df[["date", "close"]].copy()
        result.columns = ["date", symbol]
        return result

    def batch_get_ohlcv(
        self,
        symbols: List[str],
        duration: str = "1 Y",
        bar_size: str = "1 day",
    ) -> Dict[str, pd.DataFrame]:
        """
        Return {symbol: DataFrame}. Returns {} when unavailable.
        """
        if not symbols:
            return {}

        results: Dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = self.get_ohlcv(symbol=symbol, duration=duration, bar_size=bar_size)
            if df is not None:
                results[symbol] = df
        return results

    def get_vix(self) -> Optional[float]:
        """Return latest VIX close from IBKR, or None."""
        def _fetch(ib_client: Any) -> Optional[float]:
            contract = make_index_contract("VIX", exchange="CBOE", currency="USD")
            if contract is None:
                return None

            ib_client.qualifyContracts(contract)
            bars = ib_client.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                timeout=15,
            )
            if not bars:
                return None

            close = getattr(bars[-1], "close", None)
            return float(close) if close is not None else None

        try:
            return self.connection.run_with_client(_fetch)
        except Exception as exc:
            logger.warning("ibkr_get_vix_failed", error=str(exc))
            return None

    @staticmethod
    def _bars_to_dataframe(bars: Any) -> Optional[pd.DataFrame]:
        try:
            if IB_UTIL is not None:
                raw_df = IB_UTIL.df(bars)
            else:
                raw_df = pd.DataFrame(
                    [
                        {
                            "date": getattr(bar, "date", None),
                            "open": getattr(bar, "open", None),
                            "high": getattr(bar, "high", None),
                            "low": getattr(bar, "low", None),
                            "close": getattr(bar, "close", None),
                            "volume": getattr(bar, "volume", None),
                        }
                        for bar in bars
                    ]
                )

            if raw_df.empty:
                return None

            for col in OHLCV_COLUMNS:
                if col not in raw_df.columns:
                    raw_df[col] = None

            df = raw_df[OHLCV_COLUMNS].copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).reset_index(drop=True)
            if df.empty:
                return None

            return df
        except Exception as exc:
            logger.warning("ibkr_convert_bars_failed", error=str(exc))
            return None
