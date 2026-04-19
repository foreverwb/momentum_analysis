"""
Stock API 端点
从数据库读取股票数据（已移除 mock 数据）
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any

from app.models import get_db, Stock, ImportedData, ETFHolding, ETF, PriceHistory, IVData, ScoreSnapshot
from app.api.series_utils import build_metric_series, build_sma20_comparison_series
from app.core.time_utils import utc_isoformat
from app.services.parsers import normalize_heat_type
router = APIRouter()


HEAT_TYPE_FILTER_ALIASES = {
    'trend': ['trend', 'trend_heat'],
    'event': ['event', 'event_heat'],
    'hedge': ['hedge', 'hedge_heat'],
    'normal': ['normal'],
}


def _build_symbol_aliases(symbol: str) -> List[str]:
    """
    Build possible symbol aliases for class-share tickers.

    Examples:
    - BRK.B -> [BRK.B, BRKB, BRK B]
    - BRK B -> [BRK B, BRK.B, BRKB]
    - BRKB  -> [BRKB, BRK.B, BRK B]
    """
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return []

    aliases: List[str] = [normalized]
    compact = normalized.replace(" ", "").replace(".", "")

    if "." in normalized:
        aliases.append(normalized.replace(".", ""))
        aliases.append(normalized.replace(".", " "))
    elif " " in normalized:
        aliases.append(normalized.replace(" ", "."))
        aliases.append(normalized.replace(" ", ""))
    elif len(normalized) >= 3 and normalized[-1] in {"A", "B"}:
        aliases.append(f"{normalized[:-1]}.{normalized[-1]}")
        aliases.append(f"{normalized[:-1]} {normalized[-1]}")

    if compact and compact not in aliases:
        aliases.append(compact)

    deduped: List[str] = []
    seen = set()
    for item in aliases:
        candidate = item.strip().upper()
        if candidate and candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def _get_stock_by_symbol_alias(db: Session, symbol: str) -> Optional[Stock]:
    aliases = _build_symbol_aliases(symbol)
    if not aliases:
        return None

    # Prefer exact first.
    exact = aliases[0]
    stock = db.query(Stock).filter(func.upper(Stock.symbol) == exact).first()
    if stock:
        return stock

    if len(aliases) == 1:
        return None

    alias_rank = {alias: idx for idx, alias in enumerate(aliases[1:])}
    candidates = db.query(Stock).filter(func.upper(Stock.symbol).in_(aliases[1:])).all()
    if not candidates:
        return None

    candidates.sort(key=lambda row: alias_rank.get(str(row.symbol or "").upper(), len(alias_rank)))
    return candidates[0]


def _get_latest_import_record_by_alias(
    db: Session,
    aliases: List[str],
    source: str
) -> Optional[ImportedData]:
    if not aliases:
        return None
    return db.query(ImportedData).filter(
        ImportedData.source == source,
        func.upper(ImportedData.symbol).in_(aliases)
    ).order_by(
        ImportedData.date.desc(),
        ImportedData.id.desc()
    ).first()


def _ensure_stock_by_symbol_alias(db: Session, symbol: str) -> Optional[Stock]:
    """
    Resolve stock by symbol aliases. If not present in `stocks`, try to bootstrap
    a minimal row from imported/price/iv/holding tables so detail pages can render.
    """
    stock = _get_stock_by_symbol_alias(db, symbol)
    if stock:
        return stock

    aliases = _build_symbol_aliases(symbol)
    if not aliases:
        return None

    finviz_record = _get_latest_import_record_by_alias(db, aliases, "finviz")
    mc_record = _get_latest_import_record_by_alias(db, aliases, "marketchameleon")
    latest_price = db.query(PriceHistory).filter(
        func.upper(PriceHistory.symbol).in_(aliases)
    ).order_by(
        PriceHistory.date.desc(),
        PriceHistory.created_at.desc(),
        PriceHistory.id.desc()
    ).first()
    latest_iv = db.query(IVData).filter(
        func.upper(IVData.symbol).in_(aliases)
    ).order_by(
        IVData.date.desc(),
        IVData.id.desc()
    ).first()
    latest_holding = db.query(ETFHolding).filter(
        func.upper(ETFHolding.ticker).in_(aliases)
    ).order_by(
        ETFHolding.data_date.desc(),
        ETFHolding.id.desc()
    ).first()

    if not any([finviz_record, mc_record, latest_price, latest_iv, latest_holding]):
        return None

    def _as_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            parsed = float(value)
            return parsed
        except (TypeError, ValueError):
            return None

    finviz_data = finviz_record.data if finviz_record and isinstance(finviz_record.data, dict) else {}
    mc_data = mc_record.data if mc_record and isinstance(mc_record.data, dict) else {}

    symbol_candidates: List[str] = [
        str(finviz_record.symbol).upper() if finviz_record and finviz_record.symbol else "",
        str(latest_price.symbol).upper() if latest_price and latest_price.symbol else "",
        str(latest_iv.symbol).upper() if latest_iv and latest_iv.symbol else "",
        str(latest_holding.ticker).upper() if latest_holding and latest_holding.ticker else "",
        aliases[0],
    ]
    resolved_symbol = next((item for item in symbol_candidates if item), aliases[0])

    sector_value = finviz_data.get("sector")
    industry_value = finviz_data.get("industry")
    if (not sector_value) and latest_holding and latest_holding.etf_symbol:
        etf_symbol = str(latest_holding.etf_symbol).upper()
        etf = db.query(ETF).filter(ETF.symbol == etf_symbol).first()
        if etf and etf.type == "sector":
            sector_value = etf_symbol

    heat_type_value = normalize_heat_type(
        str(mc_data.get("heat_type") or mc_data.get("heatType") or "normal")
    )
    heat_score_value = _as_float(mc_data.get("heat_score") or mc_data.get("heatScore")) or 0.0
    risk_score_value = _as_float(mc_data.get("risk_score") or mc_data.get("riskScore")) or 0.0

    metrics_payload: Dict[str, Any] = {}
    iv30_value = _as_float(getattr(latest_iv, "iv30", None))
    if iv30_value is not None:
        metrics_payload["iv30"] = iv30_value
    ivr_value = _as_float(mc_data.get("ivr"))
    if ivr_value is not None:
        metrics_payload["ivr"] = ivr_value
    total_oi_value = _as_float(getattr(latest_iv, "total_oi", None))
    if total_oi_value is not None:
        metrics_payload["openInterest"] = total_oi_value

    name_value = (
        finviz_data.get("company")
        or finviz_data.get("name")
        or finviz_data.get("ticker")
        or resolved_symbol
    )
    if not isinstance(name_value, str) or not name_value.strip():
        name_value = resolved_symbol

    stock = Stock(
        symbol=resolved_symbol,
        name=name_value.strip(),
        sector=str(sector_value).upper() if isinstance(sector_value, str) and sector_value.strip() else None,
        industry=str(industry_value).strip() if isinstance(industry_value, str) and industry_value.strip() else None,
        price=_as_float(getattr(latest_price, "close", None)),
        score_total=0.0,
        scores={
            "momentum": 0,
            "trend": 0,
            "volume": 0,
            "quality": 0,
            "options": 0,
        },
        changes={
            "delta3d": None,
            "delta5d": None,
        },
        metrics=metrics_payload or None,
        heat_type=heat_type_value,
        heat_score=heat_score_value,
        risk_score=risk_score_value,
        thresholds_pass=True,
        thresholds={},
    )
    db.add(stock)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _get_stock_by_symbol_alias(db, symbol)
    db.refresh(stock)
    return stock


def _get_latest_import_map(db: Session, symbols: List[str], source: str) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    subquery = db.query(
        ImportedData.symbol.label("symbol"),
        func.max(ImportedData.date).label("max_date")
    ).filter(
        ImportedData.source == source,
        ImportedData.symbol.in_(symbols)
    ).group_by(ImportedData.symbol).subquery()

    rows = db.query(ImportedData).join(
        subquery,
        and_(
            ImportedData.symbol == subquery.c.symbol,
            ImportedData.date == subquery.c.max_date
        )
    ).filter(ImportedData.source == source).all()

    return {row.symbol: row.data for row in rows}


def _get_related_etf_map(db: Session, symbols: List[str]) -> Dict[str, Dict[str, List[str]]]:
    if not symbols:
        return {}
    latest_dates = db.query(
        ETFHolding.etf_symbol.label("etf_symbol"),
        func.max(ETFHolding.data_date).label("max_date")
    ).group_by(ETFHolding.etf_symbol).subquery()

    rows = db.query(
        ETFHolding.ticker,
        ETFHolding.etf_symbol,
        ETF.type,
    ).join(
        latest_dates,
        and_(
            ETFHolding.etf_symbol == latest_dates.c.etf_symbol,
            ETFHolding.data_date == latest_dates.c.max_date
        )
    ).join(
        ETF,
        ETF.symbol == ETFHolding.etf_symbol
    ).filter(
        ETF.type.in_(["sector", "industry"]),
        ETFHolding.ticker.in_(symbols)
    ).all()

    mapping: Dict[str, Dict[str, List[str]]] = {}
    for ticker, etf_symbol, etf_type in rows:
        key = ticker.upper() if ticker else ticker
        value = etf_symbol.upper() if etf_symbol else etf_symbol
        if not key or not value:
            continue
        bucket = str(etf_type or "").lower().strip()
        if bucket not in ("sector", "industry"):
            continue
        mapping.setdefault(key, {"sector": [], "industry": []})[bucket].append(value)

    for ticker, related in mapping.items():
        related["sector"] = sorted(set(related.get("sector", [])))
        related["industry"] = sorted(set(related.get("industry", [])))

    return mapping


def _get_industry_etf_map(db: Session, symbols: List[str]) -> Dict[str, List[str]]:
    related_map = _get_related_etf_map(db, symbols)
    return {
        ticker: related.get("industry", [])
        for ticker, related in related_map.items()
    }


def _resolve_primary_sector_symbol(
    stock_sector: Optional[str],
    related_sector_etfs: List[str]
) -> Optional[str]:
    normalized_related = [s.upper() for s in (related_sector_etfs or []) if s]
    if normalized_related:
        return normalized_related[0]

    if not stock_sector:
        return None
    candidate = stock_sector.strip().upper()
    if candidate and candidate.isalpha() and len(candidate) <= 5:
        return candidate
    return None


def _load_recent_closes(db: Session, symbol: str, limit: int = 30) -> Optional[List[float]]:
    rows = db.query(PriceHistory).filter(
        PriceHistory.symbol == symbol.upper()
    ).order_by(PriceHistory.date.desc()).limit(limit).all()

    if len(rows) < 25:
        return None

    closes = [row.close for row in reversed(rows) if row.close is not None]
    if len(closes) < 25:
        return None
    return closes


def _load_recent_price_rows(db: Session, symbol: str, limit: int = 260) -> List[PriceHistory]:
    """按日期倒序加载最近价格记录。"""
    return db.query(PriceHistory).filter(
        PriceHistory.symbol == symbol.upper()
    ).order_by(PriceHistory.date.desc()).limit(limit).all()


def _compute_sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def _build_price_snapshot(rows_desc: List[PriceHistory]) -> Dict[str, Any]:
    """
    基于最近价格序列构建前端详情页所需快照字段。
    返回值包含:
    - volume / avgVolume
    - sma20 / sma50 / sma200
    - change / changePercent
    """
    if not rows_desc:
        return {}

    closes_asc = [row.close for row in reversed(rows_desc) if row.close is not None]
    volumes_asc = [row.volume for row in reversed(rows_desc) if row.volume is not None]
    latest = rows_desc[0]

    snapshot: Dict[str, Any] = {
        "volume": latest.volume if latest.volume is not None else None,
        "avgVolume": round(sum(volumes_asc[-20:]) / 20) if len(volumes_asc) >= 20 else None,
        "sma20": _compute_sma(closes_asc, 20),
        "sma50": _compute_sma(closes_asc, 50),
        "sma200": _compute_sma(closes_asc, 200),
    }

    if len(closes_asc) >= 2 and closes_asc[-2] not in (None, 0):
        latest_close = closes_asc[-1]
        prev_close = closes_asc[-2]
        if latest_close is not None and prev_close is not None and prev_close != 0:
            delta = latest_close - prev_close
            snapshot["change"] = round(delta, 2)
            snapshot["changePercent"] = round((delta / prev_close) * 100, 2)
    return snapshot


def _compute_return20d(closes: List[float]) -> Optional[float]:
    if len(closes) < 21:
        return None
    base = closes[-21]
    if base == 0:
        return None
    return round((closes[-1] - base) / base * 100, 1)


def _compute_sma20_slope(closes: List[float]) -> Optional[float]:
    if len(closes) < 25:
        return None
    sma_today = sum(closes[-20:]) / 20
    sma_5d_ago = sum(closes[-25:-5]) / 20
    return round((sma_today - sma_5d_ago) / 5, 4)


def _get_price_stats_map(db: Session, symbols: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    stats: Dict[str, Dict[str, Optional[float]]] = {}
    for symbol in symbols:
        closes = _load_recent_closes(db, symbol)
        if not closes:
            continue
        stats[symbol] = {
            "return20d": _compute_return20d(closes),
            "sma20Slope": _compute_sma20_slope(closes)
        }
    return stats


def _build_comparisons(
    stock: Stock,
    sector_symbol: Optional[str],
    industry_etfs: List[str],
    price_stats: Dict[str, Dict[str, Optional[float]]]
) -> List[Dict[str, Any]]:
    metrics = stock.metrics or {}
    stock_return20d = metrics.get("return20d")
    stock_beta = metrics.get("beta")

    def build_item(symbol: str, item_type: str) -> Dict[str, Any]:
        stats = price_stats.get(symbol, {})
        compare_return = stats.get("return20d")
        rs20d = None
        if stock_return20d is not None and compare_return is not None:
            rs20d = round(stock_return20d - compare_return, 1)
        item = {
            "symbol": symbol,
            "type": item_type,
            "return20d": compare_return,
            "rs20d": rs20d,
            "sma20Slope": stats.get("sma20Slope")
        }
        if item_type == "market":
            item["beta"] = stock_beta
        return item

    comparisons: List[Dict[str, Any]] = []
    for symbol in industry_etfs:
        comparisons.append(build_item(symbol, "industry"))
    if sector_symbol:
        comparisons.append(build_item(sector_symbol, "sector"))
    for symbol in ("SPY", "QQQ"):
        comparisons.append(build_item(symbol, "market"))

    return comparisons


def _compute_stock_deltas(db: Session, symbol: str) -> Dict[str, Optional[float]]:
    snapshots = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == symbol.upper(),
        ScoreSnapshot.symbol_type == 'stock'
    ).order_by(ScoreSnapshot.date.desc(), ScoreSnapshot.id.desc()).limit(6).all()
    return _compute_delta_payload_from_snapshots(snapshots)


def _compute_stock_delta_map(db: Session, symbols: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    normalized_symbols = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    if not normalized_symbols:
        return {}

    rows = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol.in_(normalized_symbols),
        ScoreSnapshot.symbol_type == 'stock'
    ).order_by(ScoreSnapshot.symbol.asc(), ScoreSnapshot.date.desc(), ScoreSnapshot.id.desc()).all()

    snapshot_map: Dict[str, List[ScoreSnapshot]] = defaultdict(list)
    for row in rows:
        entries = snapshot_map[row.symbol]
        if len(entries) < 6:
            entries.append(row)

    return {
        symbol: _compute_delta_payload_from_snapshots(entries)
        for symbol, entries in snapshot_map.items()
    }


def _compute_delta_payload_from_snapshots(
    snapshots: List[ScoreSnapshot],
) -> Dict[str, Optional[float]]:
    if not snapshots:
        return {"delta3d": None, "delta5d": None}

    current_snapshot = snapshots[0]
    current = current_snapshot.total_score or 0
    current_date = current_snapshot.date
    delta3d = None
    delta5d = None

    for snap in snapshots[1:]:
        if snap.total_score is None or snap.date is None:
            continue
        days_diff = (current_date - snap.date).days
        if delta3d is None and days_diff >= 3:
            delta3d = round(current - snap.total_score, 2)
        if delta5d is None and days_diff >= 5:
            delta5d = round(current - snap.total_score, 2)
        if delta3d is not None and delta5d is not None:
            break

    return {"delta3d": delta3d, "delta5d": delta5d}


def _resolve_stock_changes(
    stored_changes: Any,
    computed_changes: Optional[Dict[str, Optional[float]]] = None,
) -> Dict[str, Optional[float]]:
    stored = stored_changes if isinstance(stored_changes, dict) else {}
    computed = computed_changes or {}
    delta3d = stored.get("delta3d")
    delta5d = stored.get("delta5d")

    if delta3d is None:
        delta3d = computed.get("delta3d")
    if delta5d is None:
        delta5d = computed.get("delta5d")

    return {
        "delta3d": delta3d,
        "delta5d": delta5d,
    }


def _build_stock_list_response(db: Session, stocks: List[Stock]) -> List[dict]:
    if not stocks:
        return []
    symbols = [stock.symbol for stock in stocks if stock.symbol]
    finviz_map = _get_latest_import_map(db, symbols, "finviz")
    related_map = _get_related_etf_map(db, symbols)
    delta_map = _compute_stock_delta_map(db, symbols)

    resolved_related: Dict[str, Dict[str, Any]] = {}
    comparison_symbols = {"SPY", "QQQ"}
    for stock in stocks:
        related = related_map.get(stock.symbol, {"sector": [], "industry": []})
        sector_etfs = list(related.get("sector", []))
        industry_etfs = list(related.get("industry", []))
        primary_sector_symbol = _resolve_primary_sector_symbol(stock.sector, sector_etfs)
        if primary_sector_symbol and primary_sector_symbol not in sector_etfs:
            sector_etfs.append(primary_sector_symbol)

        sector_etfs = sorted(set(sector_etfs))
        industry_etfs = sorted(set(industry_etfs))

        if primary_sector_symbol:
            comparison_symbols.add(primary_sector_symbol)
        comparison_symbols.update(industry_etfs)
        resolved_related[stock.symbol] = {
            "sector_etfs": sector_etfs,
            "industry_etfs": industry_etfs,
            "primary_sector_symbol": primary_sector_symbol,
        }

    comparison_symbols = {symbol for symbol in comparison_symbols if symbol}

    price_stats = _get_price_stats_map(db, sorted(comparison_symbols))
    responses: List[dict] = []
    for stock in stocks:
        related_payload = resolved_related.get(stock.symbol, {})
        sector_etfs = list(related_payload.get("sector_etfs", []))
        industry_etfs = list(related_payload.get("industry_etfs", []))
        primary_sector_symbol = related_payload.get("primary_sector_symbol")

        payload = format_stock_response(
            stock,
            changes_override=_resolve_stock_changes(
                stock.changes,
                delta_map.get(stock.symbol),
            ),
            finviz_data=finviz_map.get(stock.symbol),
            sector_etfs=sector_etfs,
            industry_etfs=industry_etfs,
            comparisons=_build_comparisons(
                stock,
                primary_sector_symbol,
                industry_etfs,
                price_stats,
            )
        )
        if primary_sector_symbol:
            payload["sector"] = primary_sector_symbol
        responses.append(payload)

    return responses


def format_stock_response(
    stock: Stock,
    changes_override: Optional[Dict[str, Optional[float]]] = None,
    finviz_data: Optional[Dict[str, Any]] = None,
    sector_etfs: Optional[List[str]] = None,
    industry_etfs: Optional[List[str]] = None,
    comparisons: Optional[List[Dict[str, Any]]] = None
) -> dict:
    """格式化股票响应数据"""
    metrics = stock.metrics or {
        "return20d": 0,
        "return20dEx3d": None,
        "return63d": 0,
        "relativeStrength": None,
        "relativeStrengthDiff": None,
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
        "iv30": 0,
        "rsi": None,
        "beta": None
    }
    if finviz_data:
        if metrics.get("rsi") is None and finviz_data.get("rsi") is not None:
            metrics["rsi"] = finviz_data.get("rsi")
        if metrics.get("beta") is None and finviz_data.get("beta") is not None:
            metrics["beta"] = finviz_data.get("beta")

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
        "changes": changes_override or stock.changes or {
            "delta3d": None,
            "delta5d": None
        },
        "metrics": metrics,
        "rsi": metrics.get("rsi"),
        "beta": metrics.get("beta"),
        "sectorEtfs": sector_etfs or [],
        "industryEtfs": industry_etfs or [],
        "comparisons": comparisons or [],
        # 新增热度标签相关字段
        "heatType": normalize_heat_type(stock.heat_type),
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
    return _build_stock_list_response(db, stocks)


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
    return _build_stock_list_response(db, stocks)


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
    delta_map = _compute_stock_delta_map(db, symbols_upper)
    result = [
        format_stock_response(
            stock_map[symbol],
            changes_override=_resolve_stock_changes(
                stock_map[symbol].changes,
                delta_map.get(symbol),
            ),
        )
        for symbol in symbols_upper
    ]
    
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
    heat_type_raw = str(heat_type or '').strip().lower().replace(' ', '_')
    if heat_type_raw not in HEAT_TYPE_FILTER_ALIASES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的热度类型: {heat_type}。有效类型: {', '.join(valid_heat_types)}"
        )
    heat_type_lower = normalize_heat_type(heat_type)
    
    aliases = HEAT_TYPE_FILTER_ALIASES.get(heat_type_lower, [heat_type_lower])
    query = db.query(Stock).filter(func.lower(Stock.heat_type).in_(aliases))
    
    if sector:
        query = query.filter(Stock.sector == sector.upper())
    
    # 按热度评分降序，其次按总评分降序
    stocks = query.order_by(
        Stock.heat_score.desc(),
        Stock.score_total.desc()
    ).limit(limit).all()
    return _build_stock_list_response(db, stocks)


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
    stock = _ensure_stock_by_symbol_alias(db, symbol)
    
    if not stock:
        raise HTTPException(
            status_code=404, 
            detail=f"未找到股票: {symbol}"
        )

    related_map = _get_related_etf_map(db, [stock.symbol])
    related = related_map.get(stock.symbol, {"sector": [], "industry": []})
    sector_etfs = list(related.get("sector", []))
    industry_etfs = related.get("industry", [])
    primary_sector_symbol = _resolve_primary_sector_symbol(stock.sector, sector_etfs)
    if primary_sector_symbol and primary_sector_symbol not in sector_etfs:
        sector_etfs.append(primary_sector_symbol)

    comparison_symbols: List[str] = []
    if primary_sector_symbol:
        comparison_symbols.append(primary_sector_symbol)
    comparison_symbols.extend(industry_etfs)
    comparison_symbols.extend(["SPY", "QQQ"])
    price_stats = _get_price_stats_map(db, sorted(set(comparison_symbols)))

    # 基础响应
    response = format_stock_response(
        stock,
        changes_override=_resolve_stock_changes(
            stock.changes,
            _compute_stock_deltas(db, stock.symbol),
        ),
        industry_etfs=industry_etfs,
        comparisons=_build_comparisons(
            stock,
            primary_sector_symbol,
            industry_etfs,
            price_stats,
        ),
    )
    if primary_sector_symbol:
        response["sector"] = primary_sector_symbol
    response["sectorEtfs"] = sector_etfs

    # 补充价格快照字段（用于前端综合概览渲染）
    price_rows = _load_recent_price_rows(db, stock.symbol)
    price_snapshot = _build_price_snapshot(price_rows)
    response.update({
        "change": price_snapshot.get("change"),
        "changePercent": price_snapshot.get("changePercent"),
        "volume": price_snapshot.get("volume"),
        "avgVolume": price_snapshot.get("avgVolume"),
        "sma20": price_snapshot.get("sma20"),
        "sma50": price_snapshot.get("sma50"),
        "sma200": price_snapshot.get("sma200"),
    })

    latest_iv = db.query(IVData).filter(
        IVData.symbol == stock.symbol
    ).order_by(IVData.date.desc()).first()
    if latest_iv:
        if response.get("impliedVolatility") is None and latest_iv.iv30 is not None:
            response["impliedVolatility"] = latest_iv.iv30
        if response.get("openInterest") is None and latest_iv.total_oi is not None:
            response["openInterest"] = latest_iv.total_oi
    
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
            "type": normalize_heat_type(stock.heat_type),
            "score": stock.heat_score or 0.0,
            "riskScore": stock.risk_score or 0.0,
            "thresholdsPass": stock.thresholds_pass if stock.thresholds_pass is not None else True,
        },
        "updatedAt": utc_isoformat(stock.updated_at),
        "createdAt": utc_isoformat(stock.created_at),
    }
    
    return response


@router.get("/symbol/{symbol}/trend-comparison", response_model=dict)
async def get_stock_trend_comparison(
    symbol: str,
    period: int = Query(20, description="对比周期（交易日）: 5/20/63"),
    metric: str = Query("relative", description="指标: relative/sma20/return20d/score"),
    label_tz: str = Query("beijing", description="日期标签时区，默认北京时间"),
    db: Session = Depends(get_db)
):
    """
    获取个股与相关 ETF/指数的走势对比数据
    """
    if period not in (5, 20, 63):
        raise HTTPException(status_code=400, detail="period must be one of 5, 20, 63")
    if metric not in ("relative", "sma20", "return20d", "score"):
        raise HTTPException(status_code=400, detail="metric must be one of relative, sma20, return20d, score")
    normalized_label_tz = (label_tz or "beijing").strip().lower()
    if normalized_label_tz not in ("market", "beijing"):
        raise HTTPException(status_code=400, detail="label_tz must be one of market, beijing")

    stock = _ensure_stock_by_symbol_alias(db, symbol)
    if not stock:
        raise HTTPException(status_code=404, detail=f"未找到股票: {symbol}")

    related_map = _get_related_etf_map(db, [stock.symbol])
    related = related_map.get(stock.symbol, {"sector": [], "industry": []})
    industry_etfs = related.get("industry", [])
    sector_etfs = related.get("sector", [])

    primary_sector_symbol = _resolve_primary_sector_symbol(stock.sector, sector_etfs)
    all_sector_etfs = list(sector_etfs)
    if primary_sector_symbol and primary_sector_symbol not in all_sector_etfs:
        all_sector_etfs.append(primary_sector_symbol)

    symbols: List[str] = [stock.symbol]
    symbols.extend(industry_etfs)
    symbols.extend(all_sector_etfs)
    symbols.extend(["SPY", "QQQ"])

    deduped: List[str] = []
    for sym in symbols:
        if sym and sym not in deduped:
            deduped.append(sym)

    if metric == "sma20":
        dates, price_series, sma20_series, deviation_series = build_sma20_comparison_series(
            db,
            deduped,
            period,
            label_tz=normalized_label_tz,
        )
        return {
            "symbol": stock.symbol,
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
        "symbol": stock.symbol,
        "period": period,
        "metric": metric,
        "label_tz": normalized_label_tz,
        "symbols": deduped,
        "dates": dates,
        "series": series
    }


@router.get("/{stock_id}", response_model=dict)
async def get_stock(stock_id: int, db: Session = Depends(get_db)):
    """
    根据 ID 获取单个股票
    """
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    
    return format_stock_response(
        stock,
        changes_override=_resolve_stock_changes(
            stock.changes,
            _compute_stock_deltas(db, stock.symbol),
        ),
    )


@router.get("/symbol/{symbol}", response_model=dict)
async def get_stock_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """
    根据符号获取股票
    """
    stock = _ensure_stock_by_symbol_alias(db, symbol)
    
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock '{symbol}' not found")
    
    return format_stock_response(
        stock,
        changes_override=_resolve_stock_changes(
            stock.changes,
            _compute_stock_deltas(db, stock.symbol),
        ),
    )


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
    return _build_stock_list_response(db, stocks)


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
    stock = _ensure_stock_by_symbol_alias(db, symbol)
    
    if not stock:
        raise HTTPException(
            status_code=404, 
            detail=f"未找到股票: {symbol}"
        )
    
    # 从 stock + 最新导入中提取期权相关数据
    metrics = stock.metrics if isinstance(stock.metrics, dict) else {}
    scores = stock.scores if isinstance(stock.scores, dict) else {}
    latest_mc_record = db.query(ImportedData).filter(
        ImportedData.symbol == stock.symbol,
        ImportedData.source == "marketchameleon"
    ).order_by(ImportedData.date.desc(), ImportedData.id.desc()).first()
    mc_data = latest_mc_record.data if latest_mc_record and isinstance(latest_mc_record.data, dict) else {}
    latest_iv_record = db.query(IVData).filter(
        IVData.symbol == stock.symbol
    ).order_by(IVData.date.desc(), IVData.id.desc()).first()

    def _as_float(*values: Any) -> Optional[float]:
        for value in values:
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _as_str(*values: Any) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text and text not in {"-", "N/A", "None"}:
                return text
        return None

    options_score = _as_float(scores.get("options")) or 0.0
    heat_score = _as_float(stock.heat_score, mc_data.get("heat_score"))
    if heat_score is None or heat_score <= 0:
        heat_score = options_score

    risk_score = _as_float(stock.risk_score, mc_data.get("risk_score"))
    ivr = _as_float(metrics.get("ivr"), mc_data.get("ivr"))
    if risk_score is None or risk_score <= 0:
        if ivr is not None:
            risk_score = max(0.0, min(100.0, 100.0 - ivr))
        else:
            risk_score = options_score

    iv30 = _as_float(
        metrics.get("iv30"),
        mc_data.get("iv30"),
        mc_data.get("iv_30"),
        getattr(latest_iv_record, "iv30", None),
    )
    iv60 = _as_float(
        metrics.get("iv60"),
        mc_data.get("iv60"),
        mc_data.get("iv_60"),
        getattr(latest_iv_record, "iv60", None),
    )
    iv90 = _as_float(
        metrics.get("iv90"),
        mc_data.get("iv90"),
        mc_data.get("iv_90"),
        getattr(latest_iv_record, "iv90", None),
        metrics.get("iv90_futu"),
        mc_data.get("iv90_futu"),
    )
    term_structure_score = (
        min(100, max(0, (100 - ivr) * 0.5 + options_score * 0.5))
        if ivr is not None
        else options_score
    )
    slope = None
    if iv30 is not None and iv90 is not None and iv90 != 0:
        # 统一按业务规则计算：Slope = IV30 / IV90
        slope = round(iv30 / iv90, 4)
    if slope is None:
        slope = _as_float(metrics.get("slope"), mc_data.get("slope"))
    term_structure_interpretation = None
    if slope is not None:
        if slope >= 1.1:
            term_structure_interpretation = "短端昂贵（倒挂/恐慌）"
        elif slope < 0.9:
            term_structure_interpretation = "正常陡峭结构"
        else:
            term_structure_interpretation = "正常"
    elif iv30 is not None and (iv90 is None or iv90 == 0):
        term_structure_interpretation = "IV90缺失（90天期限样本不足）"
    slope_change = _as_float(metrics.get("termSlopeChange"), mc_data.get("iv_change"))
    iv30_change = _as_float(
        metrics.get("iv30_chg_pct"),
        metrics.get("iv30Change"),
        metrics.get("iv_change"),
        mc_data.get("iv30_chg_pct"),
        mc_data.get("IV30ChgPct"),
        mc_data.get("iv_change"),
    )

    options_rel_volume = _as_float(
        metrics.get("optionsRelVolume"),
        metrics.get("rel_vol"),
        metrics.get("rel_vol_to_90d"),
        mc_data.get("rel_vol"),
        mc_data.get("rel_vol_to_90d"),
    )
    relative_nominal = _as_float(
        metrics.get("rel_notional"),
        metrics.get("rel_notional_to_90d"),
        mc_data.get("rel_notional"),
        mc_data.get("rel_notional_to_90d"),
        options_rel_volume,
    )
    relative_volume = options_rel_volume
    if relative_nominal is None and heat_score > 0:
        relative_nominal = round(heat_score / 50, 2)
    if relative_volume is None and heat_score > 0:
        relative_volume = round(heat_score / 50, 2)

    trade_count_raw = mc_data.get("trade_count")
    trade_count: str
    if isinstance(trade_count_raw, (int, float)):
        if trade_count_raw >= 5000:
            trade_count = "高"
        elif trade_count_raw >= 2000:
            trade_count = "中"
        else:
            trade_count = "低"
    elif heat_score >= 70:
        trade_count = "高"
    elif heat_score >= 40:
        trade_count = "中"
    else:
        trade_count = "低"

    def _normalize_bucket(raw: Any) -> Optional[str]:
        if raw is None:
            return None
        text = str(raw).strip().replace("天", "").replace("日", "")
        text = text.replace("—", "-").replace("–", "-").replace("~", "-").replace("至", "-")
        text = "".join(text.split())
        if text in {"0-7", "0_7", "07", "0to7", "0-7d", "0-7D"}:
            return "0-7"
        if text in {"8-30", "8_30", "830", "8to30", "8-30d", "8-30D"}:
            return "8-30"
        if text in {"31-90", "31_90", "3190", "31to90", "31-90d", "31-90D"}:
            return "31-90"
        return text or None

    def _infer_trend(net_oi: Optional[float], call_oi: Optional[float], put_oi: Optional[float], default: str = "") -> str:
        if default:
            return default
        if net_oi is not None:
            if net_oi > 0:
                return "偏多"
            if net_oi < 0:
                return "偏空"
            return "中性"
        if call_oi is not None and put_oi is not None:
            if call_oi > put_oi:
                return "偏多"
            if call_oi < put_oi:
                return "偏空"
        return "中性"

    bucket_suffixes = (("0-7", "0_7"), ("8-30", "8_30"), ("31-90", "31_90"))

    def _build_iv_history_positioning() -> Dict[str, Dict[str, Any]]:
        if latest_iv_record is None or getattr(latest_iv_record, "date", None) is None:
            return {}

        previous_rows = db.query(IVData).filter(
            IVData.symbol == stock.symbol,
            IVData.date < latest_iv_record.date,
        ).order_by(IVData.date.desc(), IVData.id.desc()).limit(5).all()

        prev1 = previous_rows[0] if len(previous_rows) >= 1 else None
        prev3 = previous_rows[2] if len(previous_rows) >= 3 else None
        prev5 = previous_rows[4] if len(previous_rows) >= 5 else None

        def _delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
            if current is None or previous is None:
                return None
            return current - previous

        def _record_float(record: Optional[IVData], attr: str) -> Optional[float]:
            if record is None:
                return None
            return _as_float(getattr(record, attr, None))

        computed: Dict[str, Dict[str, Any]] = {}
        for bucket, suffix in bucket_suffixes:
            # Stock.metrics may lag the freshest IVData row by one refresh cycle.
            # Use the latest IV snapshot as the current-source-of-truth for bucket totals.
            current_call_total = _as_float(
                getattr(latest_iv_record, f"call_oi_bucket_{suffix}", None),
                metrics.get(f"call_oi_{suffix}"),
                metrics.get(f"call_oi_bucket_{suffix}"),
            )
            current_put_total = _as_float(
                getattr(latest_iv_record, f"put_oi_bucket_{suffix}", None),
                metrics.get(f"put_oi_{suffix}"),
                metrics.get(f"put_oi_bucket_{suffix}"),
            )
            current_net_total = _as_float(
                getattr(latest_iv_record, f"oi_bucket_{suffix}", None),
                metrics.get(f"oi_bucket_{suffix}"),
                metrics.get(f"net_oi_{suffix}"),
            )
            if current_net_total is None and current_call_total is not None and current_put_total is not None:
                current_net_total = current_call_total + current_put_total

            call_oi = _delta(current_call_total, _record_float(prev1, f"call_oi_bucket_{suffix}"))
            put_oi = _delta(current_put_total, _record_float(prev1, f"put_oi_bucket_{suffix}"))
            net_oi = _delta(current_net_total, _record_float(prev1, f"oi_bucket_{suffix}"))
            delta3d = _delta(current_net_total, _record_float(prev3, f"oi_bucket_{suffix}"))
            delta5d = _delta(current_net_total, _record_float(prev5, f"oi_bucket_{suffix}"))

            if all(value is None for value in (call_oi, put_oi, net_oi, delta3d, delta5d)):
                continue

            trend_reference = net_oi if net_oi is not None else delta3d if delta3d is not None else delta5d
            computed[bucket] = {
                "bucket": bucket,
                "callOI": call_oi,
                "putOI": put_oi,
                "netOI": net_oi,
                "delta3d": delta3d,
                "delta5d": delta5d,
                "trend": _infer_trend(trend_reference, call_oi, put_oi),
            }

        return computed

    iv_history_positioning = _build_iv_history_positioning()

    positioning: List[Dict[str, Any]] = []
    raw_positioning = metrics.get("optionsPositioning", []) if isinstance(metrics.get("optionsPositioning"), list) else []
    for row in raw_positioning:
        if not isinstance(row, dict):
            continue
        bucket = _normalize_bucket(
            row.get("bucket")
            or row.get("term")
            or row.get("term_bucket")
            or row.get("range")
            or row.get("label")
        )
        if not bucket:
            continue
        call_oi = _as_float(row.get("callOI"), row.get("call_oi"), row.get("call_delta_oi"), row.get("callDeltaOI"))
        put_oi = _as_float(row.get("putOI"), row.get("put_oi"), row.get("put_delta_oi"), row.get("putDeltaOI"))
        net_oi = _as_float(row.get("netOI"), row.get("net_oi"), row.get("net_delta_oi"), row.get("netDeltaOI"))
        delta3d = _as_float(row.get("delta3d"), row.get("delta_3d"))
        delta5d = _as_float(row.get("delta5d"), row.get("delta_5d"))
        # Backward-compat: older ETF refresh payload stored unknown call/put splits as 0.
        # Treat that placeholder as "missing" when bucket net/delta exists.
        if call_oi == 0 and put_oi == 0 and any(
            value not in (None, 0) for value in (net_oi, delta3d, delta5d)
        ):
            call_oi = None
            put_oi = None
        if net_oi is None and call_oi is not None and put_oi is not None:
            net_oi = call_oi - put_oi
        if delta3d is None:
            delta3d = net_oi
        trend = _infer_trend(net_oi, call_oi, put_oi, str(row.get("trend") or "").strip())
        if call_oi is None and put_oi is None and net_oi is None and delta3d is None and delta5d is None:
            continue
        positioning.append(
            {
                "bucket": bucket,
                "callOI": call_oi,
                "putOI": put_oi,
                "netOI": net_oi,
                "delta3d": delta3d,
                "delta5d": delta5d,
                "trend": trend,
            }
        )

    supplemental_positioning: Dict[str, Dict[str, Any]] = {}
    for bucket, suffix in bucket_suffixes:
        history_row = iv_history_positioning.get(bucket) or {}
        call_oi = _as_float(
            history_row.get("callOI"),
            getattr(latest_iv_record, f"call_delta_oi_{suffix}", None),
            metrics.get(f"call_delta_oi_{suffix}"),
            metrics.get(f"call_oi_{suffix}"),
            metrics.get(f"call_oi_bucket_{suffix}"),
            mc_data.get(f"call_delta_oi_{suffix}"),
        )
        put_oi = _as_float(
            history_row.get("putOI"),
            getattr(latest_iv_record, f"put_delta_oi_{suffix}", None),
            metrics.get(f"put_delta_oi_{suffix}"),
            metrics.get(f"put_oi_{suffix}"),
            metrics.get(f"put_oi_bucket_{suffix}"),
            mc_data.get(f"put_delta_oi_{suffix}"),
        )
        net_oi = _as_float(
            history_row.get("netOI"),
            getattr(latest_iv_record, f"net_delta_oi_{suffix}", None),
            metrics.get(f"net_delta_oi_{suffix}"),
            metrics.get(f"delta_oi_{suffix}"),
            metrics.get(f"net_oi_{suffix}"),
            metrics.get(f"oi_bucket_{suffix}"),
            mc_data.get(f"net_delta_oi_{suffix}"),
            mc_data.get(f"delta_oi_{suffix}"),
            mc_data.get(f"oi_bucket_{suffix}"),
        )
        if net_oi is None and call_oi is not None and put_oi is not None:
            net_oi = call_oi - put_oi
        delta3d = _as_float(
            history_row.get("delta3d"),
            metrics.get(f"delta3d_{suffix}"),
            metrics.get(f"delta_3d_{suffix}"),
            metrics.get(f"net_delta3d_{suffix}"),
            mc_data.get(f"delta3d_{suffix}"),
            mc_data.get(f"delta_3d_{suffix}"),
        )
        delta5d = _as_float(
            history_row.get("delta5d"),
            metrics.get(f"delta5d_{suffix}"),
            metrics.get(f"delta_5d_{suffix}"),
            metrics.get(f"net_delta5d_{suffix}"),
            mc_data.get(f"delta5d_{suffix}"),
            mc_data.get(f"delta_5d_{suffix}"),
        )
        if delta3d is None:
            delta3d = net_oi
        if call_oi is None and put_oi is None and net_oi is None and delta3d is None and delta5d is None:
            continue
        supplemental_positioning[bucket] = {
            "bucket": bucket,
            "callOI": call_oi,
            "putOI": put_oi,
            "netOI": net_oi,
            "delta3d": delta3d,
            "delta5d": delta5d,
            "trend": _infer_trend(net_oi, call_oi, put_oi, str(history_row.get("trend") or "").strip()),
        }

    if positioning and supplemental_positioning:
        for row in positioning:
            bucket = row.get("bucket")
            if bucket not in supplemental_positioning:
                continue
            extra = supplemental_positioning[bucket]
            if row.get("callOI") is None and extra.get("callOI") is not None:
                row["callOI"] = extra.get("callOI")
            if row.get("putOI") is None and extra.get("putOI") is not None:
                row["putOI"] = extra.get("putOI")
            if row.get("netOI") is None and extra.get("netOI") is not None:
                row["netOI"] = extra.get("netOI")
            if row.get("delta3d") is None and extra.get("delta3d") is not None:
                row["delta3d"] = extra.get("delta3d")
            if row.get("delta5d") is None and extra.get("delta5d") is not None:
                row["delta5d"] = extra.get("delta5d")
            row["trend"] = _infer_trend(
                _as_float(row.get("netOI")),
                _as_float(row.get("callOI")),
                _as_float(row.get("putOI")),
                str(row.get("trend") or "").strip(),
            )
    elif not positioning and supplemental_positioning:
        positioning.extend(supplemental_positioning.values())

    heat_type = normalize_heat_type(mc_data.get("heat_type") or stock.heat_type or "normal")

    updated_candidates = []
    if stock.updated_at:
        updated_candidates.append(stock.updated_at)
    if latest_mc_record and latest_mc_record.created_at:
        updated_candidates.append(latest_mc_record.created_at)
    updated_at = max(updated_candidates).isoformat() if updated_candidates else None

    source_tags = ["Database"]
    if latest_mc_record is not None:
        source_tags.append("MarketChameleon")
    if positioning or latest_iv_record is not None:
        source_tags.append("Futu")

    earnings_event = _as_str(
        metrics.get("earningsDate"),
        metrics.get("earnings_date"),
        mc_data.get("earnings_date"),
        mc_data.get("Earnings"),
        mc_data.get("earningsDate"),
        mc_data.get("earnings"),
    )

    return {
        "symbol": stock.symbol,
        # Heat metrics
        "heatScore": round(heat_score, 2),
        "heatType": heat_type,
        "relativeNominal": relative_nominal,
        "relativeVolume": relative_volume,
        "tradeCount": trade_count,

        # Risk pricing metrics
        "riskScore": round(risk_score, 2),
        "ivr": ivr,
        "iv30": iv30,
        "iv60": iv60,
        "iv90": iv90,
        "iv30Change": iv30_change,

        # Term structure metrics
        "termStructureScore": round(term_structure_score),
        "slope": slope,
        "slopeChange": slope_change,
        "termStructureInterpretation": term_structure_interpretation,
        "earningsEvent": earnings_event,

        # Positioning data
        "positioning": positioning,

        # Metadata
        "dataSource": " / ".join(source_tags),
        "updatedAt": updated_at,
    }
