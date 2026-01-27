"""
ETF API 端点
从数据库读取 ETF 数据（已移除 mock 数据）
集成 IBKR/Futu API 获取实时数据并计算评分
"""

import asyncio
import logging
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel

from app.models import (
    get_db, ETF, ETFHolding, VALID_SECTOR_SYMBOLS, Stock, ImportedData,
    PriceHistory, IVData, ScoreSnapshot
)

router = APIRouter()
logger = logging.getLogger(__name__)


class HoldingsCoverageRequest(BaseModel):
    coverage_type: str
    coverage_value: int
    sources: Optional[List[str]] = None
    concurrent: Optional[bool] = None


def format_etf_response(etf: ETF, include_holdings: bool = False, db: Session = None) -> dict:
    """格式化 ETF 响应数据"""

    # 从持仓数据动态计算 coverageRanges
    coverage_ranges = []
    if etf.holdings:
        # 获取最新日期的持仓
        latest_date = max(h.data_date for h in etf.holdings) if etf.holdings else None
        if latest_date:
            holdings_for_date = [h for h in etf.holdings if h.data_date == latest_date]

            # 检查是否有足够的持仓数据来确定覆盖范围
            if holdings_for_date:
                total_holdings = len(holdings_for_date)
                total_weight = sum(h.weight for h in holdings_for_date)

                # 检查可能的 Top 覆盖范围
                for top_n in [10, 15, 20, 30]:
                    if total_holdings >= top_n:
                        coverage_ranges.append(f'top{top_n}')

                # 检查可能的 Weight 覆盖范围
                for weight_pct in [60, 65, 70, 75, 80, 85]:
                    accumulated_weight = 0
                    for h in sorted(holdings_for_date, key=lambda x: x.weight, reverse=True):
                        accumulated_weight += h.weight
                        if accumulated_weight >= weight_pct:
                            coverage_ranges.append(f'weight{weight_pct}')
                            break

    result = {
        "id": etf.id,
        "symbol": etf.symbol,
        "name": etf.name,
        "type": etf.type,
        "score": etf.score or 0.0,
        "rank": etf.rank or 0,
        "delta": etf.delta or {"delta3d": None, "delta5d": None},
        "completeness": etf.completeness or 0.0,
        "holdingsCount": etf.holdings_count or 0,
        "coverageRanges": list(set(coverage_ranges))  # 去除重复
    }

    if etf.type == "industry" and etf.parent_sector:
        result["parentSector"] = etf.parent_sector

    if include_holdings and etf.holdings:
        # 只返回最新日期的持仓，并附带最新评分（若有）
        latest_date = max(h.data_date for h in etf.holdings) if etf.holdings else None
        if latest_date:
            holdings_today = [h for h in etf.holdings if h.data_date == latest_date]

            score_map = {}
            if db:
                try:
                    tickers = [h.ticker for h in holdings_today]
                    if tickers:
                        stocks = db.query(Stock).filter(Stock.symbol.in_(tickers)).all()
                        for stock in stocks:
                            score_map[stock.symbol] = stock.score_total
                except Exception as exc:
                    logger.warning(f"Stock score query failed, skip scores: {exc}")

            result["holdings"] = [
                {
                    "ticker": h.ticker,
                    "weight": h.weight,
                    "score": score_map.get(h.ticker)
                }
                for h in holdings_today
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
    
    return [format_etf_response(etf, include_holdings=include_holdings, db=db) for etf in etfs]


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
    
    return [format_etf_response(etf, include_holdings=include_holdings, db=db) for etf in etfs]


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
    
    return [format_etf_response(etf, include_holdings=include_holdings, db=db) for etf in etfs]


@router.get("/score-snapshots", response_model=List[dict])
async def get_etf_score_snapshots(
    symbols: Optional[str] = Query(None, description="逗号分隔的 ETF 符号列表"),
    db: Session = Depends(get_db)
):
    """
    获取 ETF 最新评分快照

    返回:
    [
      {
        "symbol": "XLK",
        "date": "2026-02-01",
        "total_score": 47.9,
        "score_breakdown": {...},
        "thresholds_pass": true
      }
    ]
    """
    if not symbols:
        return []

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return []

    results = []
    for symbol in symbol_list:
        snapshot = db.query(ScoreSnapshot).filter(
            ScoreSnapshot.symbol == symbol,
            ScoreSnapshot.symbol_type == 'etf'
        ).order_by(ScoreSnapshot.date.desc()).first()

        if snapshot:
            results.append({
                "symbol": snapshot.symbol,
                "date": snapshot.date.isoformat() if snapshot.date else None,
                "total_score": snapshot.total_score,
                "score_breakdown": snapshot.score_breakdown,
                "thresholds_pass": snapshot.thresholds_pass
            })

    return results


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
    
    return format_etf_response(etf, include_holdings=include_holdings, db=db)


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
    
    return format_etf_response(etf, include_holdings=include_holdings, db=db)


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


@router.post("/symbol/{symbol}/refresh", response_model=dict)
async def refresh_etf_data(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    刷新 ETF 数据（从 IBKR/Futu 获取数据并重新计算评分）
    
    数据源:
    - IBKR: 价格数据、相对动量(RelMom)、趋势质量
    - Futu: IV 期限结构 (可选)
    
    评分体系:
    - 相对动量 (45%): IBKR
    - 趋势质量 (25%): IBKR + 本地计算
    - 广度 (20%): 需要 Finviz 数据
    - 期权确认 (10%): Futu/MarketChameleon
    
    参数:
    - symbol: ETF 符号
    """
    from app.services.orchestrator import get_orchestrator
    from app.services.calculators import ETFScoreCalculator
    from app.models import PriceHistory, IVData, ScoreSnapshot
    
    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")
    
    orchestrator = get_orchestrator()
    broker_status = orchestrator.get_broker_status()
    
    # 跟踪数据完整性
    data_sources = {
        'ibkr_price': False,
        'ibkr_relmom': False,
        'ibkr_trend': False,
        'futu_iv': False,
        'finviz_breadth': False,
        'mc_options': False
    }
    
    score_result = {
        'rel_mom': {'score': 0, 'data': None},
        'trend_quality': {'score': 0, 'data': None},
        'breadth': {'score': 50, 'data': None},  # 默认中性
        'options_confirm': {'score': 50, 'data': None}  # 默认中性
    }
    
    warnings = []
    
    # ==================== 1. 从 IBKR 获取数据 ====================
    ibkr_connected = broker_status.get('ibkr', {}).get('is_connected', False)
    
    if not ibkr_connected:
        # 尝试连接 IBKR
        try:
            ibkr_connected = await orchestrator.connect_ibkr()
            if ibkr_connected:
                warnings.append("已自动连接 IBKR")
        except Exception as e:
            warnings.append(f"IBKR 连接失败: {str(e)}")
    
    if ibkr_connected and orchestrator._ibkr:
        ibkr = orchestrator._ibkr
        
        # 1.1 获取价格数据
        try:
            price_df = ibkr.get_ohlcv_data(etf.symbol, '100 D')
            if price_df is not None and not price_df.empty:
                data_sources['ibkr_price'] = True
                
                # 保存价格数据到数据库
                from datetime import date as date_type
                today = date_type.today()
                for _, row in price_df.iterrows():
                    try:
                        row_date = row['date'].date() if hasattr(row['date'], 'date') else row['date']
                        existing = db.query(PriceHistory).filter(
                            PriceHistory.symbol == etf.symbol,
                            PriceHistory.date == row_date
                        ).first()
                        if not existing:
                            price_record = PriceHistory(
                                symbol=etf.symbol,
                                date=row_date,
                                open=float(row['open']),
                                high=float(row['high']),
                                low=float(row['low']),
                                close=float(row['close']),
                                volume=int(row['volume']),
                                source='ibkr'
                            )
                            db.add(price_record)
                    except Exception:
                        pass  # 忽略单条记录的错误
                db.commit()
        except Exception as e:
            warnings.append(f"IBKR 价格数据获取失败: {str(e)}")
        
        # 1.2 计算相对动量 (RelMom)
        try:
            relmom_result = ibkr.analyze_sector_vs_spy(etf.symbol, 'SPY')
            if relmom_result:
                data_sources['ibkr_relmom'] = True
                
                # RelMom 值转换为 0-100 分数 (范围 [-0.1, 0.15] 映射到 [0, 100])
                rel_mom = relmom_result.get('RelMom', 0) or 0
                rel_mom_score = (rel_mom + 0.1) / 0.25 * 100
                rel_mom_score = min(100, max(0, rel_mom_score))
                
                score_result['rel_mom'] = {
                    'score': round(rel_mom_score, 2),
                    'data': {
                        'RS': relmom_result.get('RS'),
                        'RS_5D': relmom_result.get('RS_5D'),
                        'RS_20D': relmom_result.get('RS_20D'),
                        'RS_63D': relmom_result.get('RS_63D'),
                        'RelMom': relmom_result.get('RelMom'),
                        'strength': relmom_result.get('strength', 'NEUTRAL'),
                        'description': relmom_result.get('description', '')
                    }
                }
        except Exception as e:
            warnings.append(f"RelMom 计算失败: {str(e)}")
        
        # 1.3 计算趋势质量
        try:
            from app.services.calculators.technical import calculate_sma, calculate_sma_slope, calculate_max_drawdown
            
            if data_sources['ibkr_price'] and price_df is not None and len(price_df) >= 50:
                prices = price_df['close']
                
                # 计算均线
                sma20 = calculate_sma(prices, 20)
                sma50 = calculate_sma(prices, 50)
                
                current_price = float(prices.iloc[-1])
                current_sma20 = float(sma20.iloc[-1])
                current_sma50 = float(sma50.iloc[-1])
                
                # 评分项
                price_above_sma50 = current_price > current_sma50
                sma20_above_sma50 = current_sma20 > current_sma50
                sma20_slope = calculate_sma_slope(sma20, period=5)
                max_dd = calculate_max_drawdown(prices, 20)
                
                # 计算分数 (每项25分)
                trend_score = 0
                if price_above_sma50:
                    trend_score += 25
                if sma20_above_sma50:
                    trend_score += 25
                if sma20_slope > 0:
                    trend_score += 25
                if max_dd > -0.10:
                    trend_score += 25
                
                data_sources['ibkr_trend'] = True
                score_result['trend_quality'] = {
                    'score': trend_score,
                    'data': {
                        'price': round(current_price, 2),
                        'sma20': round(current_sma20, 2),
                        'sma50': round(current_sma50, 2),
                        'price_above_sma50': price_above_sma50,
                        'sma20_above_sma50': sma20_above_sma50,
                        'sma20_slope': round(sma20_slope, 4),
                        'max_drawdown_20d': round(max_dd, 4)
                    }
                }
        except Exception as e:
            warnings.append(f"趋势质量计算失败: {str(e)}")
    else:
        warnings.append("IBKR 未连接，无法获取价格数据和计算 RelMom")
    
    # ==================== 2. 从 Futu 获取 IV 数据 ====================
    futu_connected = broker_status.get('futu', {}).get('is_connected', False)
    
    if not futu_connected:
        # 尝试连接 Futu
        try:
            futu_connected = await orchestrator.connect_futu()
            if futu_connected:
                warnings.append("已自动连接 Futu")
        except Exception:
            pass  # Futu 是可选的
    
    if futu_connected and orchestrator._futu:
        futu = orchestrator._futu
        
        try:
            iv_results = futu.fetch_iv_terms([etf.symbol], max_days=120)
            if etf.symbol in iv_results:
                iv_data = iv_results[etf.symbol]
                if iv_data.is_valid():
                    data_sources['futu_iv'] = True
                    
                    # 保存 IV 数据
                    from datetime import date as date_type
                    today = date_type.today()
                    existing_iv = db.query(IVData).filter(
                        IVData.symbol == etf.symbol,
                        IVData.date == today
                    ).first()
                    
                    if existing_iv:
                        existing_iv.iv7 = iv_data.iv7
                        existing_iv.iv30 = iv_data.iv30
                        existing_iv.iv60 = iv_data.iv60
                        existing_iv.iv90 = iv_data.iv90
                        existing_iv.total_oi = iv_data.total_oi
                    else:
                        iv_record = IVData(
                            symbol=etf.symbol,
                            date=today,
                            iv7=iv_data.iv7,
                            iv30=iv_data.iv30,
                            iv60=iv_data.iv60,
                            iv90=iv_data.iv90,
                            total_oi=iv_data.total_oi,
                            source='futu'
                        )
                        db.add(iv_record)
                    
                    # 计算期权确认分数 (基于 IV 期限结构)
                    # IV30 < IV60 < IV90 表示正常期限结构，有利
                    iv30 = iv_data.iv30 or 0
                    iv60 = iv_data.iv60 or 0
                    iv90 = iv_data.iv90 or 0
                    
                    term_score = 50  # 默认中性
                    if iv30 > 0 and iv60 > 0 and iv90 > 0:
                        if iv30 < iv60 < iv90:
                            term_score = 80  # 正常期限结构
                        elif iv30 > iv90:
                            term_score = 30  # 倒挂，风险较高
                    
                    score_result['options_confirm'] = {
                        'score': term_score,
                        'data': {
                            'iv7': iv_data.iv7,
                            'iv30': iv_data.iv30,
                            'iv60': iv_data.iv60,
                            'iv90': iv_data.iv90,
                            'total_oi': iv_data.total_oi,
                            'term_structure': 'normal' if term_score >= 70 else ('inverted' if term_score < 40 else 'flat')
                        }
                    }
                    db.commit()
        except Exception as e:
            warnings.append(f"Futu IV 数据获取失败: {str(e)}")
    else:
        warnings.append("Futu 未连接，使用默认期权评分")
    
    # ==================== 3. 计算综合评分 ====================
    # 权重: RelMom 45%, Trend 25%, Breadth 20%, Options 10%
    weights = {
        'rel_mom': 0.45,
        'trend_quality': 0.25,
        'breadth': 0.20,
        'options_confirm': 0.10
    }
    
    total_score = (
        weights['rel_mom'] * score_result['rel_mom']['score'] +
        weights['trend_quality'] * score_result['trend_quality']['score'] +
        weights['breadth'] * score_result['breadth']['score'] +
        weights['options_confirm'] * score_result['options_confirm']['score']
    )
    
    # 计算数据完整度
    completeness_weight = {
        'ibkr_price': 20,
        'ibkr_relmom': 25,
        'ibkr_trend': 15,
        'futu_iv': 10,
        'finviz_breadth': 20,
        'mc_options': 10
    }
    completeness = sum(
        completeness_weight[k] for k, v in data_sources.items() if v
    )
    
    # 检查硬性门槛
    thresholds_pass = True
    threshold_details = {}
    
    # 门槛1: Price > SMA50
    if score_result['trend_quality']['data']:
        price_above_sma50 = score_result['trend_quality']['data'].get('price_above_sma50', False)
        threshold_details['price_above_sma50'] = 'PASS' if price_above_sma50 else 'FAIL'
        if not price_above_sma50:
            thresholds_pass = False
    else:
        threshold_details['price_above_sma50'] = 'NO_DATA'
    
    # 门槛2: RS_20D > 0
    if score_result['rel_mom']['data']:
        rs_20d = score_result['rel_mom']['data'].get('RS_20D', 0) or 0
        threshold_details['rs_20d_positive'] = 'PASS' if rs_20d > 0 else 'FAIL'
        if rs_20d <= 0:
            thresholds_pass = False
    else:
        threshold_details['rs_20d_positive'] = 'NO_DATA'
    
    # ==================== 4. 更新数据库 ====================
    etf.score = round(total_score, 2)
    etf.completeness = completeness
    etf.updated_at = datetime.now()
    
    # 保存评分快照
    from datetime import date as date_type
    today = date_type.today()
    existing_snapshot = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == etf.symbol,
        ScoreSnapshot.symbol_type == 'etf',
        ScoreSnapshot.date == today
    ).first()
    
    if existing_snapshot:
        existing_snapshot.total_score = total_score
        existing_snapshot.score_breakdown = score_result
        existing_snapshot.thresholds_pass = thresholds_pass
    else:
        snapshot = ScoreSnapshot(
            symbol=etf.symbol,
            symbol_type='etf',
            date=today,
            total_score=total_score,
            score_breakdown=score_result,
            thresholds_pass=thresholds_pass
        )
        db.add(snapshot)
    
    # 重新计算同类型 ETF 排名
    etfs_of_same_type = db.query(ETF).filter(
        ETF.type == etf.type,
        ETF.score > 0
    ).order_by(ETF.score.desc()).all()
    
    for idx, e in enumerate(etfs_of_same_type, 1):
        e.rank = idx
    
    db.commit()
    
    # ==================== 5. 返回结果 ====================
    normalized_sources = {key: bool(value) for key, value in data_sources.items()}

    return {
        "status": "success",
        "symbol": etf.symbol,
        "message": f"ETF {etf.symbol} 数据已刷新",
        "score": etf.score,
        "rank": etf.rank,
        "completeness": completeness,
        "thresholds_pass": thresholds_pass,
        "thresholds": threshold_details,
        "breakdown": {
            "rel_mom": score_result['rel_mom'],
            "trend_quality": score_result['trend_quality'],
            "breadth": score_result['breadth'],
            "options_confirm": score_result['options_confirm']
        },
        "data_sources": normalized_sources,
        "warnings": warnings if warnings else None
    }


@router.post("/symbol/{symbol}/refresh-holdings", response_model=dict)
async def refresh_holdings_data(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    刷新 ETF Holdings 数据状态
    
    参数:
    - symbol: ETF 符号
    """
    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")
    
    # 获取最新的持仓数据统计
    latest_date = db.query(func.max(ETFHolding.data_date)).filter(
        ETFHolding.etf_id == etf.id
    ).scalar()
    
    if not latest_date:
        return {
            "status": "warning",
            "symbol": etf.symbol,
            "message": "没有持仓数据。请先通过 CLI 或导入功能上传 Holdings 数据。",
            "holdingsCount": 0
        }
    
    # 更新持仓数量
    holdings_count = db.query(func.count(ETFHolding.id)).filter(
        ETFHolding.etf_id == etf.id,
        ETFHolding.data_date == latest_date
    ).scalar()
    
    etf.holdings_count = holdings_count
    etf.updated_at = datetime.now()
    db.commit()
    
    return {
        "status": "success",
        "symbol": etf.symbol,
        "message": f"Holdings 数据已刷新，共 {holdings_count} 条记录",
        "holdingsCount": holdings_count,
        "latestDate": latest_date.isoformat() if latest_date else None
    }


@router.post("/symbol/{symbol}/calculate", response_model=dict)
async def calculate_etf_score(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    计算 ETF 评分
    
    参数:
    - symbol: ETF 符号
    """
    from app.services.calculators import ETFScoreCalculator
    
    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")
    
    # 检查持仓数据
    if etf.holdings_count == 0:
        return {
            "status": "error",
            "symbol": etf.symbol,
            "message": "没有持仓数据，无法计算评分",
            "score": 0,
            "rank": 0,
            "completeness": 0
        }
    
    try:
        # 使用评分计算器
        calculator = ETFScoreCalculator()
        result = calculator.calculate_score(etf.symbol, etf.type)
        
        # 更新 ETF 记录
        etf.score = result.get('total_score', 0)
        etf.completeness = result.get('completeness', 0)
        etf.delta = {
            'delta3d': result.get('delta3d'),
            'delta5d': result.get('delta5d')
        }
        etf.updated_at = datetime.now()
        
        # 重新计算排名
        etfs_of_same_type = db.query(ETF).filter(
            ETF.type == etf.type,
            ETF.score > 0
        ).order_by(ETF.score.desc()).all()
        
        for idx, e in enumerate(etfs_of_same_type, 1):
            e.rank = idx
        
        db.commit()
        
        return {
            "status": "success",
            "symbol": etf.symbol,
            "score": etf.score,
            "rank": etf.rank,
            "completeness": etf.completeness
        }
    except Exception as e:
        return {
            "status": "error",
            "symbol": etf.symbol,
            "message": f"计算评分失败: {str(e)}",
            "score": etf.score or 0,
            "rank": etf.rank or 0,
            "completeness": etf.completeness or 0
        }


@router.post("/batch-refresh", response_model=dict)
async def batch_refresh_etf_data(
    etf_type: str = Query("sector", description="ETF 类型: sector 或 industry"),
    db: Session = Depends(get_db)
):
    """
    批量刷新 ETF 数据（从 IBKR/Futu 获取数据并重新计算所有 ETF 评分）
    
    参数:
    - etf_type: ETF 类型 (sector/industry)
    """
    from app.services.orchestrator import get_orchestrator
    
    # 获取所有指定类型的 ETF
    etfs = db.query(ETF).filter(ETF.type == etf_type).all()
    
    if not etfs:
        return {
            "status": "warning",
            "message": f"没有找到类型为 {etf_type} 的 ETF"
        }
    
    orchestrator = get_orchestrator()
    broker_status = orchestrator.get_broker_status()
    
    # 检查 IBKR 连接
    ibkr_connected = broker_status.get('ibkr', {}).get('is_connected', False)
    if not ibkr_connected:
        try:
            ibkr_connected = await orchestrator.connect_ibkr()
        except Exception:
            pass
    
    if not ibkr_connected:
        return {
            "status": "error",
            "message": "IBKR 未连接，无法批量刷新数据。请先连接 IBKR。",
            "broker_status": broker_status
        }
    
    results = []
    success_count = 0
    error_count = 0
    
    for etf in etfs:
        try:
            # 调用单个刷新接口的逻辑
            result = await refresh_etf_data(etf.symbol, db)
            results.append({
                "symbol": etf.symbol,
                "status": result.get("status"),
                "score": result.get("score"),
                "completeness": result.get("completeness")
            })
            if result.get("status") == "success":
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            results.append({
                "symbol": etf.symbol,
                "status": "error",
                "message": str(e)
            })
            error_count += 1
    
    return {
        "status": "success" if error_count == 0 else "partial",
        "message": f"批量刷新完成: {success_count} 成功, {error_count} 失败",
        "total": len(etfs),
        "success_count": success_count,
        "error_count": error_count,
        "results": results
    }


@router.get("/refresh-requirements", response_model=dict)
async def get_refresh_requirements():
    """
    获取刷新 ETF 数据所需的条件
    
    返回:
    - Broker 连接状态
    - 数据源依赖关系
    - 评分体系说明
    """
    from app.services.orchestrator import get_orchestrator
    
    orchestrator = get_orchestrator()
    broker_status = orchestrator.get_broker_status()
    
    ibkr_status = broker_status.get('ibkr', {})
    futu_status = broker_status.get('futu', {})
    
    return {
        "broker_status": {
            "ibkr": {
                "is_connected": ibkr_status.get('is_connected', False),
                "required": True,
                "provides": ["price_data", "relmom", "trend_quality"],
                "weight": "70% of total score",
                "connect_url": "POST /api/broker/ibkr/connect"
            },
            "futu": {
                "is_connected": futu_status.get('is_connected', False),
                "required": False,
                "provides": ["iv_term_structure", "options_data"],
                "weight": "10% of total score",
                "connect_url": "POST /api/broker/futu/connect"
            }
        },
        "score_breakdown": {
            "rel_mom": {
                "weight": "45%",
                "source": "IBKR",
                "description": "相对动量 (RelMom) - 基于 RS 变化率计算"
            },
            "trend_quality": {
                "weight": "25%",
                "source": "IBKR + 本地计算",
                "description": "趋势质量 - SMA 排列、斜率、回撤"
            },
            "breadth": {
                "weight": "20%",
                "source": "Finviz (需手动导入)",
                "description": "市场广度 - %Above50DMA 等"
            },
            "options_confirm": {
                "weight": "10%",
                "source": "Futu / MarketChameleon",
                "description": "期权确认 - IV 期限结构"
            }
        },
        "thresholds": {
            "price_above_sma50": "必须: 价格 > 50日均线",
            "rs_20d_positive": "必须: 20日相对强度 > 0"
        },
        "instructions": [
            "1. 首先连接 IBKR: POST /api/broker/ibkr/connect",
            "2. (可选) 连接 Futu: POST /api/broker/futu/connect",
            "3. 刷新单个 ETF: POST /api/etfs/symbol/{symbol}/refresh",
            "4. 批量刷新: POST /api/etfs/batch-refresh?etf_type=sector"
        ]
    }


@router.post("/symbol/{symbol}/refresh-holdings-by-coverage")
async def refresh_holdings_by_coverage(
    symbol: str,
    request: HoldingsCoverageRequest,
    db: Session = Depends(get_db)
):
    """
    基于覆盖范围刷新 ETF 持仓股票数据

    参数:
    - symbol: ETF 符号
    - coverage_type: 覆盖范围类型 ("top" 或 "weight")
    - coverage_value: 覆盖范围值 (如果 type=top 则为数字如 10、15；如果 type=weight 则为百分比如 60、70)

    返回:
    {
      "status": "success|error",
      "symbol": "XLK",
      "coverage": "top10",
      "stocks_count": 10,
      "total_weight": 42.5,
      "completeness": {
        "coverage": "top10",
        "total_stocks": 10,
        "complete_count": 8,
        "pending_count": 2,
        "missing_count": 0,
        "average_completeness": 85.5
      },
      "updated_stocks": [
        {
          "ticker": "MSFT",
          "weight": 5.2,
          "price": 420.50,
          "change_1d": 1.2,
          "data_sources": ["ibkr"],
          "data_status": "complete",
          "completeness": 95.0,
          "updated_at": "2026-01-30T10:00:00Z"
        }
      ],
      "updated_at": "2026-01-30T10:00:00Z",
      "message": "已刷新 10 只持仓股票数据"
    }
    """
    from app.services.calculators.data_completeness import DataCompletenessCalculator

    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()

    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")

    coverage_type = request.coverage_type
    coverage_value = request.coverage_value

    # 获取最新的持仓数据
    from sqlalchemy import func
    latest_date = db.query(func.max(ETFHolding.data_date)).filter(
        ETFHolding.etf_symbol == symbol.upper()
    ).scalar()

    if not latest_date:
        raise HTTPException(status_code=404, detail=f"No holdings data found for {symbol}")

    # 获取持仓列表，按权重排序
    holdings_query = db.query(ETFHolding).filter(
        ETFHolding.etf_symbol == symbol.upper(),
        ETFHolding.data_date == latest_date
    ).order_by(ETFHolding.weight.desc())

    all_holdings = holdings_query.all()

    # 根据覆盖范围过滤
    filtered_holdings = []

    if coverage_type.lower() == "top":
        # Top N: 取前 N 只
        filtered_holdings = all_holdings[:coverage_value]
    elif coverage_type.lower() == "weight":
        # Weight X%: 取权重累积到 X% 的股票
        accumulated_weight = 0
        for holding in all_holdings:
            filtered_holdings.append(holding)
            accumulated_weight += holding.weight
            if accumulated_weight >= coverage_value:
                break
    else:
        raise HTTPException(status_code=400, detail=f"Invalid coverage_type: {coverage_type}")

    from app.services.calculators.momentum_pool import calculate_momentum_pool_result

    def _load_price_history(symbol: str, min_rows: int = 60) -> Optional[pd.DataFrame]:
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

    def _save_price_history(symbol: str, df: pd.DataFrame, source: str = "ibkr") -> None:
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

    def _get_imported(symbol: str, source: str) -> Optional[Dict[str, Any]]:
        record = db.query(ImportedData).filter(
            ImportedData.symbol == symbol.upper(),
            ImportedData.source == source
        ).order_by(ImportedData.date.desc()).first()
        return record.data if record else None

    def _get_latest_iv(symbol: str) -> Optional[Dict[str, Any]]:
        record = db.query(IVData).filter(
            IVData.symbol == symbol.upper()
        ).order_by(IVData.date.desc()).first()
        if not record:
            return None
        return {
            'iv30': record.iv30,
            'ivr': None
        }

    def _compute_deltas(symbol: str) -> Dict[str, Optional[float]]:
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

    # 并发获取股票数据
    from app.services.orchestrator import get_orchestrator
    orchestrator = get_orchestrator()

    broker_status = orchestrator.get_broker_status()
    if not broker_status.get("ibkr", {}).get("is_connected", False):
        try:
            await orchestrator.connect_ibkr()
        except Exception as e:
            logger.warning(f"IBKR connect failed: {e}")

    if not broker_status.get("futu", {}).get("is_connected", False):
        try:
            await orchestrator.connect_futu()
        except Exception as e:
            logger.warning(f"Futu connect failed: {e}")

    # 预取板块（或父板块）价格用于相对强度计算
    sector_symbol = etf.parent_sector if etf.type == "industry" and etf.parent_sector else etf.symbol
    sector_df = _load_price_history(sector_symbol)
    if sector_df is None and orchestrator._ibkr and orchestrator._ibkr.is_connected():
        try:
            sector_fetched = orchestrator._ibkr.get_ohlcv_data(sector_symbol, '1 Y')
            if sector_fetched is not None and not sector_fetched.empty:
                _save_price_history(sector_symbol, sector_fetched)
                sector_df = sector_fetched
        except Exception as e:
            logger.warning(f"Failed to get sector price data for {sector_symbol}: {e}")

    updated_stocks = []
    stock_semaphore = asyncio.Semaphore(5)  # 限制并发数为 5

    async def fetch_stock_data(holding: ETFHolding, idx: int, total_count: int):
        async with stock_semaphore:
            try:
                # 从 IBKR 获取价格数据
                price_data = None
                change_1d = None
                volume_data = None
                data_sources = []

                stock_df = None
                if orchestrator._ibkr and orchestrator._ibkr.is_connected():
                    try:
                        # 获取股票的日线数据（用于动能评分）
                        stock_df = orchestrator._ibkr.get_ohlcv_data(holding.ticker, '1 Y')
                        if stock_df is not None and not stock_df.empty:
                            latest_row = stock_df.iloc[-1]
                            price_data = float(latest_row.get('close', 0))
                            volume_data = float(latest_row.get('volume', 0))
                            data_sources.append('ibkr')

                            # 计算 1 日涨跌幅
                            if len(stock_df) >= 2:
                                prev_close = float(stock_df.iloc[-2].get('close', 0))
                                if prev_close > 0:
                                    change_1d = ((price_data - prev_close) / prev_close) * 100
                    except Exception as e:
                        logger.warning(f"Failed to get price data for {holding.ticker}: {e}")
                else:
                    stock_df = _load_price_history(holding.ticker)
                    if stock_df is not None and not stock_df.empty:
                        latest_row = stock_df.iloc[-1]
                        price_data = float(latest_row.get('close', 0))
                        volume_data = float(latest_row.get('volume', 0))

                # 从 Futu 获取 IV 数据（可选）
                iv30 = None
                if orchestrator._futu and orchestrator._futu.is_connected():
                    try:
                        iv_results = orchestrator._futu.fetch_iv_terms(
                            [holding.ticker],
                            max_days=120,
                            progress_total=total_count,
                            progress_offset=idx - 1
                        )
                        if holding.ticker in iv_results:
                            iv_data = iv_results[holding.ticker]
                            if iv_data.is_valid():
                                iv30 = iv_data.iv30
                                data_sources.append('futu')
                    except Exception as e:
                        logger.warning(f"Failed to get IV data for {holding.ticker}: {e}")

                # 构建持仓数据字典用于完整度评估
                holding_data = {
                    'price_data': price_data,
                    'volume': volume_data,
                    'change_1d': change_1d,
                    'iv30': iv30,
                    'data_sources': data_sources,
                    'updated_at': datetime.utcnow().isoformat()
                }

                return {
                    "ticker": holding.ticker,
                    "weight": holding.weight,
                    "price": price_data,
                    "change_1d": change_1d,
                    "data_sources": data_sources,
                    "iv30": iv30,
                    "price_df": stock_df,
                    "holding_data": holding_data,
                    "updated_at": datetime.utcnow().isoformat()
                }

            except Exception as e:
                logger.error(f"Error fetching data for {holding.ticker}: {e}")
                return {
                    "ticker": holding.ticker,
                    "weight": holding.weight,
                    "price": None,
                    "change_1d": None,
                    "data_sources": [],
                    "iv30": None,
                    "holding_data": {
                        'price_data': None,
                        'volume': None,
                        'change_1d': None,
                        'iv30': None,
                        'data_sources': [],
                        'updated_at': datetime.utcnow().isoformat()
                    },
                    "updated_at": datetime.utcnow().isoformat()
                }

    # 并发获取所有股票数据
    tasks = [fetch_stock_data(h, idx, len(filtered_holdings)) for idx, h in enumerate(filtered_holdings, start=1)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 计算数据完整度
    completeness_calculator = DataCompletenessCalculator(db)

    for result in results:
        if isinstance(result, dict):
            holding_data = result.pop('holding_data', {})
            price_df = result.pop('price_df', None)

            # 计算单只持仓的完整度
            completeness_status = completeness_calculator.calculate_holding_data_completeness(
                result['ticker'],
                holding_data
            )

            # 添加完整度信息到结果
            result['data_status'] = completeness_status.status
            result['completeness'] = completeness_status.completeness_score

            # 计算动能股评分并更新数据库
            score_value = None
            if price_df is None:
                price_df = _load_price_history(result['ticker'])

            if price_df is not None and not price_df.empty:
                _save_price_history(result['ticker'], price_df)
                finviz_data = _get_imported(result['ticker'], 'finviz')
                mc_data = _get_imported(result['ticker'], 'marketchameleon')
                iv_data = _get_latest_iv(result['ticker'])

                pool_result = calculate_momentum_pool_result(
                    price_df=price_df,
                    sector_df=sector_df,
                    finviz_data=finviz_data,
                    mc_data=mc_data,
                    iv_data=iv_data
                )

                if pool_result:
                    score_value = pool_result.total_score

                    stock = db.query(Stock).filter(Stock.symbol == result['ticker'].upper()).first()
                    if not stock:
                        stock = Stock(symbol=result['ticker'].upper())

                    sector_value = sector_symbol
                    if finviz_data and finviz_data.get('sector'):
                        sector_value = finviz_data.get('sector')
                    industry_value = finviz_data.get('industry') if finviz_data else None
                    if not industry_value:
                        industry_value = etf.name or etf.symbol

                    stock.name = finviz_data.get('company_name') if finviz_data else (stock.name or result['ticker'])
                    stock.sector = sector_value
                    stock.industry = industry_value
                    stock.price = float(price_df['close'].iloc[-1])
                    stock.score_total = pool_result.total_score
                    stock.scores = pool_result.scores
                    stock.metrics = pool_result.metrics
                    db.add(stock)
                    db.flush()

                    today = date.today()
                    existing_snapshot = db.query(ScoreSnapshot).filter(
                        ScoreSnapshot.symbol == stock.symbol,
                        ScoreSnapshot.symbol_type == 'stock',
                        ScoreSnapshot.date == today
                    ).first()
                    snapshot_payload = {
                        'scores': pool_result.scores,
                        'metrics': pool_result.metrics
                    }
                    thresholds_pass = (pool_result.scores.get('momentum', 0) >= 50 and pool_result.scores.get('trend', 0) >= 50)
                    if existing_snapshot:
                        existing_snapshot.total_score = pool_result.total_score
                        existing_snapshot.score_breakdown = snapshot_payload
                        existing_snapshot.thresholds_pass = thresholds_pass
                    else:
                        db.add(ScoreSnapshot(
                            symbol=stock.symbol,
                            symbol_type='stock',
                            date=today,
                            total_score=pool_result.total_score,
                            score_breakdown=snapshot_payload,
                            thresholds_pass=thresholds_pass
                        ))

                    stock.changes = _compute_deltas(stock.symbol)

            result['score'] = score_value

            updated_stocks.append(result)

    db.commit()

    # 评估覆盖范围的整体完整度
    holdings_with_data = [
        {
            'ticker': stock['ticker'],
            'weight': stock['weight'],
            'price_data': stock['price'],
            'volume': None,  # 不需要用于完整度评估
            'change_1d': stock['change_1d'],
            'iv30': stock.get('iv30'),
            'data_sources': stock['data_sources'],
            'updated_at': stock['updated_at']
        }
        for stock in updated_stocks
    ]

    coverage_completeness = completeness_calculator.assess_coverage_range_completeness(
        symbol.upper(),
        coverage_type.lower(),
        coverage_value,
        holdings_with_data
    )

    coverage_label = f"{coverage_type.lower()}{coverage_value}"
    total_weight = sum(h.weight for h in filtered_holdings)

    return {
        "status": "success",
        "symbol": symbol.upper(),
        "coverage": coverage_label,
        "stocks_count": len(filtered_holdings),
        "total_weight": round(total_weight, 2),
        "completeness": coverage_completeness.to_dict(),
        "updated_stocks": updated_stocks,
        "updated_at": datetime.utcnow().isoformat(),
        "message": f"已刷新 {len(filtered_holdings)} 只持仓股票数据，平均完备度 {round(coverage_completeness.average_completeness, 1)}%"
    }
