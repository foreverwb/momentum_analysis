"""
Futu broker subpackage.

This package separates connection, options data fetching and IV calculations.
"""

from .connection import FutuConnection
from .iv_calculator import FutuIVCalculator, IVTermResult, estimate_iv_fetch_time
from .options_data import FutuOptionsDataFetcher, OptionContract, RateLimiter
from .utils import futu_unavailable_reason, is_futu_dependency_available

__all__ = [
    "FutuConnection",
    "FutuOptionsDataFetcher",
    "FutuIVCalculator",
    "IVTermResult",
    "OptionContract",
    "RateLimiter",
    "estimate_iv_fetch_time",
    "is_futu_dependency_available",
    "futu_unavailable_reason",
]
