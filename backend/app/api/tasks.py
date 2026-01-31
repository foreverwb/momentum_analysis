"""
Task API 端点
从数据库读取任务数据（已移除 mock 数据）
支持 WebSocket 实时进度推送和批量刷新功能
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import asyncio

from app.models import get_db, Task
from app.schemas import TaskCreate
from app.api.etfs import refresh_etf_data

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
