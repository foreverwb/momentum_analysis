from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.models import get_db


class _EmptyQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


class _EmptySession:
    def query(self, *_args, **_kwargs):
        return _EmptyQuery()

    def add(self, *_args, **_kwargs):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def _override_get_db():
    yield _EmptySession()


class _SlowOrchestrator:
    def get_broker_status(self):
        return {"ibkr": {"is_connected": True}}

    async def connect_ibkr(self):
        return True

    async def get_regime_summary(self):
        await asyncio.sleep(0.05)
        return {
            "status": "A",
            "regime_text": "RISK_ON 满火力",
            "spy": {"price": 1, "sma20": 1, "sma50": 1, "return_20d": 0, "sma20_slope": 0},
            "vix": 15,
            "indicators": {
                "price_above_sma20": True,
                "price_above_sma50": True,
                "sma20_slope": 0,
                "sma20_slope_positive": False,
                "sma20_above_sma50": False,
                "return_20d": 0,
            },
        }


@pytest.mark.asyncio
async def test_market_regime_refresh_returns_timeout_payload(monkeypatch):
    import app.api.market as market_module
    import app.services.orchestrator as orchestrator_module

    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(market_module, "REGIME_SUMMARY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(orchestrator_module, "get_orchestrator", lambda: _SlowOrchestrator())

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/market/regime?refresh=true",
                headers={"Origin": "http://localhost:5173"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ERROR"
    assert "timeout" in str(payload.get("error", "")).lower()

