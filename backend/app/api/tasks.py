from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.models import get_db
from app.schemas import TaskCreate

router = APIRouter()

# Mock data (mutable for create operations)
MOCK_TASKS = [
    {
        "id": 1,
        "title": "科技板块轮动监控",
        "type": "rotation",
        "baseIndex": "SPY",
        "sector": None,
        "etfs": ["XLK", "XLF", "XLV"],
        "createdAt": "2026-01-25"
    },
    {
        "id": 2,
        "title": "科技内部行业下钻",
        "type": "drilldown",
        "baseIndex": "SPY",
        "sector": "XLK",
        "etfs": ["SOXX", "SMH", "IGV", "SKYY"],
        "createdAt": "2026-01-24"
    },
    {
        "id": 3,
        "title": "半导体动能股追踪",
        "type": "momentum",
        "baseIndex": "SPY",
        "sector": "XLK",
        "etfs": ["SOXX", "SMH"],
        "createdAt": "2026-01-23"
    }
]


@router.get("", response_model=List[dict])
async def get_tasks(db: Session = Depends(get_db)):
    """Get all monitoring tasks"""
    return MOCK_TASKS


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    """Get a specific task by ID"""
    task = next((t for t in MOCK_TASKS if t["id"] == task_id), None)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task


@router.post("", response_model=dict)
async def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Create a new monitoring task"""
    new_id = max(t["id"] for t in MOCK_TASKS) + 1 if MOCK_TASKS else 1
    
    new_task = {
        "id": new_id,
        "title": task.title,
        "type": task.type.value,
        "baseIndex": task.baseIndex,
        "sector": task.sector,
        "etfs": task.etfs,
        "createdAt": datetime.now().strftime("%Y-%m-%d")
    }
    
    MOCK_TASKS.append(new_task)
    return new_task


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    """Delete a monitoring task"""
    global MOCK_TASKS
    
    task = next((t for t in MOCK_TASKS if t["id"] == task_id), None)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    MOCK_TASKS = [t for t in MOCK_TASKS if t["id"] != task_id]
    return {"message": "Task deleted successfully"}
