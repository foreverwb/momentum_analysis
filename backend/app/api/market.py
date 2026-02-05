"""
市场数据 API
Market Data API Endpoints

提供:
- 市场环境 (Regime Gate)
- ETF 排名
- 市场快照
- 数据同步
"""

from fastapi import APIRouter, Query, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date as date_type
import logging

from sqlalchemy.orm import Session

from app.models import get_db, MarketRegimeSnapshot

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency at runtime
    np = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["Market"])


# ==================== Pydantic Models ====================

class SPYData(BaseModel):
    """SPY 数据模型"""
    price: float
    sma20: float
    sma50: float
    dist_to_sma20: Optional[float] = None
    dist_to_sma50: Optional[float] = None
    return_20d: float
    sma20_slope: float


class RegimeIndicators(BaseModel):
    """Regime 指标模型"""
    price_above_sma20: bool
    price_above_sma50: bool
    sma20_slope: float
    sma20_slope_positive: bool
    sma20_above_sma50: bool
    return_20d: float
    dist_to_sma20: Optional[float] = None
    dist_to_sma50: Optional[float] = None
    near_sma50: Optional[bool] = None


class RegimeResponse(BaseModel):
    """Regime Gate 响应模型"""
    status: str = Field(..., description="状态码: A/B/C/UNKNOWN")
    regime_text: Optional[str] = Field(None, description="环境描述: RISK_ON/NEUTRAL/RISK_OFF")
    spy: Optional[SPYData] = None
    vix: Optional[float] = None
    indicators: Optional[RegimeIndicators] = None
    error: Optional[str] = None


class ETFRankingItem(BaseModel):
    """ETF 排名项"""
    symbol: str
    name: Optional[str] = None
    total_score: float
    rank: int
    thresholds_pass: bool
    type: str
    breakdown: Optional[Dict[str, Any]] = None


class ETFRankingsResponse(BaseModel):
    """ETF 排名响应"""
    type: str
    benchmark: str
    count: int
    rankings: List[ETFRankingItem]


class MarketSnapshotResponse(BaseModel):
    """市场快照响应"""
    timestamp: str
    broker_status: Dict[str, Any]
    regime: Dict[str, Any]
    spy: Optional[Dict[str, Any]] = None
    vix: Optional[float] = None
    sector_etf_rankings: List[Dict[str, Any]]


class SyncRequest(BaseModel):
    """数据同步请求"""
    symbols: List[str]
    sync_type: str = Field("price", description="同步类型: price/iv/all")


class SyncResponse(BaseModel):
    """数据同步响应"""
    status: str
    synced: List[str]
    failed: Optional[List[str]] = None
    total: int
    success_count: int


# ==================== ETF 名称映射 ====================

ETF_NAMES = {
    'XLK': 'Technology Select Sector SPDR',
    'XLF': 'Financial Select Sector SPDR',
    'XLE': 'Energy Select Sector SPDR',
    'XLV': 'Health Care Select Sector SPDR',
    'XLI': 'Industrial Select Sector SPDR',
    'XLY': 'Consumer Discretionary Select Sector SPDR',
    'XLP': 'Consumer Staples Select Sector SPDR',
    'XLU': 'Utilities Select Sector SPDR',
    'XLB': 'Materials Select Sector SPDR',
    'XLRE': 'Real Estate Select Sector SPDR',
    'XLC': 'Communication Services Select Sector SPDR',
    'SOXX': 'iShares Semiconductor ETF',
    'IGV': 'iShares Expanded Tech-Software Sector ETF',
    'SMH': 'VanEck Semiconductor ETF',
    'XBI': 'SPDR S&P Biotech ETF',
    'KBE': 'SPDR S&P Bank ETF',
    'XOP': 'SPDR S&P Oil & Gas Exploration & Production ETF',
    'OIH': 'VanEck Oil Services ETF',
    'ITA': 'iShares U.S. Aerospace & Defense ETF',
    'XRT': 'SPDR S&P Retail ETF',
    'XHB': 'SPDR S&P Homebuilders ETF',
    'IBB': 'iShares Biotechnology ETF',
}


# ==================== API Endpoints ====================

@router.get("/regime", response_model=RegimeResponse)
async def get_market_regime(
    refresh: bool = Query(False, description="是否强制刷新并写入数据库"),
    db: Session = Depends(get_db)
):
    """
    获取当前市场环境 (Regime Gate)
    
    返回:
    - status: A (满火力) / B (半火力) / C (低火力)
    - regime_text: RISK_ON / NEUTRAL / RISK_OFF
    - spy: SPY 价格和趋势信息
    - vix: VIX 指数
    - indicators: 详细指标
    """
    def normalize_json(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: normalize_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize_json(v) for v in value]
        if np is not None:
            if isinstance(value, np.generic):
                return value.item()
        if isinstance(value, (datetime, date_type)):
            return value.isoformat()
        return value

    def serialize_snapshot(snapshot: MarketRegimeSnapshot) -> Dict[str, Any]:
        return {
            "status": snapshot.status,
            "regime_text": normalize_json(snapshot.regime_text),
            "spy": normalize_json(snapshot.spy),
            "vix": normalize_json(snapshot.vix),
            "indicators": normalize_json(snapshot.indicators or {}),
            "error": normalize_json(snapshot.error)
        }

    try:
        today = date_type.today()

        if not refresh:
            existing_snapshot = db.query(MarketRegimeSnapshot).filter(
                MarketRegimeSnapshot.snapshot_date == today
            ).first()
            if existing_snapshot:
                return serialize_snapshot(existing_snapshot)
            return {
                "status": "NO_DATA",
                "regime_text": None,
                "spy": None,
                "vix": None,
                "indicators": {},
                "error": "No snapshot for today"
            }

        from app.services.orchestrator import get_orchestrator

        orchestrator = get_orchestrator()

        # 检查 IBKR 连接
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            # 尝试连接（失败时不抛出，返回 DISCONNECTED 状态）
            try:
                await orchestrator.connect_ibkr()
            except Exception as exc:
                logger.warning(f"IBKR 连接失败，返回离线状态: {exc}")

        # 获取 Regime 摘要
        result = await orchestrator.get_regime_summary()

        # 保底返回，避免抛 500 导致前端 CORS 误报
        if not isinstance(result, dict) or not result.get('status'):
            result = {
                "status": "ERROR",
                "regime_text": None,
                "spy": None,
                "vix": None,
                "indicators": {},
                "error": "Regime data unavailable"
            }

        normalized_result = normalize_json(result)

        # 写入/更新当日快照
        snapshot = db.query(MarketRegimeSnapshot).filter(
            MarketRegimeSnapshot.snapshot_date == today
        ).first()

        payload = {
            "status": normalized_result.get("status") or "UNKNOWN",
            "regime_text": normalized_result.get("regime_text"),
            "spy": normalized_result.get("spy"),
            "vix": normalized_result.get("vix"),
            "indicators": normalized_result.get("indicators"),
            "error": normalized_result.get("error")
        }

        if snapshot:
            snapshot.status = payload["status"]
            snapshot.regime_text = payload["regime_text"]
            snapshot.spy = payload["spy"]
            snapshot.vix = payload["vix"]
            snapshot.indicators = payload["indicators"]
            snapshot.error = payload["error"]
            snapshot.updated_at = datetime.utcnow()
        else:
            snapshot = MarketRegimeSnapshot(
                snapshot_date=today,
                **payload
            )
            db.add(snapshot)

        db.commit()

        return normalized_result

    except Exception as e:
        logger.error(f"获取 Regime 失败: {e}")
        # 不抛异常，返回错误对象，确保前端拿到 CORS headers
        return {
            "status": "ERROR",
            "regime_text": None,
            "spy": None,
            "vix": None,
            "indicators": {},
            "error": str(e)
        }


@router.get("/etf-rankings", response_model=ETFRankingsResponse)
async def get_etf_rankings(
    type: str = Query("sector", description="ETF 类型: sector/industry"),
    benchmark: str = Query("SPY", description="基准指数"),
    top_n: int = Query(11, description="返回数量")
):
    """
    获取 ETF 排名
    
    参数:
    - type: sector (板块 ETF) 或 industry (行业 ETF)
    - benchmark: 基准指数 (默认 SPY)
    - top_n: 返回数量 (默认 11)
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 检查 IBKR 连接
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            await orchestrator.connect_ibkr()
        
        # 计算排名
        rankings = await orchestrator.calculate_etf_rankings(
            etf_type=type,
            benchmark=benchmark
        )
        
        # 添加 ETF 名称
        for item in rankings:
            item['name'] = ETF_NAMES.get(item['symbol'], item['symbol'])
        
        return {
            'type': type,
            'benchmark': benchmark,
            'count': len(rankings),
            'rankings': rankings[:top_n]
        }
        
    except Exception as e:
        logger.error(f"获取 ETF 排名失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshot", response_model=MarketSnapshotResponse)
async def get_market_snapshot():
    """
    获取完整市场快照
    
    包含:
    - 当前时间戳
    - Broker 连接状态
    - 市场环境 (Regime)
    - SPY 数据
    - VIX
    - 板块 ETF Top 5 排名
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 尝试连接 Broker
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            await orchestrator.connect_ibkr()
        
        # 获取快照
        snapshot = await orchestrator.get_market_snapshot()
        
        return snapshot
        
    except Exception as e:
        logger.error(f"获取市场快照失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync", response_model=SyncResponse)
async def sync_market_data(
    request: SyncRequest,
    background_tasks: BackgroundTasks
):
    """
    同步市场数据
    
    触发 IBKR/Futu 数据获取
    
    参数:
    - symbols: 股票代码列表
    - sync_type: price (价格) / iv (IV) / all (全部)
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        results = {
            'status': 'success',
            'synced': [],
            'failed': [],
            'total': len(request.symbols),
            'success_count': 0
        }
        
        # 同步价格数据
        if request.sync_type in ['price', 'all']:
            broker_status = orchestrator.get_broker_status()
            if not broker_status.get('ibkr', {}).get('is_connected', False):
                await orchestrator.connect_ibkr()
            
            price_result = await orchestrator.sync_price_data(request.symbols)
            results['synced'].extend(price_result.get('synced', []))
            results['failed'].extend(price_result.get('failed', []))
        
        # 同步 IV 数据
        if request.sync_type in ['iv', 'all']:
            broker_status = orchestrator.get_broker_status()
            if not broker_status.get('futu', {}).get('is_connected', False):
                await orchestrator.connect_futu()
            
            iv_result = await orchestrator.sync_iv_data(request.symbols)
            # IV 同步结果合并
            for symbol in iv_result.get('synced', []):
                if symbol not in results['synced']:
                    results['synced'].append(symbol)
        
        results['success_count'] = len(results['synced'])
        
        return results
        
    except Exception as e:
        logger.error(f"数据同步失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/etf/{symbol}/detail")
async def get_etf_detail(
    symbol: str,
    benchmark: str = Query("SPY", description="基准指数")
):
    """
    获取单个 ETF 详情
    
    包含:
    - 综合评分
    - 各维度分数
    - 门槛检查结果
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 检查连接
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            await orchestrator.connect_ibkr()
        
        # 计算评分
        result = await orchestrator.calculate_etf_score(
            symbol=symbol,
            benchmark=benchmark
        )
        
        # 添加名称
        result['name'] = ETF_NAMES.get(symbol, symbol)
        
        return result
        
    except Exception as e:
        logger.error(f"获取 ETF {symbol} 详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spy")
async def get_spy_data():
    """
    获取 SPY 数据
    
    包含:
    - 当前价格
    - SMA20/50/200
    - 趋势判断
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            await orchestrator.connect_ibkr()
        
        spy_data = await orchestrator.get_spy_data()
        
        if spy_data is None:
            raise HTTPException(status_code=503, detail="Unable to fetch SPY data")
        
        return spy_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 SPY 数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vix")
async def get_vix():
    """
    获取 VIX 指数
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            await orchestrator.connect_ibkr()
        
        vix = await orchestrator.get_vix()
        
        return {
            'vix': vix,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取 VIX 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
