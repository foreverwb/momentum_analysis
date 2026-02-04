"""
Broker package exports.

IBKR legacy `ibkr_connector.py` has been removed. Use the new layered stack:
- `IBKRConnection`
- `IBKRHistoricalDataFetcher`
- `IBKRMarketDataFetcher`
- `app.services.data_providers.*`
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, NoReturn, Optional, Tuple

import structlog

from ...core.broker_config import load_broker_config
from .base import BrokerConnector
from .ibkr import (
    IBKRConnection,
    IBKRHistoricalDataFetcher,
    IBKRMarketDataFetcher,
    is_ibkr_dependency_available,
)
from .futu import (
    FutuConnection,
    FutuIVCalculator,
    FutuOptionsDataFetcher,
    IVTermResult as FutuIVTermResult,
    OptionContract as FutuOptionContract,
    RateLimiter as FutuRateLimiter,
    estimate_iv_fetch_time,
    futu_unavailable_reason,
    is_futu_dependency_available,
)

logger = structlog.get_logger(__name__)
_IBKR_CONNECTOR_REMOVED_MESSAGE = (
    "IBKRConnector has been removed. Use IBKRConnection + PriceDataProvider "
    "or DataOrchestrator.connect_ibkr(...) instead."
)


class FutuConnector(BrokerConnector):
    """Compatibility connector built on top of the new futu submodules."""

    OI_CACHE_FILE = "oi_cache.json"
    CACHE_LOCK = FutuIVCalculator.CACHE_LOCK

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        market: Optional[str] = None,
    ):
        cfg = load_broker_config().futu
        resolved_host = host.strip() if isinstance(host, str) and host.strip() else cfg.host
        resolved_port = port if isinstance(port, int) and port > 0 else cfg.port
        resolved_market = market.strip() if isinstance(market, str) and market.strip() else cfg.market

        self.host = resolved_host
        self.port = resolved_port
        self.market = resolved_market
        self.connection = FutuConnection(
            host=resolved_host,
            port=resolved_port,
            market=resolved_market,
        )
        self.options_fetcher = FutuOptionsDataFetcher(self.connection)
        self.iv_calculator = FutuIVCalculator(
            connection=self.connection,
            options_fetcher=self.options_fetcher,
            oi_cache_file=self.OI_CACHE_FILE,
        )
        self.chain_limiter = self.options_fetcher.chain_limiter
        self.snapshot_limiter = self.options_fetcher.snapshot_limiter

        if not is_futu_dependency_available():
            logger.warning(
                "futu_connector_dependency_unavailable",
                reason=futu_unavailable_reason(),
            )

    def connect(self) -> bool:
        try:
            return bool(self.connection.connect())
        except Exception as exc:
            logger.warning("futu_connector_connect_failed", error=str(exc))
            return False

    def disconnect(self) -> None:
        try:
            self.connection.disconnect()
        except Exception as exc:
            logger.warning("futu_connector_disconnect_failed", error=str(exc))

    def is_connected(self) -> bool:
        try:
            return bool(self.connection.is_connected())
        except Exception:
            return False

    def get_stub_reason(self) -> str:
        return futu_unavailable_reason()

    def get_price_data(self, symbol: str, duration: str = "1 Y") -> Optional[Any]:
        return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            return self.options_fetcher.get_current_price(symbol=symbol)
        except Exception as exc:
            logger.warning("futu_connector_get_current_price_failed", symbol=symbol, error=str(exc))
            return None

    def fetch_iv_terms(
        self,
        symbols: Iterable[str],
        max_days: int = 120,
        window_days: int = 30,
        max_retries: int = 2,
        progress_total: Optional[int] = None,
        progress_offset: int = 0,
        log_progress: bool = True,
        log_fetch_summary: bool = True,
    ) -> Dict[str, FutuIVTermResult]:
        symbols_list = list(symbols)
        if not symbols_list:
            return {}
        try:
            return self.iv_calculator.fetch_iv_terms(
                symbols=symbols_list,
                max_days=max_days,
                window_days=window_days,
                max_retries=max_retries,
                progress_total=progress_total,
                progress_offset=progress_offset,
                log_progress=log_progress,
                log_fetch_summary=log_fetch_summary,
            )
        except Exception as exc:
            logger.warning("futu_connector_fetch_iv_terms_failed", error=str(exc))
            return {symbol: FutuIVTermResult() for symbol in symbols_list}

    def batch_compute_delta_oi(
        self,
        symbol_to_oi: Dict[str, Optional[int]],
    ) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        try:
            return self.iv_calculator.batch_compute_delta_oi(symbol_to_oi=symbol_to_oi)
        except Exception as exc:
            logger.warning("futu_connector_batch_compute_delta_oi_failed", error=str(exc))
            return {symbol: (None, None) for symbol in symbol_to_oi}

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


def is_futu_available() -> bool:
    return bool(is_futu_dependency_available())


def create_futu_connector(
    host: Optional[str] = None,
    port: Optional[int] = None,
    market: Optional[str] = None,
) -> FutuConnector:
    return FutuConnector(host=host, port=port, market=market)


def is_ibkr_available() -> bool:
    """Return whether IBKR dependency (`ib_insync`) is available."""
    return bool(is_ibkr_dependency_available())


def create_ibkr_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    client_id: Optional[int] = None,
    timeout: Optional[int] = None,
) -> IBKRConnection:
    """Factory for IBKR connection object."""
    cfg = load_broker_config().ibkr
    resolved_host = host.strip() if isinstance(host, str) and host.strip() else cfg.host
    resolved_port = port if isinstance(port, int) and port > 0 else cfg.port
    resolved_client_id = client_id if isinstance(client_id, int) and client_id > 0 else cfg.client_id
    resolved_timeout = timeout if isinstance(timeout, int) and timeout > 0 else cfg.timeout
    return IBKRConnection(
        host=resolved_host,
        port=resolved_port,
        client_id=resolved_client_id,
        timeout=resolved_timeout,
    )


def create_ibkr_historical_fetcher(connection: Any) -> IBKRHistoricalDataFetcher:
    """Factory for historical-data fetcher."""
    return IBKRHistoricalDataFetcher(connection)


def create_ibkr_market_fetcher(connection: Any) -> IBKRMarketDataFetcher:
    """Factory for market-data fetcher."""
    return IBKRMarketDataFetcher(connection)


def _raise_ibkr_connector_removed() -> NoReturn:
    raise RuntimeError(_IBKR_CONNECTOR_REMOVED_MESSAGE)


class IBKRConnector:
    """
    Compatibility symbol retained after removing legacy `ibkr_connector.py`.

    Instantiation is intentionally blocked to force migration.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        _raise_ibkr_connector_removed()


def create_ibkr_connector(*args: Any, **kwargs: Any) -> Any:
    _raise_ibkr_connector_removed()


__all__ = [
    "BrokerConnector",
    "FutuConnector",
    "IBKRConnector",
    "FutuConnection",
    "FutuOptionsDataFetcher",
    "FutuIVCalculator",
    "FutuIVTermResult",
    "FutuOptionContract",
    "FutuRateLimiter",
    "IBKRConnection",
    "IBKRHistoricalDataFetcher",
    "IBKRMarketDataFetcher",
    "is_ibkr_available",
    "is_futu_available",
    "is_futu_dependency_available",
    "futu_unavailable_reason",
    "estimate_iv_fetch_time",
    "create_ibkr_connector",
    "create_ibkr_connection",
    "create_ibkr_historical_fetcher",
    "create_ibkr_market_fetcher",
    "create_futu_connector",
]
