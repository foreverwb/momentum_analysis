"""
Ensure regime summary computation does not block the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import app.services.calculators.regime_gate as regime_gate_module
from app.services.orchestrator import DataOrchestrator


class _ConnectedConnection:
    def is_connected(self) -> bool:
        return True


class _DummyIB:
    pass


class _SlowRegimeGateCalculator:
    def __init__(self, _ibkr):
        self._ibkr = _ibkr

    def calculate_regime(self):
        time.sleep(0.2)
        return {
            "status": "UNKNOWN",
            "regime": "UNKNOWN",
            "fire_power": "未知",
            "data": None,
        }

    def get_regime_summary(self):
        time.sleep(0.2)
        return {
            "status": "UNKNOWN",
            "regime_text": "未知",
            "spy": None,
            "vix": None,
            "indicators": None,
        }


@pytest.mark.asyncio
async def test_get_regime_summary_runs_in_background_thread(monkeypatch):
    monkeypatch.setattr(regime_gate_module, "RegimeGateCalculator", _SlowRegimeGateCalculator)

    orchestrator = DataOrchestrator()
    orchestrator._broker_status["ibkr"].is_connected = True
    orchestrator._ibkr_connection = _ConnectedConnection()
    orchestrator._ibkr = _DummyIB()

    regime_task = asyncio.create_task(orchestrator.get_regime_summary())
    ping_task = asyncio.create_task(asyncio.sleep(0.01, result="ok"))

    done, _pending = await asyncio.wait({regime_task, ping_task}, timeout=0.08)

    assert ping_task in done
    assert ping_task.result() == "ok"

    result = await regime_task
    assert result.get("status") == "UNKNOWN"

