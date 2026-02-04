"""
IBKR connection management.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import Any, Callable, Optional, TypeVar

import structlog

from ....core.broker_config import load_broker_config
from .utils import IB_CLASS, is_ibkr_dependency_available

logger = structlog.get_logger(__name__)
T = TypeVar("T")


class IBKRConnection:
    """
    Manage IBKR connection lifecycle only.

    This class does not auto-connect in constructor.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
        timeout: Optional[int] = None,
    ):
        cfg = load_broker_config().ibkr
        self.host = host.strip() if isinstance(host, str) and host.strip() else cfg.host
        self.port = port if isinstance(port, int) and port > 0 else cfg.port
        self.client_id = client_id if isinstance(client_id, int) and client_id > 0 else cfg.client_id
        self.timeout = timeout if isinstance(timeout, int) and timeout > 0 else cfg.timeout
        self._ib: Optional[Any] = None
        self._connected = False
        self._worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker_thread_id: Optional[int] = None
        self._worker_state_lock = threading.Lock()
        self._pending_worker_futures = 0
        self._error_lock = threading.Lock()
        self._last_error: Optional[dict[str, Any]] = None
        self._error_handler_attached = False
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ibkr-worker",
            initializer=self._init_worker_context,
        )

    def connect(self) -> bool:
        """Connect to TWS / IB Gateway. Returns False on any failure."""
        if not is_ibkr_dependency_available() or IB_CLASS is None:
            logger.warning("ibkr_connect_skipped_dependency_unavailable")
            self._connected = False
            self._ib = None
            return False

        try:
            return bool(self._run_in_worker(self._connect_impl, timeout=self.timeout + 5))
        except Exception as exc:
            self.record_error(message=str(exc))
            logger.warning("ibkr_connect_failed", error=str(exc))
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect safely. Never raises."""
        try:
            self._run_in_worker(self._disconnect_impl, True, timeout=5)
        except Exception as exc:
            logger.warning("ibkr_disconnect_failed", error=str(exc))
            try:
                # fallback: ensure state is reset even if worker is blocked
                self._disconnect_impl(reset_client=True)
            except Exception:
                pass
        finally:
            self._connected = False

    def is_connected(self) -> bool:
        """Connection state with runtime verification."""
        if self._ib is None:
            return False
        if not self._connected:
            return False
        # 如果 worker 正在执行阻塞调用，不要在这里排队等待，直接返回缓存连接状态。
        if self._is_worker_busy():
            return bool(self._connected)
        try:
            connected = bool(self._run_in_worker(self._safe_is_connected, self._ib, timeout=1.5))
            self._connected = connected
            return connected
        except Exception:
            self._connected = False
            return False

    def clear_last_error(self) -> None:
        with self._error_lock:
            self._last_error = None

    def get_last_error(self, max_age_seconds: Optional[float] = None) -> Optional[dict[str, Any]]:
        with self._error_lock:
            payload = dict(self._last_error) if self._last_error is not None else None
        if payload is None:
            return None

        ts = payload.pop("_ts", None)
        if max_age_seconds is not None and isinstance(ts, (int, float)):
            if (monotonic() - ts) > max_age_seconds:
                return None
        return payload

    def get_last_error_message(self, max_age_seconds: Optional[float] = None) -> Optional[str]:
        payload = self.get_last_error(max_age_seconds=max_age_seconds)
        if not payload:
            return None
        message = payload.get("message")
        code = payload.get("code")
        if not message:
            return None
        if code is None:
            return str(message)
        return f"IBKR[{code}] {message}"

    def record_error(
        self,
        message: str,
        code: Optional[int] = None,
        req_id: Optional[int] = None,
    ) -> None:
        clean_message = str(message).strip() if message is not None else ""
        if not clean_message:
            return
        payload: dict[str, Any] = {"message": clean_message, "_ts": monotonic()}
        if code is not None:
            payload["code"] = int(code)
        if req_id is not None:
            payload["req_id"] = int(req_id)
        with self._error_lock:
            self._last_error = payload

    def get_client(self) -> Optional[Any]:
        """Return connected IB client, otherwise None."""
        return self._ib if self.is_connected() else None

    def run_with_client(self, operation: Callable[[Any], T]) -> Optional[T]:
        """
        Execute `operation(ib_client)` on the dedicated IB worker thread.
        Returns None when disconnected or on failure.
        """
        if not self.is_connected():
            return None

        def _execute() -> Optional[T]:
            ib_client = self._ib
            if ib_client is None or not self._safe_is_connected(ib_client):
                self._connected = False
                return None
            return operation(ib_client)

        try:
            return self._run_in_worker(_execute, timeout=self.timeout + 10)
        except Exception as exc:
            logger.warning("ibkr_client_operation_failed", error=str(exc))
            self.record_error(message=str(exc))
            self._connected = False
            try:
                self._run_in_worker(self._disconnect_impl, True, timeout=5)
            except Exception:
                # ignore cleanup failures; caller already gets None
                try:
                    self._disconnect_impl(reset_client=True)
                except Exception:
                    pass
            return None

    def _init_worker_context(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_loop = loop
        self._worker_thread_id = threading.get_ident()

    def _run_in_worker(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        timeout = kwargs.pop("timeout", None)
        if self._worker_thread_id == threading.get_ident():
            return fn(*args, **kwargs)
        future = self._executor.submit(fn, *args, **kwargs)
        self._track_worker_future(future)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            try:
                future.cancel()
            except Exception:
                pass
            timeout_label = timeout if timeout is not None else "unknown"
            message = f"IBKR worker operation timeout ({timeout_label}s)"
            self.record_error(message=message)
            logger.warning("ibkr_worker_operation_timeout", timeout=timeout)
            raise TimeoutError(message) from exc

    def _connect_impl(self) -> bool:
        if self._ib is None:
            self._ib = IB_CLASS()

        if self._safe_is_connected(self._ib):
            self._connected = True
            return True

        try:
            self._ib.connect(
                self.host,
                self.port,
                clientId=self.client_id,
                timeout=self.timeout,
            )
            self._attach_error_handler(self._ib)

            try:
                self._ib.reqMarketDataType(3)  # Delayed market data
            except Exception as exc:
                logger.warning("ibkr_set_market_data_type_failed", error=str(exc))

            self._connected = self._safe_is_connected(self._ib)
            return self._connected
        except Exception as exc:
            self.record_error(message=str(exc))
            logger.warning("ibkr_connect_failed", error=str(exc))
            self._disconnect_impl(reset_client=True)
            return False

    def _disconnect_impl(self, reset_client: bool = False) -> None:
        try:
            if self._ib is not None:
                self._ib.disconnect()
        except Exception as exc:
            logger.warning("ibkr_disconnect_failed", error=str(exc))
        finally:
            self._connected = False
            if reset_client:
                self._ib = None
                self._error_handler_attached = False

    def _track_worker_future(self, future: Any) -> None:
        with self._worker_state_lock:
            self._pending_worker_futures += 1

        def _on_done(_future: Any) -> None:
            with self._worker_state_lock:
                self._pending_worker_futures = max(0, self._pending_worker_futures - 1)

        future.add_done_callback(_on_done)

    def _is_worker_busy(self) -> bool:
        with self._worker_state_lock:
            return self._pending_worker_futures > 0

    @staticmethod
    def _safe_is_connected(ib_client: Any) -> bool:
        try:
            return bool(ib_client and ib_client.isConnected())
        except Exception:
            return False

    def _attach_error_handler(self, ib_client: Any) -> None:
        if self._error_handler_attached:
            return
        error_event = getattr(ib_client, "errorEvent", None)
        if error_event is None:
            return
        try:
            error_event += self._handle_ib_error_event
            self._error_handler_attached = True
        except Exception as exc:
            logger.warning("ibkr_attach_error_handler_failed", error=str(exc))

    def _handle_ib_error_event(
        self,
        req_id: Any,
        error_code: Any,
        error_string: Any,
        contract: Any = None,
    ) -> None:
        try:
            code = int(error_code)
        except Exception:
            code = None
        try:
            req = int(req_id)
        except Exception:
            req = None

        message = str(error_string or "").strip()
        symbol = getattr(contract, "symbol", None) if contract is not None else None
        if message and symbol and symbol not in message:
            message = f"{message} [{symbol}]"

        # Connectivity info/warnings from IB; keep logs clean and avoid overwriting actionable errors.
        if code in {2104, 2106, 2107, 2158}:
            return
        if not message:
            return

        self.record_error(message=message, code=code, req_id=req)

        if code in {1100, 1300}:
            self._connected = False

    def __enter__(self) -> "IBKRConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
