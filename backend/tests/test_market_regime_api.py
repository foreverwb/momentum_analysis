from httpx import AsyncClient, ASGITransport
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


def _override_get_db():
    yield _EmptySession()


@pytest.mark.asyncio
async def test_market_regime_no_data_returns_200_with_cors_headers():
    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/market/regime",
                headers={"Origin": "http://localhost:5173"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    data = response.json()
    assert data["status"] == "NO_DATA"
    assert data["indicators"] is None
