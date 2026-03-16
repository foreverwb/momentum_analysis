from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import structlog
from sqlalchemy.orm import Session

from app.core.broker_config import load_broker_config
from app.core.time_utils import utc_now_naive
from app.models import RefreshJob, SessionLocal

logger = structlog.get_logger(__name__)

SessionFactory = Callable[[], Session]


def _utc_now() -> datetime:
    return utc_now_naive()


def _normalize_symbol(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _dedupe_symbols(values: List[Any]) -> List[str]:
    deduped: List[str] = []
    for value in values:
        normalized = _normalize_symbol(value)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _job_summary_status(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "success"
    item_statuses = [str(item.get("status") or "").lower() for item in results]
    if all(status == "snapshot" for status in item_statuses):
        return "snapshot"
    if all(status in {"success", "snapshot"} for status in item_statuses):
        return "success"
    if all(status == "error" for status in item_statuses):
        return "failed"
    return "partial_success"


class RefreshJobManager:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        serial_gap_seconds: Optional[int] = None,
    ) -> None:
        cfg = load_broker_config()
        self._session_factory = session_factory
        self._serial_gap_seconds = max(
            0,
            int(
                cfg.refresh.serial_gap_seconds
                if serial_gap_seconds is None
                else serial_gap_seconds
            ),
        )
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._queued_job_ids: set[int] = set()
        self._running_job_id: Optional[int] = None
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._start_lock = asyncio.Lock()

    async def ensure_started(self) -> None:
        async with self._start_lock:
            if self._worker_task is not None and not self._worker_task.done():
                return
            self._recover_unfinished_jobs()
            self._worker_task = asyncio.create_task(self._run_worker())
            logger.info("refresh_job_worker_started")

    async def shutdown(self) -> None:
        worker = self._worker_task
        self._worker_task = None
        if worker is None:
            return
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        self._running_job_id = None
        self._queued_job_ids.clear()
        logger.info("refresh_job_worker_stopped")

    async def enqueue_etfs_job(self, symbols: List[Any], source: str = "cli") -> Dict[str, Any]:
        normalized_symbols = _dedupe_symbols(symbols)
        if not normalized_symbols:
            raise ValueError("symbols 不能为空")
        job = self._create_job(
            job_type="etfs",
            source=source,
            payload={"symbols": normalized_symbols},
            progress_total=len(normalized_symbols),
        )
        await self.ensure_started()
        self._queue_job_id(job.id)
        return self.get_job(job.id) or {}

    async def enqueue_holdings_job(self, items: List[Dict[str, Any]], source: str = "cli") -> Dict[str, Any]:
        normalized_items: List[Dict[str, Any]] = []
        for item in items:
            symbol = _normalize_symbol(item.get("symbol"))
            if not symbol:
                continue
            coverage_type = str(item.get("coverage_type") or "top").strip().lower()
            coverage_value_raw = item.get("coverage_value", 20)
            try:
                coverage_value = int(coverage_value_raw)
            except (TypeError, ValueError):
                coverage_value = 20
            if coverage_type == "all":
                coverage_value = 0
            elif coverage_value <= 0:
                coverage_value = 20
            related_etf_symbols = _dedupe_symbols(item.get("related_etf_symbols") or [])
            normalized_items.append(
                {
                    "symbol": symbol,
                    "coverage_type": coverage_type,
                    "coverage_value": coverage_value,
                    "related_etf_symbols": related_etf_symbols,
                }
            )

        if not normalized_items:
            raise ValueError("holdings items 不能为空")

        job = self._create_job(
            job_type="holdings",
            source=source,
            payload={"items": normalized_items},
            progress_total=len(normalized_items),
        )
        await self.ensure_started()
        self._queue_job_id(job.id)
        return self.get_job(job.id) or {}

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self._session_factory() as db:
            job = db.query(RefreshJob).filter(RefreshJob.id == job_id).first()
            if job is None:
                return None
            return self._serialize_job(db, job)

    def list_jobs(self, *, limit: int = 20, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._session_factory() as db:
            query = db.query(RefreshJob)
            if status:
                query = query.filter(RefreshJob.status == status.strip().lower())
            rows = query.order_by(RefreshJob.created_at.desc(), RefreshJob.id.desc()).limit(limit).all()
            return [self._serialize_job(db, row) for row in rows]

    def _create_job(
        self,
        *,
        job_type: str,
        source: str,
        payload: Dict[str, Any],
        progress_total: int,
    ) -> RefreshJob:
        with self._session_factory() as db:
            job = RefreshJob(
                job_type=job_type,
                status="pending",
                source=source,
                payload=payload,
                progress_total=max(0, int(progress_total)),
                progress_completed=0,
                progress_failed=0,
                message="任务已进入队列",
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            return job

    def _recover_unfinished_jobs(self) -> None:
        with self._session_factory() as db:
            unfinished_jobs = db.query(RefreshJob).filter(
                RefreshJob.status.in_(["pending", "running"])
            ).order_by(RefreshJob.created_at.asc(), RefreshJob.id.asc()).all()

            for job in unfinished_jobs:
                if job.status == "running":
                    job.status = "pending"
                    job.started_at = None
                    job.current_item = None
                    job.message = "服务重启后恢复排队"
            if unfinished_jobs:
                db.commit()

            for job in unfinished_jobs:
                self._queue_job_id(job.id)

    def _queue_job_id(self, job_id: int) -> None:
        if job_id == self._running_job_id or job_id in self._queued_job_ids:
            return
        self._queued_job_ids.add(job_id)
        self._queue.put_nowait(job_id)

    async def _run_worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            self._queued_job_ids.discard(job_id)
            self._running_job_id = job_id
            try:
                await self._process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("refresh_job_worker_failed", job_id=job_id, error=str(exc))
                self._mark_job_failed(job_id, str(exc))
            finally:
                self._running_job_id = None
                self._queue.task_done()

    async def _process_job(self, job_id: int) -> None:
        with self._session_factory() as db:
            job = db.query(RefreshJob).filter(RefreshJob.id == job_id).first()
            if job is None or job.status in {"completed", "failed", "cancelled"}:
                return

            job.status = "running"
            job.started_at = job.started_at or _utc_now()
            job.completed_at = None
            job.error = None
            job.current_item = None
            job.message = "任务开始执行"
            db.commit()

            if job.job_type == "etfs":
                await self._run_etfs_job(db, job)
            elif job.job_type == "holdings":
                await self._run_holdings_job(db, job)
            else:
                raise ValueError(f"Unsupported refresh job type: {job.job_type}")

    async def _run_etfs_job(self, db: Session, job: RefreshJob) -> None:
        from app.api.etfs import refresh_etf_data

        symbols = _dedupe_symbols((job.payload or {}).get("symbols") or [])
        results: List[Dict[str, Any]] = []
        failures = 0

        for index, symbol in enumerate(symbols, start=1):
            job.current_item = symbol
            job.message = f"正在刷新 ETF {symbol} ({index}/{len(symbols)})"
            db.commit()

            try:
                result = await refresh_etf_data(symbol, db)
            except Exception as exc:
                failures += 1
                result = {
                    "symbol": symbol,
                    "status": "error",
                    "message": str(exc),
                }

            results.append(result)
            job.progress_completed = index
            job.progress_failed = failures
            job.result = {
                "items": results,
                "summary_status": _job_summary_status(results),
            }
            job.message = f"已完成 {index}/{len(symbols)}"
            db.commit()

            if index < len(symbols) and self._serial_gap_seconds > 0:
                await asyncio.sleep(self._serial_gap_seconds)

        self._finalize_job(db, job, results)

    async def _run_holdings_job(self, db: Session, job: RefreshJob) -> None:
        from app.api.etfs import HoldingsCoverageRequest, refresh_holdings_by_coverage

        items = (job.payload or {}).get("items") or []
        results: List[Dict[str, Any]] = []
        failures = 0

        for index, item in enumerate(items, start=1):
            symbol = _normalize_symbol(item.get("symbol")) or ""
            coverage_type = str(item.get("coverage_type") or "top").strip().lower()
            coverage_value = int(item.get("coverage_value") or 0)
            coverage_label = (
                "all" if coverage_type == "all" else f"{coverage_type}{coverage_value}"
            )

            job.current_item = symbol
            job.message = f"正在刷新 holdings {symbol} ({coverage_label}) {index}/{len(items)}"
            db.commit()

            try:
                request = HoldingsCoverageRequest(
                    coverage_type=coverage_type,
                    coverage_value=coverage_value,
                    related_etf_symbols=item.get("related_etf_symbols") or [],
                )
                result = await refresh_holdings_by_coverage(symbol, request, db)
            except Exception as exc:
                failures += 1
                result = {
                    "symbol": symbol,
                    "status": "error",
                    "coverage": coverage_label,
                    "message": str(exc),
                }

            results.append(result)
            job.progress_completed = index
            job.progress_failed = failures
            job.result = {
                "items": results,
                "summary_status": _job_summary_status(results),
            }
            job.message = f"已完成 {index}/{len(items)}"
            db.commit()

            if index < len(items) and self._serial_gap_seconds > 0:
                await asyncio.sleep(self._serial_gap_seconds)

        self._finalize_job(db, job, results)

    def _finalize_job(self, db: Session, job: RefreshJob, results: List[Dict[str, Any]]) -> None:
        summary_status = _job_summary_status(results)
        total = len(results)
        failures = int(job.progress_failed or 0)
        completed = total - failures

        if summary_status == "snapshot":
            message = f"任务完成，{total} 项均命中冷却快照"
        elif summary_status == "failed":
            message = f"任务完成，{total} 项全部失败"
        elif summary_status == "partial_success":
            message = f"任务完成，成功 {completed} 项，失败 {failures} 项"
        else:
            message = f"任务完成，成功 {completed} 项"

        job.status = "completed"
        job.current_item = None
        job.message = message
        job.completed_at = _utc_now()
        job.result = {
            "items": results,
            "summary_status": summary_status,
            "completed": completed,
            "failed": failures,
            "total": total,
        }
        db.commit()

    def _mark_job_failed(self, job_id: int, error: str) -> None:
        with self._session_factory() as db:
            job = db.query(RefreshJob).filter(RefreshJob.id == job_id).first()
            if job is None:
                return
            job.status = "failed"
            job.error = error
            job.current_item = None
            job.message = error
            job.completed_at = _utc_now()
            db.commit()

    def _serialize_job(self, db: Session, job: RefreshJob) -> Dict[str, Any]:
        queue_position = None
        if job.status == "pending":
            ahead_count = db.query(RefreshJob).filter(
                RefreshJob.status == "pending",
                RefreshJob.id < job.id,
            ).count()
            queue_position = ahead_count + (1 if self._running_job_id is not None else 0) + 1

        return {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "source": job.source,
            "payload": job.payload,
            "result": job.result,
            "error": job.error,
            "progress_total": job.progress_total,
            "progress_completed": job.progress_completed,
            "progress_failed": job.progress_failed,
            "current_item": job.current_item,
            "message": job.message,
            "queue_position": queue_position,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }


_refresh_job_manager: Optional[RefreshJobManager] = None


def get_refresh_job_manager() -> RefreshJobManager:
    global _refresh_job_manager
    if _refresh_job_manager is None:
        _refresh_job_manager = RefreshJobManager()
    return _refresh_job_manager


def reset_refresh_job_manager() -> None:
    global _refresh_job_manager
    _refresh_job_manager = None
