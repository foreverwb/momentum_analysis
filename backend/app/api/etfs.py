from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.models import get_db

router = APIRouter()

# Mock data
MOCK_ETFS = [
    {
        "id": 1,
        "symbol": "XLK",
        "name": "Technology Select Sector SPDR",
        "type": "sector",
        "score": 72.5,
        "rank": 1,
        "delta": {"delta3d": 2.3, "delta5d": 4.1},
        "completeness": 95,
        "holdingsCount": 75
    },
    {
        "id": 2,
        "symbol": "XLF",
        "name": "Financial Select Sector SPDR",
        "type": "sector",
        "score": 68.2,
        "rank": 2,
        "delta": {"delta3d": 1.5, "delta5d": 2.8},
        "completeness": 88,
        "holdingsCount": 68
    },
    {
        "id": 3,
        "symbol": "XLV",
        "name": "Health Care Select Sector SPDR",
        "type": "sector",
        "score": 64.8,
        "rank": 3,
        "delta": {"delta3d": 0.8, "delta5d": 1.2},
        "completeness": 92,
        "holdingsCount": 64
    },
    {
        "id": 4,
        "symbol": "SOXX",
        "name": "iShares Semiconductor ETF",
        "type": "industry",
        "score": 78.5,
        "rank": 1,
        "delta": {"delta3d": 3.2, "delta5d": 5.8},
        "completeness": 100,
        "holdingsCount": 30
    },
    {
        "id": 5,
        "symbol": "SMH",
        "name": "VanEck Semiconductor ETF",
        "type": "industry",
        "score": 76.2,
        "rank": 2,
        "delta": {"delta3d": 2.8, "delta5d": 4.9},
        "completeness": 98,
        "holdingsCount": 25
    }
]


@router.get("", response_model=List[dict])
async def get_etfs(
    type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all ETFs with optional type filter"""
    etfs = MOCK_ETFS
    
    if type:
        etfs = [e for e in etfs if e["type"] == type]
    
    return etfs


@router.get("/{etf_id}", response_model=dict)
async def get_etf(etf_id: int, db: Session = Depends(get_db)):
    """Get a specific ETF by ID"""
    etf = next((e for e in MOCK_ETFS if e["id"] == etf_id), None)
    
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    
    return etf
