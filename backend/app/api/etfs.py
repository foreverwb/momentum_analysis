"""
ETF API 端点
从数据库读取 ETF 数据（已移除 mock 数据）
集成 IBKR/Futu API 获取实时数据并计算评分
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date, datetime

from app.models import (
    get_db, ETF, ETFHolding, VALID_SECTOR_SYMBOLS,
    PriceHistory, IVData, ScoreSnapshot
)

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
        "data_sources": data_sources,
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