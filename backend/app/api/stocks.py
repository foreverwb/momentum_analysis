from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.models import get_db
from app.schemas import StockResponse

router = APIRouter()

# Mock data for now
MOCK_STOCKS = [
    {
        "id": 1,
        "symbol": "MU",
        "name": "MU",
        "sector": "XLK",
        "industry": "半导体",
        "price": 405.78,
        "scoreTotal": 56.2,
        "scores": {
            "momentum": 60,
            "trend": 55,
            "volume": 50,
            "quality": 70,
            "options": 70
        },
        "changes": {
            "delta3d": 0,
            "delta5d": None
        },
        "metrics": {
            "return20d": 0,
            "return63d": 0,
            "sma20Slope": 0,
            "ivr": 80,
            "iv30": 67.5
        }
    },
    {
        "id": 2,
        "symbol": "NVDA",
        "name": "NVIDIA Corporation",
        "sector": "XLK",
        "industry": "半导体",
        "price": 892.45,
        "scoreTotal": 52.8,
        "scores": {
            "momentum": 58,
            "trend": 52,
            "volume": 48,
            "quality": 65,
            "options": 68
        },
        "changes": {
            "delta3d": 1.5,
            "delta5d": 3.2
        },
        "metrics": {
            "return20d": 5.2,
            "return63d": 12.8,
            "sma20Slope": 0.5,
            "ivr": 65,
            "iv30": 55.2
        }
    },
    {
        "id": 3,
        "symbol": "AMD",
        "name": "Advanced Micro Devices",
        "sector": "XLK",
        "industry": "半导体",
        "price": 178.32,
        "scoreTotal": 48.5,
        "scores": {
            "momentum": 52,
            "trend": 45,
            "volume": 42,
            "quality": 58,
            "options": 55
        },
        "changes": {
            "delta3d": -0.8,
            "delta5d": 1.2
        },
        "metrics": {
            "return20d": 3.1,
            "return63d": 8.5,
            "sma20Slope": 0.3,
            "ivr": 55,
            "iv30": 48.5
        }
    },
    {
        "id": 4,
        "symbol": "INTC",
        "name": "Intel Corporation",
        "sector": "XLK",
        "industry": "半导体",
        "price": 42.15,
        "scoreTotal": 35.2,
        "scores": {
            "momentum": 35,
            "trend": 32,
            "volume": 38,
            "quality": 40,
            "options": 45
        },
        "changes": {
            "delta3d": -2.1,
            "delta5d": -4.5
        },
        "metrics": {
            "return20d": -2.5,
            "return63d": -8.2,
            "sma20Slope": -0.2,
            "ivr": 72,
            "iv30": 62.3
        }
    }
]


@router.get("", response_model=List[dict])
async def get_stocks(
    industry: str = None,
    db: Session = Depends(get_db)
):
    """Get all stocks with optional industry filter"""
    stocks = MOCK_STOCKS
    
    if industry:
        stocks = [s for s in stocks if s["industry"] == industry]
    
    return stocks


@router.get("/{stock_id}", response_model=dict)
async def get_stock(stock_id: int, db: Session = Depends(get_db)):
    """Get a specific stock by ID"""
    stock = next((s for s in MOCK_STOCKS if s["id"] == stock_id), None)
    
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    
    return stock
