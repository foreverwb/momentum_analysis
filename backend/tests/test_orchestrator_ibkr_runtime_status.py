"""
Regression tests for IBKR runtime-status synchronization in orchestrator.
"""

from __future__ import annotations

import pytest

from app.services.orchestrator import DataOrchestrator


class _RuntimeDisconnectedConnection:
    def is_connected(self) -> bool:
        return False


class _ShouldNotBeUsedIBKR:
    def is_connected(self) -> bool:
        return False

    def get_price_data(self, *_args, **_kwargs):
        raise AssertionError("regime should not request price data when runtime disconnected")

    def get_vix(self):
        raise AssertionError("regime should not request vix when runtime disconnected")


@pytest.mark.asyncio
async def test_market_regime_falls_back_when_runtime_connection_is_lost() -> None:
    orchestrator = DataOrchestrator()
    orchestrator._broker_status["ibkr"].is_connected = True
    orchestrator._ibkr_connection = _RuntimeDisconnectedConnection()
    orchestrator._ibkr = _ShouldNotBeUsedIBKR()

    result = await orchestrator.get_market_regime()

    assert result.get("error") == "IBKR not connected"
    assert orchestrator._broker_status["ibkr"].is_connected is False


def test_get_broker_status_syncs_runtime_disconnected_state() -> None:
    orchestrator = DataOrchestrator()
    orchestrator._broker_status["ibkr"].is_connected = True
    orchestrator._ibkr_connection = _RuntimeDisconnectedConnection()

    status = orchestrator.get_broker_status()

    assert status["ibkr"]["is_connected"] is False
    assert status["ibkr"]["last_error"] in {"Connection lost", "Disconnected"}

