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


def _fmt_date(dt: Any) -> str:
    """Format date for log output."""
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt).split(" ")[0].split("T")[0]


class IBKRHistoricalDataFetcher:
    """Fetch OHLCV and close-price series from IBKR."""

    def __init__(self, connection: IBKRConnection):
        self.connection = connection

    @staticmethod
    def _fmt_tag(api_name: str, symbol: str, index: Optional[int] = None, total: Optional[int] = None) -> str:
        """Format log tag: IBKR- [1/10] SPY -> or IBKR- SPY ->"""
        if index is not None and total is not None:
            return f"IBKR- [{index}/{total}] {symbol} ->"
        return f"IBKR- {symbol} ->"

    def get_ohlcv(
        self,
        symbol: str,
        duration: str = "1 Y",
        bar_size: str = "1 day",
        log_index: Optional[int] = None,
        log_total: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Return DataFrame[date, open, high, low, close, volume], or None.
        """
        tag = self._fmt_tag("reqHistoricalData", symbol, log_index, log_total)

        def _fetch(ib_client: Any) -> Optional[pd.DataFrame]:
            contract = make_stock_contract(symbol)
            if contract is None:
                logger.info(
                    "\n".join([
                        tag,
                        f"    ┌ reqHistoricalData  duration={duration}  bar={bar_size}",
                        f"    └ SKIP  reason=invalid_contract",
                    ])
                )
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
                logger.info(
                    "\n".join([
                        tag,
                        f"    ┌ reqHistoricalData  duration={duration}  bar={bar_size}",
                        f"    └ FAIL  error={exc}",
                    ])
                )
                return None

            if not bars:
                last_error = self.connection.get_last_error(max_age_seconds=15)
                err_msg = ""
                if isinstance(last_error, dict):
                    code = last_error.get("code", "")
                    msg = last_error.get("message", "")
                    err_msg = f"  ibkr_error=[{code}] {msg}" if code else f"  ibkr_error={msg}"
                logger.info(
                    "\n".join([
                        tag,
                        f"    ┌ reqHistoricalData  duration={duration}  bar={bar_size}",
                        f"    └ EMPTY  no_bars_returned{err_msg}",
                    ])
                )
                return None

            df = self._bars_to_dataframe(bars)
            if df is None or df.empty:
                logger.info(
                    "\n".join([
                        tag,
                        f"    ┌ reqHistoricalData  duration={duration}  bar={bar_size}",
                        f"    └ EMPTY  bars={len(bars)}  parse_failed",
                    ])
                )
                return None

            # 成功日志
            first_date = df["date"].iloc[0]
            last_date = df["date"].iloc[-1]
            last_close = df["close"].iloc[-1]
            range_str = f"{_fmt_date(first_date)}~{_fmt_date(last_date)}"
            logger.info(
                "\n".join([
                    tag,
                    f"    ┌ reqHistoricalData  duration={duration}  bar={bar_size}",
                    f"    └ OK  rows={len(df)}  range={range_str}  close={last_close:.2f}",
                ])
            )
            return df

        try:
            return self.connection.run_with_client(_fetch)
        except Exception as exc:
            logger.info(
                "\n".join([
                    tag,
                    f"    ┌ reqHistoricalData  duration={duration}  bar={bar_size}",
                    f"    └ FAIL  error={exc}",
                ])
            )
            return None

    def get_close_prices(
        self,
        symbol: str,
        duration: str = "1 Y",
        log_index: Optional[int] = None,
        log_total: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Return DataFrame[date, {symbol}], or None.
        """
        df = self.get_ohlcv(
            symbol=symbol, duration=duration, bar_size="1 day",
            log_index=log_index, log_total=log_total,
        )
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

        total = len(symbols)
        results: Dict[str, pd.DataFrame] = {}
        for idx, symbol in enumerate(symbols, start=1):
            df = self.get_ohlcv(
                symbol=symbol, duration=duration, bar_size=bar_size,
                log_index=idx, log_total=total,
            )
            if df is not None:
                results[symbol] = df
        return results

    def get_vix(self) -> Optional[float]:
        """Return latest VIX close from IBKR, or None."""
        tag = "IBKR- VIX ->"

        def _fetch(ib_client: Any) -> Optional[float]:
            contract = make_index_contract("VIX", exchange="CBOE", currency="USD")
            if contract is None:
                logger.info(
                    "\n".join([
                        tag,
                        "    ┌ reqHistoricalData  duration=1D  bar=1day  type=INDEX",
                        "    └ SKIP  reason=invalid_contract",
                    ])
                )
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
                logger.info(
                    "\n".join([
                        tag,
                        "    ┌ reqHistoricalData  duration=1D  bar=1day  type=INDEX",
                        "    └ EMPTY  no_bars_returned",
                    ])
                )
                return None

            close = getattr(bars[-1], "close", None)
            vix_value = float(close) if close is not None else None
            if vix_value is not None:
                logger.info(
                    "\n".join([
                        tag,
                        "    ┌ reqHistoricalData  duration=1D  bar=1day  type=INDEX",
                        f"    └ OK  vix={vix_value:.2f}",
                    ])
                )
            else:
                logger.info(
                    "\n".join([
                        tag,
                        "    ┌ reqHistoricalData  duration=1D  bar=1day  type=INDEX",
                        "    └ EMPTY  close=None",
                    ])
                )
            return vix_value

        try:
            return self.connection.run_with_client(_fetch)
        except Exception as exc:
            logger.info(
                "\n".join([
                    tag,
                    "    ┌ reqHistoricalData  duration=1D  bar=1day  type=INDEX",
                    f"    └ FAIL  error={exc}",
                ])
            )
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