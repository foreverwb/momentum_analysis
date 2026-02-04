"""
IBKR broker subpackage.

This package intentionally keeps responsibilities separated:
- `connection.py`: connection lifecycle
- `historical_data.py`: historical data fetching
- `market_data.py`: snapshot market data fetching
"""

from .connection import IBKRConnection
from .historical_data import IBKRHistoricalDataFetcher
from .market_data import IBKRMarketDataFetcher
from .utils import is_ibkr_dependency_available

__all__ = [
    "IBKRConnection",
    "IBKRHistoricalDataFetcher",
    "IBKRMarketDataFetcher",
    "is_ibkr_dependency_available",
]

