"""
Stock API 端点
从数据库读取股票数据（已移除 mock 数据）
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.models import get_db, Stock
from app.schemas import StockResponse

router = APIRouter()


def format_stock_response(stock: Stock) -> dict:
    """格式化股票响应数据"""
    return {
        "id": stock.id,
        "symbol": stock.symbol,
        "name": stock.name or stock.symbol,
        "sector": stock.sector,
        "industry": stock.industry,
        "price": stock.price or 0.0,
        "scoreTotal": stock.score_total or 0.0,
        "scores": stock.scores or {
            "momentum": 0,
            "trend": 0,
            "volume": 0,
            "quality": 0,
            "options": 0
        },
        "changes": stock.changes or {
            "delta3d": None,
            "delta5d": None
        },
        "metrics": stock.metrics or {
            "return20d": 0,
            "return63d": 0,
            "sma20Slope": 0,
            "ivr": 0,
            "iv30": 0
        }
    }


@router.get("", response_model=List[dict])
async def get_stocks(
    industry: Optional[str] = Query(None, description="按行业筛选"),
    sector: Optional[str] = Query(None, description="按板块筛选"),
    min_score: Optional[float] = Query(None, description="最低评分"),
    limit: int = Query(100, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    获取所有股票列表
    
    参数:
    - industry: 可选，按行业筛选
    - sector: 可选，按板块筛选
    - min_score: 可选，最低评分过滤
    - limit: 返回数量限制（默认 100）
    
    返回:
    - 股票列表，按评分降序排列
    """
    query = db.query(Stock)
    
    if industry:
        query = query.filter(Stock.industry == industry)
    
    if sector:
        query = query.filter(Stock.sector == sector.upper())
    
    if min_score is not None:
        query = query.filter(Stock.score_total >= min_score)
    
    # 按评分降序排列
    stocks = query.order_by(Stock.score_total.desc()).limit(limit).all()
    
    return [format_stock_response(stock) for stock in stocks]


@router.get("/by-etf/{etf_symbol}", response_model=List[dict])
async def get_stocks_by_etf(
    etf_symbol: str,
    limit: int = Query(20, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    获取指定 ETF 持仓中的股票
    
    参数:
    - etf_symbol: ETF 符号
    - limit: 返回数量限制（默认 20）
    """
    # 通过板块筛选股票
    stocks = db.query(Stock).filter(
        Stock.sector == etf_symbol.upper()
    ).order_by(Stock.score_total.desc()).limit(limit).all()
    
    return [format_stock_response(stock) for stock in stocks]


@router.get("/{stock_id}", response_model=dict)
async def get_stock(stock_id: int, db: Session = Depends(get_db)):
    """
    根据 ID 获取单个股票
    """
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    
    return format_stock_response(stock)


@router.get("/symbol/{symbol}", response_model=dict)
async def get_stock_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """
    根据符号获取股票
    """
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock '{symbol}' not found")
    
    return format_stock_response(stock)


@router.get("/top/{n}", response_model=List[dict])
async def get_top_stocks(
    n: int = 10,
    sector: Optional[str] = Query(None, description="按板块筛选"),
    db: Session = Depends(get_db)
):
    """
    获取评分最高的 N 只股票
    """
    query = db.query(Stock)
    
    if sector:
        query = query.filter(Stock.sector == sector.upper())
    
    stocks = query.order_by(Stock.score_total.desc()).limit(n).all()
    
    return [format_stock_response(stock) for stock in stocks]
