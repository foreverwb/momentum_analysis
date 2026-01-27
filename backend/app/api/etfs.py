"""
ETF API 端点
从数据库读取 ETF 数据（已移除 mock 数据）
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date

from app.models import get_db, ETF, ETFHolding, VALID_SECTOR_SYMBOLS

router = APIRouter()


def format_etf_response(etf: ETF, include_holdings: bool = False) -> dict:
    """格式化 ETF 响应数据"""
    result = {
        "id": etf.id,
        "symbol": etf.symbol,
        "name": etf.name,
        "type": etf.type,
        "score": etf.score or 0.0,
        "rank": etf.rank or 0,
        "delta": etf.delta or {"delta3d": None, "delta5d": None},
        "completeness": etf.completeness or 0.0,
        "holdingsCount": etf.holdings_count or 0
    }
    
    if etf.type == "industry" and etf.parent_sector:
        result["parentSector"] = etf.parent_sector
    
    if include_holdings and etf.holdings:
        # 只返回最新日期的持仓
        latest_date = max(h.data_date for h in etf.holdings) if etf.holdings else None
        if latest_date:
            result["holdings"] = [
                {"ticker": h.ticker, "weight": h.weight}
                for h in etf.holdings if h.data_date == latest_date
            ]
    
    return result


@router.get("", response_model=List[dict])
async def get_etfs(
    type: Optional[str] = Query(None, description="ETF 类型: sector 或 industry"),
    include_holdings: bool = Query(False, description="是否包含持仓数据"),
    db: Session = Depends(get_db)
):
    """
    获取所有 ETF 列表
    
    参数:
    - type: 可选，筛选 ETF 类型 (sector/industry)
    - include_holdings: 是否包含持仓数据
    
    返回:
    - ETF 列表
    """
    query = db.query(ETF)
    
    if type:
        query = query.filter(ETF.type == type)
    
    # 按 rank 排序，rank 为 0 的排在后面
    etfs = query.order_by(
        (ETF.rank == 0).asc(),  # rank 非 0 的排前面
        ETF.rank.asc()
    ).all()
    
    return [format_etf_response(etf, include_holdings=include_holdings) for etf in etfs]


@router.get("/sectors", response_model=List[dict])
async def get_sector_etfs(
    include_holdings: bool = Query(False, description="是否包含持仓数据"),
    db: Session = Depends(get_db)
):
    """
    获取所有板块 ETF（11 个默认板块）
    """
    etfs = db.query(ETF).filter(ETF.type == "sector").order_by(
        (ETF.rank == 0).asc(),
        ETF.rank.asc()
    ).all()
    
    return [format_etf_response(etf, include_holdings=include_holdings) for etf in etfs]


@router.get("/industries", response_model=List[dict])
async def get_industry_etfs(
    sector: Optional[str] = Query(None, description="父板块 ETF 符号"),
    include_holdings: bool = Query(False, description="是否包含持仓数据"),
    db: Session = Depends(get_db)
):
    """
    获取所有行业 ETF
    
    参数:
    - sector: 可选，按父板块筛选
    - include_holdings: 是否包含持仓数据
    """
    query = db.query(ETF).filter(ETF.type == "industry")
    
    if sector:
        query = query.filter(ETF.parent_sector == sector.upper())
    
    etfs = query.order_by(
        (ETF.rank == 0).asc(),
        ETF.rank.asc()
    ).all()
    
    return [format_etf_response(etf, include_holdings=include_holdings) for etf in etfs]


@router.get("/{etf_id}", response_model=dict)
async def get_etf(
    etf_id: int,
    include_holdings: bool = Query(False, description="是否包含持仓数据"),
    db: Session = Depends(get_db)
):
    """
    根据 ID 获取单个 ETF
    
    参数:
    - etf_id: ETF ID
    - include_holdings: 是否包含持仓数据
    """
    etf = db.query(ETF).filter(ETF.id == etf_id).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    
    return format_etf_response(etf, include_holdings=include_holdings)


@router.get("/symbol/{symbol}", response_model=dict)
async def get_etf_by_symbol(
    symbol: str,
    include_holdings: bool = Query(False, description="是否包含持仓数据"),
    db: Session = Depends(get_db)
):
    """
    根据符号获取 ETF
    
    参数:
    - symbol: ETF 符号
    - include_holdings: 是否包含持仓数据
    """
    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")
    
    return format_etf_response(etf, include_holdings=include_holdings)


@router.get("/{etf_id}/holdings", response_model=List[dict])
async def get_etf_holdings(
    etf_id: int,
    data_date: Optional[date] = Query(None, description="持仓日期，默认最新"),
    db: Session = Depends(get_db)
):
    """
    获取 ETF 持仓数据
    
    参数:
    - etf_id: ETF ID
    - data_date: 可选，指定持仓日期
    """
    etf = db.query(ETF).filter(ETF.id == etf_id).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    
    query = db.query(ETFHolding).filter(ETFHolding.etf_id == etf_id)
    
    if data_date:
        query = query.filter(ETFHolding.data_date == data_date)
    else:
        # 获取最新日期
        latest_date = db.query(func.max(ETFHolding.data_date)).filter(
            ETFHolding.etf_id == etf_id
        ).scalar()
        
        if latest_date:
            query = query.filter(ETFHolding.data_date == latest_date)
    
    holdings = query.order_by(ETFHolding.weight.desc()).all()
    
    return [
        {
            "ticker": h.ticker,
            "weight": h.weight,
            "dataDate": h.data_date.isoformat() if h.data_date else None
        }
        for h in holdings
    ]


@router.get("/symbol/{symbol}/holdings", response_model=List[dict])
async def get_etf_holdings_by_symbol(
    symbol: str,
    data_date: Optional[date] = Query(None, description="持仓日期，默认最新"),
    db: Session = Depends(get_db)
):
    """
    根据 ETF 符号获取持仓数据
    """
    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")
    
    return await get_etf_holdings(etf.id, data_date, db)


@router.get("/valid-sectors", response_model=List[str])
async def get_valid_sector_symbols():
    """
    获取有效的板块 ETF 符号列表
    """
    return VALID_SECTOR_SYMBOLS