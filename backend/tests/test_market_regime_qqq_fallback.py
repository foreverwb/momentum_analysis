from __future__ import annotations

from datetime import date, timedelta

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.models import get_db


class _PriceRow:
    def __init__(self, row_date: date, close: float):
        self.date = row_date
        self.close = close


class _SnapshotQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


class _PriceHistoryQuery:
    def __init__(self, rows_desc):
        self._rows_desc = rows_desc

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows_desc


class _FakeSession:
    def __init__(self, rows_desc):
        self._rows_desc = rows_desc
        self.added = []

    def query(self, model, *_args, **_kwargs):
        model_name = getattr(model, "__name__", "")
        if model_name == "PriceHistory":
            return _PriceHistoryQuery(self._rows_desc)
        return _SnapshotQuery()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class _FallbackOrchestrator:
    def get_broker_status(self):
        return {"ibkr": {"is_connected": True}}

    async def connect_ibkr(self):
        return True

    async def get_regime_summary(self):
        return {
            "status": "B",
            "regime_text": "NEUTRAL 半火力",
            "spy": {
                "price": 600.0,
                "sma20": 595.0,
                "sma50": 590.0,
                "return_20d": 0.01,
                "sma20_slope": 0.5,
            },
            "qqq": None,
            "vix": 18.0,
            "indicators": {
                "price_above_sma20": True,
                "price_above_sma50": True,
                "sma20_slope": 0.5,
                "sma20_slope_positive": True,
                "sma20_above_sma50": True,
                "return_20d": 0.01,
            },
        }

    async def get_spy_data(self, symbol: str = "SPY", sma_periods=None):
        return None


def _build_price_rows_desc(count: int = 80):
    start = date.today() - timedelta(days=count - 1)
    rows_asc = [_PriceRow(start + timedelta(days=i), 100.0 + i) for i in range(count)]
    return list(reversed(rows_asc))


@pytest.mark.asyncio
async def test_market_regime_refresh_falls_back_to_price_history_for_qqq(monkeypatch):
    import app.services.orchestrator as orchestrator_module

    session = _FakeSession(_build_price_rows_desc())

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(orchestrator_module, "get_orchestrator", lambda: _FallbackOrchestrator())

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/market/regime?refresh=true")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    qqq = payload.get("qqq")

    assert isinstance(qqq, dict)
    assert qqq.get("price") is not None
    assert qqq.get("sma20") is not None
    assert qqq.get("sma50") is not None
    assert qqq.get("return_20d") is not None
    assert qqq.get("sma20_slope") is not None
