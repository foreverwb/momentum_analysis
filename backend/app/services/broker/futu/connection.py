"""
Futu connection lifecycle management.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog

from ....core.broker_config import load_broker_config
from .utils import OPEN_QUOTE_CONTEXT, futu_unavailable_reason, is_futu_dependency_available

logger = structlog.get_logger(__name__)


class FutuConnection:
    """Manage Futu OpenD connection only."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        market: Optional[str] = None,
    ):
        cfg = load_broker_config().futu
        env_host = os.getenv("FUTU_HOST")
        env_port = os.getenv("FUTU_PORT")
        env_market = os.getenv("FUTU_MARKET")

        resolved_host = (
            host
            if isinstance(host, str) and host.strip()
            else (env_host if isinstance(env_host, str) and env_host.strip() else cfg.host)
        )
        self.host = resolved_host.strip()

        if isinstance(port, int) and port > 0:
            self.port = port
        elif env_port and env_port.isdigit() and int(env_port) > 0:
            self.port = int(env_port)
        else:
            self.port = cfg.port

        if isinstance(market, str) and market.strip():
            self.market = market.strip()
        else:
            self.market = (env_market or cfg.market).strip()
        self._quote_ctx: Optional[Any] = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to Futu OpenD. Returns False on any failure."""
        if not is_futu_dependency_available() or OPEN_QUOTE_CONTEXT is None:
            logger.warning("futu_connect_skipped_dependency_unavailable", reason=futu_unavailable_reason())
            self._quote_ctx = None
            self._connected = False
            return False

        try:
            self._quote_ctx = OPEN_QUOTE_CONTEXT(host=self.host, port=self.port)
            self._connected = True
            logger.info("futu_connected", host=self.host, port=self.port, market=self.market)
            return True
        except Exception as exc:
            logger.warning("futu_connect_failed", error=str(exc))
            self._quote_ctx = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect safely. Never raises."""
        try:
            if self._quote_ctx is not None:
                self._quote_ctx.close()
        except Exception as exc:
            logger.warning("futu_disconnect_failed", error=str(exc))
        finally:
            self._quote_ctx = None
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._quote_ctx is not None

    def get_client(self) -> Optional[Any]:
        return self._quote_ctx if self.is_connected() else None

    def get_unavailable_reason(self) -> Optional[str]:
        if is_futu_dependency_available():
            return None
        return futu_unavailable_reason()

    def __enter__(self) -> "FutuConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
