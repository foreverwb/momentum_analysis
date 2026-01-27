"""
Task API 端点
从数据库读取任务数据（已移除 mock 数据）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.models import get_db, Task
from app.schemas import TaskCreate

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
