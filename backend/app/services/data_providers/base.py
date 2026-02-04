"""
Data provider abstract base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class DataProvider(ABC):
    """Base interface for all data providers."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether provider can currently serve requests."""
        raise NotImplementedError

    @abstractmethod
    def get_data(self, symbol: str, **kwargs) -> Optional[Any]:
        """Generic data access method for compatibility."""
        raise NotImplementedError

