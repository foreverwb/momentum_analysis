"""
Task API 端点
从数据库读取任务数据（已移除 mock 数据）
支持 WebSocket 实时进度推送和批量刷新功能
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date as date_type
import asyncio

import pandas as pd

from app.models import get_db, Task, ETF, ETFHolding, Stock, PriceHistory, ImportedData, IVData, ScoreSnapshot
from app.schemas import TaskCreate
from app.api.etfs import refresh_etf_data
from app.services.calculators.momentum_pool import calculate_momentum_pool_result

router = APIRouter()


def format_task_response(task: Task) -> dict:
    """格式化任务响应数据"""
    return {
        "id": task.id,
        "title": task.title,
        "type": task.type,
        "baseIndex": task.base_index,
        "sector": task.sector,
        "etfs": task.etfs or [],
        "createdAt": task.created_at.strftime("%Y-%m-%d") if task.created_at else None
    }


def _parse_coverage(coverage: str) -> Tuple[str, int]:
    coverage = (coverage or "top20").lower()
    if coverage.startswith("top"):
        return "top", int(coverage.replace("top", "") or 20)
    if coverage.startswith("weight"):
        return "weight", int(coverage.replace("weight", "") or 70)
    return "top", 20


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


@router.post("", response_model=dict)
async def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    """
    创建新的监控任务
    """
    new_task = Task(
        title=task.title,
        type=task.type.value,
        base_index=task.baseIndex,
        sector=task.sector,
        etfs=task.etfs,
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
    
    task.title = task_update.title
    task.type = task_update.type.value
    task.base_index = task_update.baseIndex
    task.sector = task_update.sector
    task.etfs = task_update.etfs
    
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

    if not task.etfs:
        return {
            "status": "success",
            "task_id": task_id,
            "total": 0,
            "completed": 0,
            "failed": 0,
            "results": [],
            "message": "任务中没有 ETF"
        }

    results = []
    failed_count = 0

    for symbol in task.etfs:
        try:
            result = await refresh_etf_data(symbol, db)
            results.append(result)
            if result.get("status") != "success":
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

    return {
        "status": "success" if failed_count == 0 else "partial_success",
        "task_id": task_id,
        "total": len(task.etfs),
        "completed": len(task.etfs) - failed_count,
        "failed": failed_count,
        "results": results,
        "message": f"刷新完成: {len(task.etfs) - failed_count} 成功, {failed_count} 失败"
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

    # 预加载板块价格
    sector_symbol = task.sector.upper() if task.sector else None
    sector_df = None
    if sector_symbol:
        sector_df = _load_price_history(db, sector_symbol)
        if sector_df is None and orchestrator._ibkr and orchestrator._ibkr.is_connected():
            try:
                fetched = orchestrator._ibkr.get_ohlcv_data(sector_symbol, "1 Y")
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
        if coverage_type == "top":
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
        if price_df is None and orchestrator._ibkr and orchestrator._ibkr.is_connected():
            try:
                fetched = orchestrator._ibkr.get_ohlcv_data(ticker, "1 Y")
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

        result = calculate_momentum_pool_result(
            price_df=price_df,
            sector_df=sector_df,
            finviz_data=finviz_data,
            mc_data=mc_data,
            iv_data=iv_data
        )

        if result is None:
            errors.append({"symbol": ticker, "reason": "calc_failed"})
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
        stock.score_total = result.total_score
        stock.scores = result.scores
        stock.metrics = result.metrics
        db.add(stock)
        db.flush()

        today = date_type.today()
        existing_snapshot = db.query(ScoreSnapshot).filter(
            ScoreSnapshot.symbol == ticker,
            ScoreSnapshot.symbol_type == "stock",
            ScoreSnapshot.date == today
        ).first()

        score_breakdown = {
            "scores": result.scores,
            "metrics": result.metrics
        }
        thresholds_pass = (result.scores.get("momentum", 0) >= 50 and result.scores.get("trend", 0) >= 50)

        if existing_snapshot:
            existing_snapshot.total_score = result.total_score
            existing_snapshot.score_breakdown = score_breakdown
            existing_snapshot.thresholds_pass = thresholds_pass
        else:
            db.add(ScoreSnapshot(
                symbol=ticker,
                symbol_type="stock",
                date=today,
                total_score=result.total_score,
                score_breakdown=score_breakdown,
                thresholds_pass=thresholds_pass
            ))

        db.flush()

        stock.changes = _compute_deltas(db, ticker)

        updated.append({
            "symbol": ticker,
            "score": result.total_score,
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

        etf_symbols = task.etfs or []

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
