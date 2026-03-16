import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base
from app.services.refresh_jobs import RefreshJobManager


async def _wait_for_job_completion(manager: RefreshJobManager, job_id: int, timeout: float = 2.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        job = manager.get_job(job_id)
        if job and job.get("status") in {"completed", "failed"}:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout} 秒内完成")


@pytest_asyncio.fixture()
async def refresh_job_manager(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    manager = RefreshJobManager(session_factory=TestingSessionLocal, serial_gap_seconds=0)
    monkeypatch.setattr("app.api.refresh_jobs.get_refresh_job_manager", lambda: manager)

    try:
        yield manager
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_refresh_job_manager_runs_etfs_serially(monkeypatch, refresh_job_manager: RefreshJobManager):
    calls = []

    async def fake_refresh(symbol, db):
        calls.append(symbol)
        await asyncio.sleep(0.01)
        return {
            "symbol": symbol,
            "status": "success",
            "message": f"{symbol} ok",
        }

    monkeypatch.setattr("app.api.etfs.refresh_etf_data", fake_refresh)

    first_job = await refresh_job_manager.enqueue_etfs_job(["XLK", "XLF"], source="test")
    second_job = await refresh_job_manager.enqueue_etfs_job(["SOXX"], source="test")

    first_result = await _wait_for_job_completion(refresh_job_manager, first_job["id"])
    second_result = await _wait_for_job_completion(refresh_job_manager, second_job["id"])

    assert calls == ["XLK", "XLF", "SOXX"]
    assert first_result["status"] == "completed"
    assert first_result["result"]["summary_status"] == "success"
    assert second_result["status"] == "completed"
    assert second_result["result"]["summary_status"] == "success"


@pytest.mark.asyncio
async def test_enqueue_holdings_refresh_job_api_accepts_and_completes(
    monkeypatch,
    refresh_job_manager: RefreshJobManager,
):
    calls = []

    async def fake_refresh_holdings(symbol, request, db):
        calls.append((symbol, request.coverage_type, request.coverage_value))
        return {
            "symbol": symbol,
            "coverage": (
                "all" if request.coverage_type == "all"
                else f"{request.coverage_type}{request.coverage_value}"
            ),
            "status": "success",
        }

    monkeypatch.setattr("app.api.etfs.refresh_holdings_by_coverage", fake_refresh_holdings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/refresh-jobs/holdings",
            json={
                "items": [
                    {"symbol": "XLK", "coverage_type": "top", "coverage_value": 20},
                    {"symbol": "SOXX", "coverage_type": "all", "coverage_value": 0},
                ]
            },
        )

    assert response.status_code == 202
    payload = response.json()
    job_id = payload["job"]["id"]
    assert payload["status"] == "accepted"
    assert payload["job"]["job_type"] == "holdings"

    completed_job = await _wait_for_job_completion(refresh_job_manager, job_id)

    assert calls == [("XLK", "top", 20), ("SOXX", "all", 0)]
    assert completed_job["status"] == "completed"
    assert completed_job["result"]["summary_status"] == "success"
