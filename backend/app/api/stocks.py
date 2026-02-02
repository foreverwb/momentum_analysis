"""
Stock API 端点
从数据库读取股票数据（已移除 mock 数据）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
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
            "return20dEx3d": None,
            "return63d": 0,
            "relativeStrength": None,
            "distanceToHigh20d": None,
            "volumeMultiple": None,
            "maAlignment": None,
            "trendPersistence": None,
            "breakoutVolume": None,
            "volumeRatio": None,
            "obvTrend": None,
            "maxDrawdown20d": None,
            "atrPercent": None,
            "deviationFrom20ma": None,
            "overheat": None,
            "optionsHeat": None,
            "optionsRelVolume": None,
            "sma20Slope": 0,
            "ivr": 0,
            "iv30": 0
        },
        # 新增热度标签相关字段
        "heatType": stock.heat_type or "normal",
        "heatScore": stock.heat_score or 0.0,
        "riskScore": stock.risk_score or 0.0,
        "thresholdsPass": stock.thresholds_pass if stock.thresholds_pass is not None else True,
        "thresholds": stock.thresholds or {}
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


@router.post("/compare", response_model=List[dict])
async def compare_stocks(
    symbols: List[str] = Body(..., description="股票符号列表，最多 4 只"),
    db: Session = Depends(get_db)
):
    """
    批量获取多只股票数据用于对比
    
    参数:
    - symbols: 股票符号列表，最多支持 4 只股票
    
    返回:
    - 股票列表，包含完整评分和指标数据
    """
    if len(symbols) > 4:
        raise HTTPException(
            status_code=400, 
            detail="最多支持对比 4 只股票"
        )
    
    if len(symbols) == 0:
        raise HTTPException(
            status_code=400, 
            detail="请至少提供 1 个股票符号"
        )
    
    # 统一转为大写
    symbols_upper = [s.upper() for s in symbols]
    
    # 查询所有股票
    stocks = db.query(Stock).filter(Stock.symbol.in_(symbols_upper)).all()
    
    # 检查是否找到所有股票
    found_symbols = {stock.symbol for stock in stocks}
    missing_symbols = set(symbols_upper) - found_symbols
    
    if missing_symbols:
        raise HTTPException(
            status_code=404,
            detail=f"未找到以下股票: {', '.join(missing_symbols)}"
        )
    
    # 按请求顺序返回
    stock_map = {stock.symbol: stock for stock in stocks}
    result = [format_stock_response(stock_map[symbol]) for symbol in symbols_upper]
    
    return result


@router.get("/by-heat/{heat_type}", response_model=List[dict])
async def get_stocks_by_heat(
    heat_type: str,
    sector: Optional[str] = Query(None, description="按板块筛选"),
    limit: int = Query(20, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    按热度类型筛选股票
    
    参数:
    - heat_type: 热度类型 (trend, event, hedge, normal)
    - sector: 可选，按板块筛选
    - limit: 返回数量限制（默认 20）
    
    返回:
    - 按热度评分降序排列的股票列表
    """
    valid_heat_types = ['trend', 'event', 'hedge', 'normal']
    heat_type_lower = heat_type.lower()
    
    if heat_type_lower not in valid_heat_types:
        raise HTTPException(
            status_code=400,
            detail=f"无效的热度类型: {heat_type}。有效类型: {', '.join(valid_heat_types)}"
        )
    
    query = db.query(Stock).filter(Stock.heat_type == heat_type_lower)
    
    if sector:
        query = query.filter(Stock.sector == sector.upper())
    
    # 按热度评分降序，其次按总评分降序
    stocks = query.order_by(
        Stock.heat_score.desc(),
        Stock.score_total.desc()
    ).limit(limit).all()
    
    return [format_stock_response(stock) for stock in stocks]


@router.get("/symbol/{symbol}/detail", response_model=dict)
async def get_stock_detail(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    获取股票详细信息，包含完整评分分解
    
    参数:
    - symbol: 股票符号
    
    返回:
    - 基础信息 + scores breakdown + thresholds + heat_type
    """
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    
    if not stock:
        raise HTTPException(
            status_code=404, 
            detail=f"未找到股票: {symbol}"
        )
    
    # 基础响应
    response = format_stock_response(stock)
    
    # 添加额外的详细信息
    response["detail"] = {
        "scoresBreakdown": {
            "momentum": {
                "score": (stock.scores or {}).get("momentum", 0),
                "weight": 0.25,
                "components": {
                    "return20d": (stock.metrics or {}).get("return20d", 0),
                    "return63d": (stock.metrics or {}).get("return63d", 0),
                    "relativeStrength": (stock.metrics or {}).get("relativeStrength"),
                }
            },
            "trend": {
                "score": (stock.scores or {}).get("trend", 0),
                "weight": 0.25,
                "components": {
                    "sma20Slope": (stock.metrics or {}).get("sma20Slope", 0),
                    "maAlignment": (stock.metrics or {}).get("maAlignment"),
                    "trendPersistence": (stock.metrics or {}).get("trendPersistence"),
                    "distanceToHigh20d": (stock.metrics or {}).get("distanceToHigh20d"),
                }
            },
            "volume": {
                "score": (stock.scores or {}).get("volume", 0),
                "weight": 0.20,
                "components": {
                    "volumeMultiple": (stock.metrics or {}).get("volumeMultiple"),
                    "volumeRatio": (stock.metrics or {}).get("volumeRatio"),
                    "breakoutVolume": (stock.metrics or {}).get("breakoutVolume"),
                    "obvTrend": (stock.metrics or {}).get("obvTrend"),
                }
            },
            "quality": {
                "score": (stock.scores or {}).get("quality", 0),
                "weight": 0.15,
                "components": {
                    "maxDrawdown20d": (stock.metrics or {}).get("maxDrawdown20d"),
                    "atrPercent": (stock.metrics or {}).get("atrPercent"),
                    "deviationFrom20ma": (stock.metrics or {}).get("deviationFrom20ma"),
                    "overheat": (stock.metrics or {}).get("overheat"),
                }
            },
            "options": {
                "score": (stock.scores or {}).get("options", 0),
                "weight": 0.15,
                "components": {
                    "ivr": (stock.metrics or {}).get("ivr", 0),
                    "iv30": (stock.metrics or {}).get("iv30", 0),
                    "optionsHeat": (stock.metrics or {}).get("optionsHeat"),
                    "optionsRelVolume": (stock.metrics or {}).get("optionsRelVolume"),
                }
            }
        },
        "thresholdDetails": stock.thresholds or {},
        "heatAnalysis": {
            "type": stock.heat_type or "normal",
            "score": stock.heat_score or 0.0,
            "riskScore": stock.risk_score or 0.0,
            "thresholdsPass": stock.thresholds_pass if stock.thresholds_pass is not None else True,
        },
        "updatedAt": stock.updated_at.isoformat() if stock.updated_at else None,
        "createdAt": stock.created_at.isoformat() if stock.created_at else None,
    }
    
    return response


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


@router.get("/symbol/{symbol}/options-overlay", response_model=dict)
async def get_stock_options_overlay(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    获取股票期权覆盖数据，用于期权/波动率确认面板
    
    参数:
    - symbol: 股票符号
    
    返回:
    - 期权热度、风险定价、期限结构、持仓变化等数据
    """
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    
    if not stock:
        raise HTTPException(
            status_code=404, 
            detail=f"未找到股票: {symbol}"
        )
    
    # 从 stock 中提取期权相关数据
    metrics = stock.metrics or {}
    scores = stock.scores or {}
    
    # 计算各项评分
    heat_score = stock.heat_score or 0.0
    risk_score = stock.risk_score or 0.0
    options_score = scores.get('options', 0)
    
    # 计算期限结构评分（基于现有数据）
    ivr = metrics.get('ivr', 0) or 0
    iv30 = metrics.get('iv30', 0) or 0
    term_structure_score = min(100, max(0, (100 - ivr) * 0.5 + options_score * 0.5)) if ivr else options_score
    
    # 计算相对成交量（基于期权热度）
    options_heat = metrics.get('optionsHeat', 0) or 0
    options_rel_volume = metrics.get('optionsRelVolume', 0) or 0
    
    relative_nominal = options_rel_volume if options_rel_volume else (heat_score / 50 if heat_score > 0 else None)
    relative_volume = options_rel_volume if options_rel_volume else (heat_score / 50 if heat_score > 0 else None)
    
    # 确定交易笔数等级
    if heat_score >= 70:
        trade_count = "高"
    elif heat_score >= 40:
        trade_count = "中"
    else:
        trade_count = "低"
    
    # 从数据库获取持仓变化数据（如果有）
    # 目前返回空列表，待期权数据源接入后填充
    positioning = []
    
    # 尝试从 metrics 中获取持仓数据（如果已导入）
    if metrics.get('optionsPositioning'):
        positioning = metrics.get('optionsPositioning', [])
    
    return {
        "symbol": stock.symbol,
        # Heat metrics
        "heatScore": heat_score,
        "heatType": stock.heat_type or "normal",
        "relativeNominal": relative_nominal,
        "relativeVolume": relative_volume,
        "tradeCount": trade_count,
        
        # Risk pricing metrics
        "riskScore": risk_score,
        "ivr": ivr if ivr else None,
        "iv30": iv30 if iv30 else None,
        "iv30Change": metrics.get('iv30Change'),
        
        # Term structure metrics
        "termStructureScore": round(term_structure_score),
        "slope": metrics.get('termSlope'),
        "slopeChange": metrics.get('termSlopeChange'),
        "earningsEvent": metrics.get('earningsDate'),
        
        # Positioning data
        "positioning": positioning,
        
        # Metadata
        "dataSource": "Database",
        "updatedAt": stock.updated_at.isoformat() if stock.updated_at else None,
    }