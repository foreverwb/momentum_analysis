"""
Task API 端点
从数据库读取任务数据（已移除 mock 数据）
支持 WebSocket 实时进度推送和批量刷新功能
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date as date_type, timedelta, timezone
import asyncio
import json

import pandas as pd

from app.models import get_db, Task, ETF, ETFHolding, Stock, PriceHistory, ImportedData, IVData, ScoreSnapshot
from app.schemas import TaskCreate, TaskEtfsAdd
from app.api.etfs import refresh_etf_data, ETF_REFRESH_COOLDOWN_MINUTES
from app.api.series_utils import build_metric_series, build_sma20_comparison_series

router = APIRouter()


def format_task_response(task: Task) -> dict:
    """格式化任务响应数据"""
    base_indices = _normalize_base_indices(task.base_index)
    return {
        "id": task.id,
        "title": task.title,
        "type": task.type,
        "baseIndex": ",".join(base_indices),
        "baseIndices": base_indices,
        "sector": task.sector,
        "etfs": task.etfs or [],
        "createdAt": task.created_at.strftime("%Y-%m-%d") if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
    }


def _parse_coverage(coverage: str) -> Tuple[str, int]:
    coverage = (coverage or "top20").lower()
    if coverage == "all":
        return "all", 0
    if coverage.startswith("top"):
        return "top", int(coverage.replace("top", "") or 20)
    if coverage.startswith("weight"):
        return "weight", int(coverage.replace("weight", "") or 70)
    return "top", 20


def _normalize_symbols(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item).strip().upper() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip().upper() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [item.strip().upper() for item in text.split(',') if item.strip()]
    return []


def _normalize_base_indices(raw: Any) -> List[str]:
    symbols = _normalize_symbols(raw)
    deduped: List[str] = []
    for symbol in symbols:
        if symbol and symbol not in deduped:
            deduped.append(symbol)
    return deduped or ["SPY"]


def _normalize_optional_symbol(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    normalized = str(raw).strip().upper()
    return normalized or None


def _dedupe_symbols(symbols: List[str]) -> List[str]:
    deduped: List[str] = []
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _validate_task_etfs(
    *,
    task_type: str,
    sector: Optional[str],
    etfs: Any,
    db: Session,
) -> Tuple[Optional[str], List[str]]:
    normalized_type = str(task_type or "").strip().lower()
    normalized_sector = _normalize_optional_symbol(sector)
    normalized_etfs = _dedupe_symbols(_normalize_symbols(etfs))

    if normalized_type not in {"rotation", "drilldown", "momentum"}:
        raise HTTPException(status_code=400, detail=f"Unsupported task type: {task_type}")

    if normalized_type in {"drilldown", "momentum"} and not normalized_sector:
        raise HTTPException(status_code=400, detail="该任务类型必须指定板块 ETF")

    if not normalized_etfs:
        return (None if normalized_type == "rotation" else normalized_sector, normalized_etfs)

    etf_rows = db.query(ETF).filter(func.upper(ETF.symbol).in_(normalized_etfs)).all()
    etf_by_symbol = {
        str(etf.symbol or "").strip().upper(): etf
        for etf in etf_rows
        if str(etf.symbol or "").strip()
    }

    missing_symbols = [symbol for symbol in normalized_etfs if symbol not in etf_by_symbol]
    if missing_symbols:
        raise HTTPException(status_code=400, detail=f"ETF 不存在: {', '.join(missing_symbols)}")

    if normalized_type == "rotation":
        invalid_symbols = [
            symbol for symbol in normalized_etfs
            if str(etf_by_symbol[symbol].type or "").strip().lower() != "sector"
        ]
        if invalid_symbols:
            raise HTTPException(
                status_code=400,
                detail=f"板块轮动任务只能添加板块 ETF: {', '.join(invalid_symbols)}",
            )
        return None, normalized_etfs

    invalid_symbols = [
        symbol for symbol in normalized_etfs
        if str(etf_by_symbol[symbol].type or "").strip().lower() != "industry"
    ]
    if invalid_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"当前任务类型只能添加行业 ETF: {', '.join(invalid_symbols)}",
        )

    wrong_sector_symbols = [
        symbol for symbol in normalized_etfs
        if _normalize_optional_symbol(etf_by_symbol[symbol].parent_sector) != normalized_sector
    ]
    if wrong_sector_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"只能添加属于板块 {normalized_sector} 的行业 ETF: {', '.join(wrong_sector_symbols)}",
        )

    return normalized_sector, normalized_etfs


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _format_beijing_time(value: Optional[datetime]) -> Optional[str]:
    dt = _coerce_datetime(value)
    if dt is None:
        return None
    return (dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def _task_monitored_etf_symbols(task: Task) -> List[str]:
    """
    返回任务详情页应监控的 ETF 列表。
    - 默认使用 task.etfs
    - drilldown 任务额外包含 task.sector（若存在），并置于首位
    """
    symbols = _normalize_symbols(task.etfs)
    if str(task.type or "").lower() == "drilldown" and task.sector:
        sector_symbol = str(task.sector).strip().upper()
        if sector_symbol:
            symbols = [sector_symbol] + symbols

    deduped: List[str] = []
    for symbol in symbols:
        if symbol and symbol not in deduped:
            deduped.append(symbol)
    return deduped


def _load_price_history(db: Session, symbol: str, min_rows: int = 60) -> Optional[pd.DataFrame]:
    rows = db.query(PriceHistory).filter(
        PriceHistory.symbol == symbol.upper()
    ).order_by(PriceHistory.date.asc()).all()

    if len(rows) < min_rows:
        return None

    return pd.DataFrame([
        {
            'date': r.date,
            'open': r.open,
            'high': r.high,
            'low': r.low,
            'close': r.close,
            'volume': r.volume
        }
        for r in rows
    ])


def _save_price_history(db: Session, symbol: str, df: pd.DataFrame, source: str = "ibkr") -> None:
    if df is None or df.empty:
        return
    existing_dates = {
        r.date for r in db.query(PriceHistory.date).filter(PriceHistory.symbol == symbol.upper()).all()
    }
    new_records = []
    for _, row in df.iterrows():
        row_date = row['date'].date() if hasattr(row['date'], 'date') else row['date']
        if row_date in existing_dates:
            continue
        new_records.append(PriceHistory(
            symbol=symbol.upper(),
            date=row_date,
            open=float(row.get('open', 0) or 0),
            high=float(row.get('high', 0) or 0),
            low=float(row.get('low', 0) or 0),
            close=float(row.get('close', 0) or 0),
            volume=int(row.get('volume', 0) or 0),
            source=source
        ))
    if new_records:
        db.add_all(new_records)


def _get_latest_import(db: Session, symbol: str, source: str) -> Optional[Dict[str, Any]]:
    record = db.query(ImportedData).filter(
        ImportedData.symbol == symbol.upper(),
        ImportedData.source == source
    ).order_by(ImportedData.date.desc()).first()
    return record.data if record else None


def _get_latest_iv(db: Session, symbol: str) -> Optional[Dict[str, Any]]:
    record = db.query(IVData).filter(
        IVData.symbol == symbol.upper()
    ).order_by(IVData.date.desc()).first()
    if not record:
        return None
    return {
        'iv30': record.iv30,
        'ivr': None
    }


def _compute_deltas(db: Session, symbol: str) -> Dict[str, Optional[float]]:
    snapshots = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == symbol.upper(),
        ScoreSnapshot.symbol_type == 'stock'
    ).order_by(ScoreSnapshot.date.desc()).limit(6).all()

    if not snapshots:
        return {"delta3d": None, "delta5d": None}

    current = snapshots[0].total_score or 0
    delta3d = None
    delta5d = None

    if len(snapshots) >= 4 and snapshots[3].total_score is not None:
        delta3d = round(current - snapshots[3].total_score, 2)
    if len(snapshots) >= 6 and snapshots[5].total_score is not None:
        delta5d = round(current - snapshots[5].total_score, 2)

    return {"delta3d": delta3d, "delta5d": delta5d}


@router.get("", response_model=List[dict])
async def get_tasks(db: Session = Depends(get_db)):
    """
    获取所有监控任务
    """
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    return [format_task_response(task) for task in tasks]


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    """
    根据 ID 获取单个任务
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return format_task_response(task)


@router.get("/{task_id}/trend-comparison", response_model=dict)
async def get_task_trend_comparison(
    task_id: int,
    period: int = Query(20, description="对比周期（交易日）: 5/20/63"),
    metric: str = Query("relative", description="指标: relative/sma20/return20d/score"),
    label_tz: str = Query("market", description="日期标签时区: market/beijing"),
    db: Session = Depends(get_db)
):
    """
    获取任务的走势对比数据

    返回:
    - dates: 日期标签
    - series: [{symbol, values}]
    """
    if period not in (5, 20, 63):
        raise HTTPException(status_code=400, detail="period must be one of 5, 20, 63")
    if metric not in ("relative", "sma20", "return20d", "score"):
        raise HTTPException(status_code=400, detail="metric must be one of relative, sma20, return20d, score")
    normalized_label_tz = (label_tz or "market").strip().lower()
    if normalized_label_tz not in ("market", "beijing"):
        raise HTTPException(status_code=400, detail="label_tz must be one of market, beijing")

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    symbols = _normalize_symbols(task.etfs)
    if task.sector:
        symbols.append(task.sector.upper())
    symbols.extend(_normalize_base_indices(task.base_index))
    symbols.extend(["SPY", "QQQ"])

    # 去重并保持顺序
    deduped: List[str] = []
    for symbol in symbols:
        if symbol and symbol not in deduped:
            deduped.append(symbol)

    if metric == "sma20":
        dates, price_series, sma20_series, deviation_series = build_sma20_comparison_series(
            db,
            deduped,
            period,
            label_tz=normalized_label_tz,
        )
        return {
            "task_id": task.id,
            "period": period,
            "metric": metric,
            "label_tz": normalized_label_tz,
            "symbols": deduped,
            "dates": dates,
            # 保持向后兼容：series 默认返回可读性更高的偏离度(%)
            "series": deviation_series,
            "price_series": price_series,
            "sma20_series": sma20_series,
            "deviation_series": deviation_series,
        }

    dates, series = build_metric_series(
        db,
        deduped,
        period,
        metric=metric,
        label_tz=normalized_label_tz,
    )

    return {
        "task_id": task.id,
        "period": period,
        "metric": metric,
        "label_tz": normalized_label_tz,
        "symbols": deduped,
        "dates": dates,
        "series": series
    }


@router.post("", response_model=dict)
async def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    """
    创建新的监控任务
    """
    base_indices = _normalize_base_indices(task.baseIndex)
    normalized_sector, normalized_etfs = _validate_task_etfs(
        task_type=task.type.value,
        sector=task.sector,
        etfs=task.etfs,
        db=db,
    )
    new_task = Task(
        title=task.title,
        type=task.type.value,
        base_index=",".join(base_indices),
        sector=normalized_sector,
        etfs=normalized_etfs,
        created_at=datetime.utcnow()
    )
    
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    
    return format_task_response(new_task)


@router.put("/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    task_update: TaskCreate,
    db: Session = Depends(get_db)
):
    """
    更新任务
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    base_indices = _normalize_base_indices(task_update.baseIndex)
    normalized_sector, normalized_etfs = _validate_task_etfs(
        task_type=task_update.type.value,
        sector=task_update.sector,
        etfs=task_update.etfs,
        db=db,
    )
    task.title = task_update.title
    task.type = task_update.type.value
    task.base_index = ",".join(base_indices)
    task.sector = normalized_sector
    task.etfs = normalized_etfs
    
    db.commit()
    db.refresh(task)
    
    return format_task_response(task)


@router.post("/{task_id}/etfs", response_model=dict)
async def add_task_etfs(
    task_id: int,
    payload: TaskEtfsAdd,
    db: Session = Depends(get_db)
):
    """
    向现有监控任务中追加 ETF
    """
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    _, requested_etfs = _validate_task_etfs(
        task_type=task.type,
        sector=task.sector,
        etfs=payload.etfs,
        db=db,
    )
    if not requested_etfs:
        raise HTTPException(status_code=400, detail="请至少选择一个 ETF")

    merged_etfs = _dedupe_symbols(_normalize_symbols(task.etfs) + requested_etfs)
    _, validated_etfs = _validate_task_etfs(
        task_type=task.type,
        sector=task.sector,
        etfs=merged_etfs,
        db=db,
    )

    task.etfs = validated_etfs
    task.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(task)

    return format_task_response(task)


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    """
    删除任务
    """
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()

    return {"message": "Task deleted successfully"}


@router.post("/{task_id}/refresh-all-etfs")
async def refresh_all_etfs(task_id: int, db: Session = Depends(get_db)):
    """
    批量刷新任务中的所有 ETF 数据

    此端点可与 WebSocket /refresh-stream 配合使用实时获取进度

    返回:
    {
      "status": "success|partial_success|error",
      "task_id": 1,
      "total": 3,
      "completed": 3,
      "failed": 0,
      "results": [
        {
          "symbol": "XLK",
          "status": "success",
          "score": 75.2,
          "completeness": 0.85,
          "message": "刷新成功",
          "data_sources": {"ibkr": true, "futu": true}
        }
      ],
      "message": "刷新完成: 3 成功, 0 失败"
    }
    """
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    etf_symbols = _task_monitored_etf_symbols(task)

    if not etf_symbols:
        refresh_finished_at = datetime.utcnow()
        task.updated_at = refresh_finished_at
        db.commit()
        return {
            "status": "success",
            "task_id": task_id,
            "total": 0,
            "completed": 0,
            "failed": 0,
            "results": [],
            "message": "任务中没有 ETF",
            "updated_at": refresh_finished_at.isoformat(),
        }

    results = []
    failed_count = 0

    for symbol in etf_symbols:
        try:
            result = await refresh_etf_data(symbol, db)
            results.append(result)
            result_status = str(result.get("status") or "").lower()
            if result_status not in {"success", "snapshot"}:
                failed_count += 1
        except Exception as e:
            failed_count += 1
            results.append({
                "symbol": symbol,
                "status": "error",
                "score": None,
                "completeness": None,
                "message": f"刷新失败: {str(e)}",
                "data_sources": {}
            })

    refresh_finished_at = datetime.utcnow()
    task.updated_at = refresh_finished_at
    db.commit()

    snapshot_results = [
        item for item in results
        if str(item.get("status") or "").lower() == "snapshot"
    ]
    all_snapshot = len(snapshot_results) == len(results) and len(results) > 0

    next_refresh_candidates: List[datetime] = []
    cooldown_minutes = ETF_REFRESH_COOLDOWN_MINUTES
    for item in snapshot_results:
        parsed = _coerce_datetime(item.get("next_refresh_at"))
        if parsed is not None:
            next_refresh_candidates.append(parsed)
        gate = item.get("refresh_gate")
        if isinstance(gate, dict):
            gate_minutes = gate.get("cooldown_minutes")
            if isinstance(gate_minutes, (int, float)):
                cooldown_minutes = int(gate_minutes)
    next_refresh_at = min(next_refresh_candidates) if next_refresh_candidates else None
    next_refresh_label = _format_beijing_time(next_refresh_at)
    if all_snapshot:
        summary_message = (
            f"已跳过刷新：IBKR 与 Futu 数据在 {cooldown_minutes} 分钟内已更新（{len(snapshot_results)} 个 ETF）。"
            + (f"下次可刷新时间（北京时间）{next_refresh_label}" if next_refresh_label else "")
        )
        summary_status = "snapshot"
        completed_count = len(etf_symbols)
        failed_count = 0
    else:
        summary_message = f"刷新完成: {len(etf_symbols) - failed_count} 成功, {failed_count} 失败"
        summary_status = "success" if failed_count == 0 else "partial_success"
        completed_count = len(etf_symbols) - failed_count

    return {
        "status": summary_status,
        "task_id": task_id,
        "total": len(etf_symbols),
        "completed": completed_count,
        "failed": failed_count,
        "results": results,
        "message": summary_message,
        "next_refresh_at": next_refresh_at.isoformat() if next_refresh_at else None,
        "updated_at": refresh_finished_at.isoformat(),
    }


@router.post("/{task_id}/refresh-stocks")
async def refresh_momentum_stocks(
    task_id: int,
    coverage: str = Query("top20", description="覆盖范围: top20/weight70 等"),
    limit: int = Query(50, description="返回的股票数量上限"),
    db: Session = Depends(get_db)
):
    """
    刷新动能股池数据（仅适用于 momentum 任务）
    - 根据任务内的行业 ETF holdings 获取股票列表
    - 计算动能评分与指标
    - 写入 stocks 表 + score_snapshots
    """
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.type != "momentum":
        raise HTTPException(status_code=400, detail="Only momentum tasks can refresh stocks")

    etf_symbols = [s.upper() for s in (task.etfs or []) if isinstance(s, str)]
    if not etf_symbols:
        return {
            "status": "success",
            "task_id": task_id,
            "updated": [],
            "message": "任务中没有行业 ETF"
        }

    coverage_type, coverage_value = _parse_coverage(coverage)

    # 确保 IBKR 连接可用（若需要拉取价格）
    from app.services.orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    broker_status = orchestrator.get_broker_status()
    if not broker_status.get("ibkr", {}).get("is_connected", False):
        try:
            await orchestrator.connect_ibkr()
        except Exception:
            pass
    ibkr_connected = orchestrator.get_broker_status().get("ibkr", {}).get("is_connected", False)

    # 预加载板块价格
    sector_symbol = task.sector.upper() if task.sector else None
    sector_df = None
    if sector_symbol:
        sector_df = _load_price_history(db, sector_symbol)
        if sector_df is None and ibkr_connected:
            try:
                fetched = await orchestrator.get_ohlcv_data(sector_symbol, "1 Y")
                if fetched is not None and not fetched.empty:
                    _save_price_history(db, sector_symbol, fetched)
                    sector_df = fetched
            except Exception:
                pass

    # 构建 holdings 清单（按权重最高保留）
    holdings_map: Dict[str, Dict[str, Any]] = {}
    for symbol in etf_symbols:
        etf = db.query(ETF).filter(ETF.symbol == symbol).first()
        if not etf:
            continue
        latest_date = db.query(func.max(ETFHolding.data_date)).filter(
            ETFHolding.etf_symbol == symbol
        ).scalar()
        if not latest_date:
            continue
        holdings = db.query(ETFHolding).filter(
            ETFHolding.etf_symbol == symbol,
            ETFHolding.data_date == latest_date
        ).order_by(ETFHolding.weight.desc()).all()

        filtered: List[ETFHolding] = []
        if coverage_type == "all":
            filtered = holdings
        elif coverage_type == "top":
            filtered = holdings[:coverage_value]
        else:
            total = 0.0
            for holding in holdings:
                filtered.append(holding)
                total += holding.weight
                if total >= coverage_value:
                    break

        for holding in filtered:
            ticker = holding.ticker.upper()
            if ticker not in holdings_map or holding.weight > holdings_map[ticker]["weight"]:
                holdings_map[ticker] = {
                    "holding": holding,
                    "etf": etf,
                    "weight": holding.weight
                }

    updated = []
    errors = []

    for ticker, context in holdings_map.items():
        holding = context["holding"]
        etf = context["etf"]

        price_df = _load_price_history(db, ticker)
        if price_df is None and ibkr_connected:
            try:
                fetched = await orchestrator.get_ohlcv_data(ticker, "1 Y")
                if fetched is not None and not fetched.empty:
                    _save_price_history(db, ticker, fetched)
                    price_df = fetched
            except Exception:
                price_df = None

        if price_df is None or price_df.empty:
            errors.append({"symbol": ticker, "reason": "missing_price_data"})
            continue

        finviz_data = _get_latest_import(db, ticker, "finviz")
        mc_data = _get_latest_import(db, ticker, "marketchameleon")
        iv_data = _get_latest_iv(db, ticker)

        result = await orchestrator.calculate_momentum_pool_score(
            symbol=ticker,
            sector_etf=sector_symbol,
            finviz_data=finviz_data,
            mc_data=mc_data,
            iv_data=iv_data,
            duration='1 Y',
        )

        if result is None or result.get("total_score") is None:
            errors.append({
                "symbol": ticker,
                "reason": (result or {}).get("error", "calc_failed")
            })
            continue

        stock = db.query(Stock).filter(Stock.symbol == ticker).first()
        if not stock:
            stock = Stock(symbol=ticker)

        sector_value = sector_symbol or (finviz_data.get("sector") if finviz_data else None)
        if not sector_value:
            sector_value = etf.parent_sector or etf.symbol

        industry_value = finviz_data.get("industry") if finviz_data else None
        if not industry_value:
            industry_value = etf.name or etf.symbol

        stock.name = finviz_data.get("company_name") if finviz_data else (stock.name or ticker)
        stock.sector = sector_value
        stock.industry = industry_value
        stock.price = float(price_df["close"].iloc[-1])
        stock.score_total = float(result["total_score"])
        stock.scores = result.get("scores") or {}
        stock.metrics = result.get("metrics") or {}
        db.add(stock)
        db.flush()

        today = date_type.today()
        existing_snapshot = db.query(ScoreSnapshot).filter(
            ScoreSnapshot.symbol == ticker,
            ScoreSnapshot.symbol_type == "stock",
            ScoreSnapshot.date == today
        ).first()

        score_breakdown = {
            "scores": stock.scores or {},
            "metrics": stock.metrics or {}
        }
        thresholds_pass = (
            (stock.scores or {}).get("momentum", 0) >= 50 and
            (stock.scores or {}).get("trend", 0) >= 50
        )

        if existing_snapshot:
            existing_snapshot.total_score = stock.score_total
            existing_snapshot.score_breakdown = score_breakdown
            existing_snapshot.thresholds_pass = thresholds_pass
        else:
            db.add(ScoreSnapshot(
                symbol=ticker,
                symbol_type="stock",
                date=today,
                total_score=stock.score_total,
                score_breakdown=score_breakdown,
                thresholds_pass=thresholds_pass
            ))

        db.flush()

        stock.changes = _compute_deltas(db, ticker)

        updated.append({
            "symbol": ticker,
            "score": stock.score_total,
            "sector": sector_value,
            "industry": industry_value,
            "weight": holding.weight
        })

    db.commit()

    updated_sorted = sorted(updated, key=lambda x: x["score"], reverse=True)[:limit]

    return {
        "status": "success",
        "task_id": task_id,
        "coverage": coverage,
        "total_candidates": len(holdings_map),
        "updated_count": len(updated),
        "errors": errors,
        "updated": updated_sorted,
        "message": f"已更新 {len(updated)} 只动能股"
    }


@router.websocket("/ws/{task_id}/refresh-stream")
async def websocket_refresh_stream(websocket: WebSocket, task_id: int, db: Session = Depends(get_db)):
    """
    WebSocket 端点：实时推送 ETF 刷新进度

    消息格式:
    {
      "event": "progress|completed|error",
      "etf_symbol": "XLK",
      "stage": "connecting|fetching_price|calculating_relmom|calculating_trend|fetching_iv|saving|done|error",
      "progress_percentage": 50,
      "message": "正在获取价格数据...",
      "completed_count": 1,
      "total_count": 3,
      "current_etf": "XLK",
      "error": null,
      "timestamp": "2026-01-30T10:00:00Z"
    }
    """
    await websocket.accept()

    try:
        # 验证任务是否存在
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            await websocket.send_json({
                "event": "error",
                "message": "Task not found"
            })
            await websocket.close()
            return

        etf_symbols = _task_monitored_etf_symbols(task)

        # 如果没有 ETF，直接完成
        if not etf_symbols:
            await websocket.send_json({
                "event": "completed",
                "message": "任务中没有 ETF",
                "total_count": 0,
                "completed_count": 0,
                "timestamp": datetime.utcnow().isoformat()
            })
            return

        # 导入 orchestrator
        from app.services.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()

        # 刷新每个 ETF
        for idx, symbol in enumerate(etf_symbols, 1):
            try:
                # 推送开始消息
                await websocket.send_json({
                    "event": "progress",
                    "etf_symbol": symbol,
                    "stage": "connecting",
                    "progress_percentage": 10,
                    "message": f"准备刷新 {symbol}...",
                    "completed_count": idx - 1,
                    "total_count": len(etf_symbols),
                    "current_etf": symbol,
                    "error": None,
                    "timestamp": datetime.utcnow().isoformat()
                })
                await asyncio.sleep(0.1)

                # 调用真实的刷新函数
                result = await refresh_etf_data(symbol, db)

                if result.get('status') == 'success':
                    # 推送成功消息
                    await websocket.send_json({
                        "event": "progress",
                        "etf_symbol": symbol,
                        "stage": "done",
                        "progress_percentage": 100,
                        "message": f"{symbol} 刷新完成 (评分: {result.get('score', '--')})",
                        "completed_count": idx,
                        "total_count": len(etf_symbols),
                        "current_etf": symbol if idx < len(etf_symbols) else None,
                        "error": None,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                else:
                    # 推送部分失败消息
                    await websocket.send_json({
                        "event": "progress",
                        "etf_symbol": symbol,
                        "stage": "error",
                        "progress_percentage": 100,
                        "message": f"{symbol} 刷新失败: {result.get('message', '未知错误')}",
                        "completed_count": idx,
                        "total_count": len(etf_symbols),
                        "current_etf": symbol,
                        "error": result.get('message'),
                        "timestamp": datetime.utcnow().isoformat()
                    })

            except Exception as e:
                # 推送错误消息
                await websocket.send_json({
                    "event": "progress",
                    "etf_symbol": symbol,
                    "stage": "error",
                    "progress_percentage": 100,
                    "message": f"刷新 {symbol} 出错: {str(e)}",
                    "completed_count": idx,
                    "total_count": len(etf_symbols),
                    "current_etf": symbol,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                })

            await asyncio.sleep(0.2)

        # 全部完成
        await websocket.send_json({
            "event": "completed",
            "message": f"任务完成: {len(etf_symbols)} 个 ETF 已刷新",
            "total_count": len(etf_symbols),
            "completed_count": len(etf_symbols),
            "timestamp": datetime.utcnow().isoformat()
        })

    except WebSocketDisconnect:
        print(f"WebSocket 客户端断开连接: task_id={task_id}")
    except Exception as e:
        await websocket.send_json({
            "event": "error",
            "message": str(e),
            "timestamp": datetime.utcnow().isoformat()
        })
        await websocket.close()
