from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.refresh_jobs import get_refresh_job_manager

router = APIRouter(prefix="/api/refresh-jobs", tags=["RefreshJobs"])


class RefreshEtfsJobRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, description="需要刷新的 ETF 列表")
    source: str = Field("cli", description="触发来源")
    refresh_source: Literal["all", "ibkr", "futu"] = Field("all", description="刷新数据源")


class RefreshHoldingsJobItem(BaseModel):
    symbol: str = Field(..., description="ETF 符号")
    coverage_type: Literal["top", "weight", "all"] = Field("top", description="覆盖方式")
    coverage_value: int = Field(20, description="覆盖值；all 时忽略")
    related_etf_symbols: List[str] = Field(default_factory=list, description="同任务中相关 ETF")


class RefreshHoldingsJobRequest(BaseModel):
    items: List[RefreshHoldingsJobItem] = Field(..., min_length=1, description="需要串行刷新的 holdings 列表")
    source: str = Field("cli", description="触发来源")
    refresh_source: Literal["all", "ibkr", "futu"] = Field("all", description="刷新数据源")
    exclude_symbols: List[str] = Field(default_factory=list, description="允许缺少最新导入数据的 ticker 列表")


@router.post("/etfs", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_etf_refresh_job(request: RefreshEtfsJobRequest) -> dict:
    manager = get_refresh_job_manager()
    try:
        job = await manager.enqueue_etfs_job(
            request.symbols,
            source=request.source,
            refresh_source=request.refresh_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "accepted",
        "message": "ETF refresh 任务已入队",
        "job": job,
    }


@router.post("/holdings", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_holdings_refresh_job(request: RefreshHoldingsJobRequest) -> dict:
    manager = get_refresh_job_manager()
    try:
        job = await manager.enqueue_holdings_job(
            [item.model_dump() for item in request.items],
            source=request.source,
            refresh_source=request.refresh_source,
            exclude_symbols=request.exclude_symbols,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "accepted",
        "message": "Holdings refresh 任务已入队",
        "job": job,
    }


@router.get("/{job_id}")
async def get_refresh_job(job_id: int) -> dict:
    manager = get_refresh_job_manager()
    job = manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Refresh job not found")
    return job


@router.get("")
async def list_refresh_jobs(
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
) -> dict:
    manager = get_refresh_job_manager()
    return {
        "items": manager.list_jobs(limit=limit, status=status_filter),
    }
