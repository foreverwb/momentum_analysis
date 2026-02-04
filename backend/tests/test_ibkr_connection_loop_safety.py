"""
Regression tests for IBKR connection loop/thread safety.
"""

from __future__ import annotations

import threading

import pytest

import app.services.broker.ibkr.connection as connection_module
from app.services.broker.ibkr.connection import IBKRConnection


class _FakeIB:
    def __init__(self):
        self._connected = False
        self.connect_thread_id = None
        self.market_data_type = None

    def connect(self, host: str, port: int, clientId: int, timeout: int):
        self.connect_thread_id = threading.get_ident()
        self._connected = True

    def disconnect(self):
        self._connected = False

    def isConnected(self) -> bool:
        return self._connected

    def reqMarketDataType(self, market_data_type: int):
        self.market_data_type = market_data_type


@pytest.mark.asyncio
async def test_connect_uses_worker_thread_inside_running_event_loop(monkeypatch):
    monkeypatch.setattr(connection_module, "is_ibkr_dependency_available", lambda: True)
    monkeypatch.setattr(connection_module, "IB_CLASS", _FakeIB)

    connection = IBKRConnection(host="127.0.0.1", port=4002, client_id=1)
    caller_thread = threading.get_ident()

    try:
        assert connection.connect() is True

        ib_client = connection.get_client()
        assert ib_client is not None
        assert ib_client.connect_thread_id is not None
        assert ib_client.connect_thread_id != caller_thread
        assert ib_client.market_data_type == 3

        operation_thread = connection.run_with_client(lambda _ib: threading.get_ident())
        assert operation_thread == ib_client.connect_thread_id
    finally:
        connection.disconnect()

    assert connection.is_connected() is False


def test_connection_records_ibkr_error_event_payload() -> None:
    connection = IBKRConnection()

    connection._handle_ib_error_event(
        req_id=4,
        error_code=162,
        error_string="Trading TWS session is connected from a different IP address",
        contract=None,
    )

    payload = connection.get_last_error()
    assert payload is not None
    assert payload.get("code") == 162
    assert "different IP address" in str(payload.get("message"))


def test_is_connected_returns_cached_state_when_worker_busy(monkeypatch) -> None:
    connection = IBKRConnection()
    connection._ib = object()
    connection._connected = True
    connection._pending_worker_futures = 1

    def _should_not_run(*_args, **_kwargs):
        raise AssertionError("_run_in_worker should not be called when worker is busy")

    monkeypatch.setattr(connection, "_run_in_worker", _should_not_run)

    assert connection.is_connected() is True
