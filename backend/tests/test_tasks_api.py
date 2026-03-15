import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models import ETF, Task, Base, get_db


@pytest.fixture()
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    db.add_all([
        ETF(symbol="XLK", name="Technology", type="sector", rank=1, score=82),
        ETF(symbol="XLF", name="Financials", type="sector", rank=2, score=79),
        ETF(symbol="SOXX", name="Semiconductors", type="industry", parent_sector="XLK", rank=1, score=85),
        ETF(symbol="IGV", name="Software", type="industry", parent_sector="XLK", rank=2, score=78),
        ETF(symbol="KRE", name="Regional Banks", type="industry", parent_sector="XLF", rank=3, score=74),
        Task(title="Rotation", type="rotation", base_index="SPY", etfs=["XLK"]),
        Task(title="Drilldown", type="drilldown", base_index="SPY", sector="XLK", etfs=["SOXX"]),
    ])
    db.commit()

    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def override_db(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_add_sector_etf_to_rotation_task(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/tasks/1/etfs", json={"etfs": ["XLF"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["etfs"] == ["XLK", "XLF"]
    assert payload["type"] == "rotation"


@pytest.mark.asyncio
async def test_rotation_task_rejects_industry_etf_addition(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/tasks/1/etfs", json={"etfs": ["SOXX"]})

    assert response.status_code == 400
    assert "板块轮动任务只能添加板块 ETF" in response.json()["detail"]


@pytest.mark.asyncio
async def test_drilldown_task_accepts_same_sector_industry_etf(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/tasks/2/etfs", json={"etfs": ["IGV"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["sector"] == "XLK"
    assert payload["etfs"] == ["SOXX", "IGV"]


@pytest.mark.asyncio
async def test_drilldown_task_rejects_other_sector_industry_etf(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/tasks/2/etfs", json={"etfs": ["KRE"]})

    assert response.status_code == 400
    assert "只能添加属于板块 XLK 的行业 ETF" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rotation_task_rejects_industry_etf(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/tasks",
            json={
                "title": "Invalid Rotation",
                "type": "rotation",
                "baseIndex": "SPY",
                "sector": None,
                "etfs": ["SOXX"],
            },
        )

    assert response.status_code == 400
    assert "板块轮动任务只能添加板块 ETF" in response.json()["detail"]
