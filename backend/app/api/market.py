"""
市场数据 API
Market Data API Endpoints

提供:
- 市场环境 (Regime Gate)
- ETF 排名
- 市场快照
- 数据同步
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date as date_type, timedelta, timezone
import asyncio
import logging
import math

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import ETF, ETFHolding, IVData, MarketRegimeSnapshot, PriceHistory, RegimeStateHistory, get_db
from app.core.time_utils import beijing_today, get_beijing_cutoff_boundary, utc_now_iso

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency at runtime
    np = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["Market"])
REGIME_SUMMARY_TIMEOUT_SECONDS = 25


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


class HysteresisInfo(BaseModel):
    """Regime 滞后保护信息"""
    raw_status: str = Field(..., description="原始计算状态")
    effective_status: str = Field(..., description="滞后处理后的实际状态")
    regime_locked: bool = Field(False, description="是否处于冷却期")
    pending_switch_to: Optional[str] = Field(None, description="待切换目标状态")
    confirmation_progress: str = Field("0/3", description="确认进度 (当前/需要)")


class RegimeResponse(BaseModel):
    """Regime Gate 响应模型"""
    status: str = Field(..., description="状态码: A/B/C/UNKNOWN")
    regime_text: Optional[str] = Field(None, description="环境描述: RISK_ON/NEUTRAL/RISK_OFF")
    spy: Optional[SPYData] = None
    qqq: Optional[SPYData] = None
    vix: Optional[float] = None
    indicators: Optional[RegimeIndicators] = None
    hysteresis: Optional[HysteresisInfo] = None
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


class PriceFreshnessRequest(BaseModel):
    """价格新鲜度请求"""
    symbols: List[str]


class PriceFreshnessResponse(BaseModel):
    """价格新鲜度响应"""
    stale: List[str]
    fresh: List[str]
    sync_date: str


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


def _normalize_symbol_list(symbols: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for raw in symbols or []:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        deduped.append(symbol)
        seen.add(symbol)
    return deduped


def _expand_with_related_etfs(db: Session, symbols: List[str]) -> List[str]:
    """
    将股票代码扩展为“股票 + 最新持仓中关联的行业/板块 ETF”。

    说明:
    - 仅依赖 ETFHolding 最新快照，不依赖 Stock.sector 字段，避免详情页遗漏关联 ETF。
    - 返回顺序保持“原 symbols 在前，新增 ETF 依附其后”。
    """
    normalized = _normalize_symbol_list(symbols)
    if not normalized:
        return []

    latest_dates = db.query(
        ETFHolding.etf_symbol.label("etf_symbol"),
        func.max(ETFHolding.data_date).label("max_date"),
    ).group_by(ETFHolding.etf_symbol).subquery()

    rows = (
        db.query(ETFHolding.ticker, ETFHolding.etf_symbol)
        .join(
            latest_dates,
            and_(
                ETFHolding.etf_symbol == latest_dates.c.etf_symbol,
                ETFHolding.data_date == latest_dates.c.max_date,
            ),
        )
        .join(ETF, ETF.symbol == ETFHolding.etf_symbol)
        .filter(
            ETF.type.in_(["sector", "industry"]),
            ETFHolding.ticker.in_(normalized),
        )
        .all()
    )

    related: Dict[str, set] = {}
    for ticker, etf_symbol in rows:
        stock_symbol = str(ticker or "").strip().upper()
        etf = str(etf_symbol or "").strip().upper()
        if not stock_symbol or not etf:
            continue
        related.setdefault(stock_symbol, set()).add(etf)

    expanded = list(normalized)
    for stock_symbol in normalized:
        for etf in sorted(related.get(stock_symbol, set())):
            if etf not in expanded:
                expanded.append(etf)
    return expanded


def _to_finite_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _to_non_negative_int(value: Any) -> Optional[int]:
    parsed = _to_finite_float(value)
    if parsed is None:
        return None
    if parsed < 0:
        return 0
    return int(parsed)


def _to_int_or_none(value: Any) -> Optional[int]:
    parsed = _to_finite_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _normalize_price_row_date(value: Any) -> Optional[date_type]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    if hasattr(value, "date"):
        try:
            return value.date()
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if len(text) >= 10:
            try:
                return datetime.fromisoformat(text[:10]).date()
            except ValueError:
                return None
    return None


def _normalize_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        try:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return value.replace(tzinfo=None)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed
        try:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return parsed.replace(tzinfo=None)
    return None


def _get_beijing_sync_boundary() -> Dict[str, Any]:
    boundary = get_beijing_cutoff_boundary()
    return {
        "boundary_utc": boundary["boundary_utc"],
        "boundary_date": boundary["boundary_date"],
        "sync_date": boundary["sync_date"],
    }


def _upsert_price_history(
    db: Session,
    symbol: str,
    rows: List[Dict[str, Any]],
    source: str = "ibkr",
) -> Dict[str, int]:
    if not rows:
        return {"inserted": 0, "updated": 0}

    dates = [row["date"] for row in rows]
    existing_rows = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.symbol == symbol,
            PriceHistory.date.in_(dates),
        )
        .all()
    )
    existing_map = {item.date: item for item in existing_rows}

    inserted = 0
    updated = 0
    for payload in rows:
        row_date = payload["date"]
        existing = existing_map.get(row_date)
        if existing is None:
            db.add(
                PriceHistory(
                    symbol=symbol,
                    date=row_date,
                    open=payload["open"],
                    high=payload["high"],
                    low=payload["low"],
                    close=payload["close"],
                    volume=payload["volume"],
                    source=source,
                )
            )
            inserted += 1
            continue

        changed = False
        for field in ("open", "high", "low", "close", "volume"):
            incoming = payload[field]
            if incoming is None:
                continue
            if getattr(existing, field) != incoming:
                setattr(existing, field, incoming)
                changed = True
        if existing.source != source:
            existing.source = source
            changed = True
        if changed:
            updated += 1

    return {"inserted": inserted, "updated": updated}


async def _persist_price_history_for_symbol(
    db: Session,
    orchestrator: Any,
    symbol: str,
    df: Any = None,
) -> Dict[str, int]:
    if df is None:
        df = await orchestrator.get_ohlcv_data(symbol, "1 Y")
    if df is None or getattr(df, "empty", True):
        raise ValueError(f"empty price history for {symbol}")

    parsed_rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        row_date = _normalize_price_row_date(row.get("date"))
        if row_date is None:
            continue
        parsed_rows.append(
            {
                "date": row_date,
                "open": _to_finite_float(row.get("open")),
                "high": _to_finite_float(row.get("high")),
                "low": _to_finite_float(row.get("low")),
                "close": _to_finite_float(row.get("close")),
                "volume": _to_non_negative_int(row.get("volume")),
            }
        )

    if not parsed_rows:
        raise ValueError(f"no valid rows for {symbol}")

    stats = _upsert_price_history(db, symbol, parsed_rows, source="ibkr")
    db.commit()
    return stats


def _upsert_iv_data_for_symbol(
    db: Session,
    symbol: str,
    payload: Dict[str, Any],
    snapshot_date: date_type,
    source: str = "futu",
) -> str:
    normalized_symbol = symbol.upper().strip()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be dict")

    mapped_payload = {
        "iv7": _to_finite_float(payload.get("iv7")),
        "iv30": _to_finite_float(payload.get("iv30")),
        "iv60": _to_finite_float(payload.get("iv60")),
        "iv90": _to_finite_float(payload.get("iv90")),
        "total_oi": _to_int_or_none(payload.get("total_oi")),
        "delta_oi_1d": _to_int_or_none(payload.get("delta_oi_1d")),
        "oi_bucket_0_7": _to_int_or_none(payload.get("oi_bucket_0_7")),
        "oi_bucket_8_30": _to_int_or_none(payload.get("oi_bucket_8_30")),
        "oi_bucket_31_90": _to_int_or_none(payload.get("oi_bucket_31_90")),
        "call_oi_bucket_0_7": _to_int_or_none(payload.get("call_oi_bucket_0_7")),
        "call_oi_bucket_8_30": _to_int_or_none(payload.get("call_oi_bucket_8_30")),
        "call_oi_bucket_31_90": _to_int_or_none(payload.get("call_oi_bucket_31_90")),
        "put_oi_bucket_0_7": _to_int_or_none(payload.get("put_oi_bucket_0_7")),
        "put_oi_bucket_8_30": _to_int_or_none(payload.get("put_oi_bucket_8_30")),
        "put_oi_bucket_31_90": _to_int_or_none(payload.get("put_oi_bucket_31_90")),
        "net_delta_oi_0_7": _to_int_or_none(payload.get("net_delta_oi_0_7")),
        "net_delta_oi_8_30": _to_int_or_none(payload.get("net_delta_oi_8_30")),
        "net_delta_oi_31_90": _to_int_or_none(payload.get("net_delta_oi_31_90")),
        "call_delta_oi_0_7": _to_int_or_none(payload.get("call_delta_oi_0_7")),
        "call_delta_oi_8_30": _to_int_or_none(payload.get("call_delta_oi_8_30")),
        "call_delta_oi_31_90": _to_int_or_none(payload.get("call_delta_oi_31_90")),
        "put_delta_oi_0_7": _to_int_or_none(payload.get("put_delta_oi_0_7")),
        "put_delta_oi_8_30": _to_int_or_none(payload.get("put_delta_oi_8_30")),
        "put_delta_oi_31_90": _to_int_or_none(payload.get("put_delta_oi_31_90")),
    }

    existing = (
        db.query(IVData)
        .filter(
            IVData.symbol == normalized_symbol,
            IVData.date == snapshot_date,
        )
        .first()
    )

    if existing is not None:
        for field, field_value in mapped_payload.items():
            setattr(existing, field, field_value)
        existing.source = source
        existing.created_at = datetime.utcnow()
        return "updated"

    db.add(
        IVData(
            symbol=normalized_symbol,
            date=snapshot_date,
            source=source,
            **mapped_payload,
        )
    )
    return "inserted"


def _compute_sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _compute_return_20d(closes: List[float]) -> Optional[float]:
    if len(closes) < 21:
        return None
    base = closes[-21]
    if base == 0:
        return None
    return (closes[-1] - base) / base


def _compute_sma20_slope(closes: List[float]) -> Optional[float]:
    if len(closes) < 25:
        return None
    sma_today = sum(closes[-20:]) / 20
    sma_5d_ago = sum(closes[-25:-5]) / 20
    return (sma_today - sma_5d_ago) / 5


def _build_symbol_snapshot_from_price_history(
    db: Session,
    symbol: str,
) -> Optional[Dict[str, Any]]:
    normalized_symbol = symbol.upper().strip()
    if not normalized_symbol:
        return None

    rows_desc = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.symbol == normalized_symbol,
            PriceHistory.close.isnot(None),
        )
        .order_by(PriceHistory.date.desc())
        .limit(130)
        .all()
    )
    if not rows_desc:
        return None

    closes = [float(row.close) for row in reversed(rows_desc) if row.close is not None]
    if len(closes) < 50:
        return None

    latest = rows_desc[0]
    latest_price = float(latest.close) if latest.close is not None else None
    sma20 = _compute_sma(closes, 20)
    sma50 = _compute_sma(closes, 50)
    return_20d = _compute_return_20d(closes)
    sma20_slope = _compute_sma20_slope(closes)

    if (
        latest_price is None
        or sma20 is None
        or sma50 is None
        or return_20d is None
        or sma20_slope is None
    ):
        return None

    dist_to_sma20 = (latest_price - sma20) / sma20 if sma20 != 0 else None
    dist_to_sma50 = (latest_price - sma50) / sma50 if sma50 != 0 else None

    return {
        "symbol": normalized_symbol,
        "price": latest_price,
        "sma20": float(sma20),
        "sma50": float(sma50),
        "dist_to_sma20": dist_to_sma20,
        "dist_to_sma50": dist_to_sma50,
        "return_20d": float(return_20d),
        "sma20_slope": float(sma20_slope),
        "date": latest.date.isoformat() if latest.date is not None else None,
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

    def normalize_regime_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized_payload = normalize_json(payload if isinstance(payload, dict) else {})

        def normalize_index_payload(index_payload: Any) -> Optional[Dict[str, Any]]:
            required_index_fields = {"price", "sma20", "sma50", "return_20d", "sma20_slope"}
            if not isinstance(index_payload, dict) or not required_index_fields.issubset(index_payload):
                return None
            return index_payload

        indicators = normalized_payload.get("indicators")
        required_indicator_fields = {
            "price_above_sma20",
            "price_above_sma50",
            "sma20_slope",
            "sma20_slope_positive",
            "sma20_above_sma50",
            "return_20d",
        }
        if not isinstance(indicators, dict) or not required_indicator_fields.issubset(indicators):
            indicators = None

        spy = normalize_index_payload(normalized_payload.get("spy"))
        qqq = normalize_index_payload(normalized_payload.get("qqq"))

        return {
            "status": normalized_payload.get("status") or "UNKNOWN",
            "regime_text": normalized_payload.get("regime_text"),
            "spy": spy,
            "qqq": qqq,
            "vix": normalized_payload.get("vix"),
            "indicators": indicators,
            "error": normalized_payload.get("error"),
        }

    def serialize_snapshot(snapshot: MarketRegimeSnapshot) -> Dict[str, Any]:
        return normalize_regime_payload({
            "status": snapshot.status,
            "regime_text": normalize_json(snapshot.regime_text),
            "spy": normalize_json(snapshot.spy),
            "qqq": None,
            "vix": normalize_json(snapshot.vix),
            "indicators": normalize_json(snapshot.indicators),
            "error": normalize_json(snapshot.error)
        })

    async def fetch_symbol_snapshot(
        orchestrator: Any,
        symbol: str,
        db_session: Session,
    ) -> Optional[Dict[str, Any]]:
        normalized_symbol = symbol.upper().strip()
        if not normalized_symbol:
            return None

        try:
            payload = await asyncio.wait_for(
                orchestrator.get_spy_data(normalized_symbol, sma_periods=[20, 50]),
                timeout=REGIME_SUMMARY_TIMEOUT_SECONDS,
            )
            normalized = normalize_regime_payload(
                {"status": "UNKNOWN", normalized_symbol.lower(): payload}
            ).get(normalized_symbol.lower())
            if isinstance(normalized, dict):
                return normalized
        except Exception as exc:
            logger.warning(f"获取 {normalized_symbol} 快照失败: {exc}")

        fallback_payload = _build_symbol_snapshot_from_price_history(db_session, normalized_symbol)
        normalized_fallback = normalize_regime_payload(
            {"status": "UNKNOWN", normalized_symbol.lower(): fallback_payload}
        ).get(normalized_symbol.lower())
        if isinstance(normalized_fallback, dict):
            logger.info(f"使用本地 PriceHistory 降级构建 {normalized_symbol} 快照")
            return normalized_fallback

        return None

    try:
        today = beijing_today()

        if not refresh:
            existing_snapshot = db.query(MarketRegimeSnapshot).filter(
                MarketRegimeSnapshot.snapshot_date == today
            ).first()
            if existing_snapshot:
                payload = serialize_snapshot(existing_snapshot)
                try:
                    from app.services.orchestrator import get_orchestrator

                    orchestrator = get_orchestrator()
                    broker_status = orchestrator.get_broker_status()
                    if not broker_status.get('ibkr', {}).get('is_connected', False):
                        try:
                            await orchestrator.connect_ibkr()
                        except Exception as exc:
                            logger.warning(f"IBKR 连接失败，无法补充 QQQ 快照: {exc}")
                    payload["qqq"] = await fetch_symbol_snapshot(orchestrator, "QQQ", db)
                except Exception as exc:
                    logger.warning(f"补充 QQQ 快照失败: {exc}")
                return payload
            return {
                "status": "NO_DATA",
                "regime_text": None,
                "spy": None,
                "qqq": None,
                "vix": None,
                "indicators": None,
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

        # 获取 Regime 摘要（加超时，避免请求长时间 pending）
        try:
            result = await asyncio.wait_for(
                orchestrator.get_regime_summary(),
                timeout=REGIME_SUMMARY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Regime 摘要计算超时，返回错误快照",
                extra={"timeout_seconds": REGIME_SUMMARY_TIMEOUT_SECONDS},
            )
            result = {
                "status": "ERROR",
                "regime_text": None,
                "spy": None,
                "qqq": None,
                "vix": None,
                "indicators": None,
                "error": f"Regime calculation timeout ({REGIME_SUMMARY_TIMEOUT_SECONDS}s)",
            }

        # 保底返回，避免抛 500 导致前端 CORS 误报
        if not isinstance(result, dict) or not result.get('status'):
            result = {
                "status": "ERROR",
                "regime_text": None,
                "spy": None,
                "qqq": None,
                "vix": None,
                "indicators": None,
                "error": "Regime data unavailable"
            }

        normalized_result = normalize_regime_payload(result)
        if normalized_result.get("qqq") is None:
            normalized_result["qqq"] = await fetch_symbol_snapshot(orchestrator, "QQQ", db)

        # 写入/更新当日快照
        snapshot = db.query(MarketRegimeSnapshot).filter(
            MarketRegimeSnapshot.snapshot_date == today
        ).first()

        payload = normalized_result

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
                status=payload["status"],
                regime_text=payload["regime_text"],
                spy=payload["spy"],
                vix=payload["vix"],
                indicators=payload["indicators"],
                error=payload["error"],
            )
            db.add(snapshot)

        db.commit()

        # ---- Hysteresis 滞后保护 ----
        try:
            from app.services.calculators.regime_gate import RegimeGateCalculator

            # 读取最近一条历史记录
            latest_state = db.query(RegimeStateHistory).order_by(
                RegimeStateHistory.record_date.desc()
            ).first()

            if latest_state and latest_state.record_date == today:
                # 当天已有记录，直接使用
                hysteresis_info = {
                    "raw_status": latest_state.raw_status,
                    "effective_status": latest_state.effective_status,
                    "regime_locked": latest_state.days_since_switch < RegimeGateCalculator.COOLDOWN_AFTER_SWITCH,
                    "pending_switch_to": latest_state.pending_switch_to,
                    "confirmation_progress": f"{latest_state.confirmation_progress}/{RegimeGateCalculator.CONFIRMATION_DAYS}",
                }
            else:
                prev_effective = latest_state.effective_status if latest_state else 'B'
                prev_progress = latest_state.confirmation_progress if latest_state else 0
                prev_days_since = (latest_state.days_since_switch + 1) if latest_state else 999
                prev_pending = latest_state.pending_switch_to if latest_state else None

                # 如果 pending 方向变了，重置进度
                raw_status = normalized_result.get("status", "UNKNOWN")
                if raw_status in ('A', 'B', 'C') and prev_pending and raw_status != prev_pending:
                    prev_progress = 0

                calc = RegimeGateCalculator(ibkr=orchestrator._ibkr)
                hyst = calc.calculate_regime_with_hysteresis(
                    previous_effective_status=prev_effective,
                    confirmation_progress=prev_progress,
                    days_since_last_switch=prev_days_since,
                )

                new_days_since = 0 if hyst['switched'] else prev_days_since

                state_record = RegimeStateHistory(
                    record_date=today,
                    raw_status=hyst['raw_status'],
                    effective_status=hyst['effective_status'],
                    consecutive_days=1,
                    days_since_switch=new_days_since,
                    pending_switch_to=hyst['pending_switch_to'],
                    confirmation_progress=hyst['confirmation_progress'],
                )
                db.add(state_record)
                db.commit()

                hysteresis_info = {
                    "raw_status": hyst['raw_status'],
                    "effective_status": hyst['effective_status'],
                    "regime_locked": hyst['regime_locked'],
                    "pending_switch_to": hyst['pending_switch_to'],
                    "confirmation_progress": f"{hyst['confirmation_progress']}/{RegimeGateCalculator.CONFIRMATION_DAYS}",
                }

            normalized_result["hysteresis"] = hysteresis_info
        except Exception as hyst_exc:
            logger.warning(f"Hysteresis 处理失败，不影响主流程: {hyst_exc}")

        return normalized_result

    except Exception as e:
        logger.error(f"获取 Regime 失败: {e}")
        # 不抛异常，返回错误对象，确保前端拿到 CORS headers
        return {
            "status": "ERROR",
            "regime_text": None,
            "spy": None,
            "qqq": None,
            "vix": None,
            "indicators": None,
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


@router.post("/price-freshness", response_model=PriceFreshnessResponse)
async def check_price_freshness(
    request: PriceFreshnessRequest,
    db: Session = Depends(get_db),
):
    """
    检查给定 symbol 的价格数据是否满足当前“北京时间 08:00 日切窗口”。

    判定规则:
    - 若最新 PriceHistory.date >= boundary_date，则视为 fresh
    - 否则若最新 PriceHistory.created_at >= boundary_utc，则视为 fresh
    - 其余视为 stale
    """
    try:
        normalized_symbols = _normalize_symbol_list(request.symbols)
        boundary = _get_beijing_sync_boundary()
        boundary_utc: datetime = boundary["boundary_utc"]
        boundary_date: date_type = boundary["boundary_date"]
        sync_date: str = boundary["sync_date"]

        if not normalized_symbols:
            return PriceFreshnessResponse(stale=[], fresh=[], sync_date=sync_date)

        latest_rows = (
            db.query(
                PriceHistory.symbol,
                func.max(PriceHistory.date).label("latest_date"),
                func.max(PriceHistory.created_at).label("latest_created_at"),
            )
            .filter(
                PriceHistory.symbol.in_(normalized_symbols),
                PriceHistory.source == "ibkr",
            )
            .group_by(PriceHistory.symbol)
            .all()
        )

        fresh_symbol_set = set()
        for row in latest_rows:
            symbol_name = str(row.symbol or "").strip().upper()
            if not symbol_name:
                continue
            latest_date = _normalize_price_row_date(row.latest_date)
            latest_created_at = _normalize_datetime(row.latest_created_at)

            has_fresh_by_date = latest_date is not None and latest_date >= boundary_date
            has_fresh_by_time = (
                latest_created_at is not None and latest_created_at >= boundary_utc
            )
            if has_fresh_by_date or has_fresh_by_time:
                fresh_symbol_set.add(symbol_name)

        fresh_symbols = [symbol for symbol in normalized_symbols if symbol in fresh_symbol_set]
        stale_symbols = [symbol for symbol in normalized_symbols if symbol not in fresh_symbol_set]

        return PriceFreshnessResponse(
            stale=stale_symbols,
            fresh=fresh_symbols,
            sync_date=sync_date,
        )

    except Exception as e:
        logger.error(f"价格新鲜度检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync", response_model=SyncResponse)
async def sync_market_data(
    request: SyncRequest,
    db: Session = Depends(get_db),
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
        
        normalized_symbols = _normalize_symbol_list(request.symbols)
        expanded_price_symbols = (
            _expand_with_related_etfs(db, normalized_symbols)
            if request.sync_type in ['price', 'all'] and normalized_symbols
            else normalized_symbols
        )
        if expanded_price_symbols != normalized_symbols:
            logger.info(
                "market_sync_symbols_expanded requested=%s expanded=%s",
                normalized_symbols,
                expanded_price_symbols,
            )

        results = {
            'status': 'success',
            'synced': [],
            'failed': [],
            'total': len(expanded_price_symbols if request.sync_type in ['price', 'all'] else normalized_symbols),
            'success_count': 0
        }
        
        # 同步价格数据
        if request.sync_type in ['price', 'all'] and expanded_price_symbols:
            broker_status = orchestrator.get_broker_status()
            if not broker_status.get('ibkr', {}).get('is_connected', False):
                await orchestrator.connect_ibkr()
            
            price_result = await orchestrator.sync_price_data(expanded_price_symbols)
            raw_synced = _normalize_symbol_list(price_result.get('synced', []))
            raw_failed = _normalize_symbol_list(price_result.get('failed', []))
            skipped_fresh = set(_normalize_symbol_list(price_result.get('skipped_fresh', [])))
            raw_frames = (
                price_result.get('price_frames', {})
                if isinstance(price_result.get('price_frames', {}), dict)
                else {}
            )
            results['failed'].extend(raw_failed)

            for symbol in raw_synced:
                if symbol in raw_failed:
                    continue
                if symbol in skipped_fresh and raw_frames.get(symbol) is None:
                    # 会话去重命中且无新增数据时，复用已有 DB 结果，不重复拉取。
                    results['synced'].append(symbol)
                    continue
                try:
                    await _persist_price_history_for_symbol(
                        db,
                        orchestrator,
                        symbol,
                        df=raw_frames.get(symbol),
                    )
                    results['synced'].append(symbol)
                except Exception as persist_error:
                    db.rollback()
                    logger.warning(
                        f"market_sync_persist_failed symbol={symbol} error={persist_error}",
                    )
                    if symbol not in results['failed']:
                        results['failed'].append(symbol)
        
        # 同步 IV 数据
        if request.sync_type in ['iv', 'all'] and normalized_symbols:
            broker_status = orchestrator.get_broker_status()
            if not broker_status.get('futu', {}).get('is_connected', False):
                await orchestrator.connect_futu()
            
            iv_result = await orchestrator.sync_iv_data(normalized_symbols)
            iv_synced = _normalize_symbol_list(iv_result.get('synced', []))
            iv_failed = _normalize_symbol_list(iv_result.get('failed', []))
            iv_payload = iv_result.get('data', {}) if isinstance(iv_result.get('data', {}), dict) else {}

            results['failed'].extend(iv_failed)

            iv_success_candidates: List[str] = []
            snapshot_date = beijing_today()
            for symbol in iv_synced:
                payload = iv_payload.get(symbol)
                if not isinstance(payload, dict):
                    if symbol not in results['failed']:
                        results['failed'].append(symbol)
                    logger.warning(
                        "market_sync_iv_payload_missing symbol=%s",
                        symbol,
                    )
                    continue

                try:
                    _upsert_iv_data_for_symbol(
                        db=db,
                        symbol=symbol,
                        payload=payload,
                        snapshot_date=snapshot_date,
                        source="futu",
                    )
                    iv_success_candidates.append(symbol)
                except Exception as persist_error:
                    db.rollback()
                    logger.warning(
                        "market_sync_iv_persist_failed symbol=%s error=%s",
                        symbol,
                        persist_error,
                    )
                    if symbol not in results['failed']:
                        results['failed'].append(symbol)

            if iv_success_candidates:
                try:
                    db.commit()
                    for symbol in iv_success_candidates:
                        if symbol not in results['synced']:
                            results['synced'].append(symbol)
                except Exception as commit_error:
                    db.rollback()
                    logger.warning(
                        "market_sync_iv_commit_failed symbols=%s error=%s",
                        iv_success_candidates,
                        commit_error,
                    )
                    for symbol in iv_success_candidates:
                        if symbol not in results['failed']:
                            results['failed'].append(symbol)
        
        # 去重，保持顺序
        results['synced'] = _normalize_symbol_list(results['synced'])
        results['failed'] = _normalize_symbol_list(results['failed'])
        
        results['success_count'] = len(results['synced'])
        if results['failed']:
            results['status'] = 'partial_success' if results['synced'] else 'failed'
        
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


@router.get("/symbol/{symbol}")
async def get_market_symbol_data(symbol: str, db: Session = Depends(get_db)):
    """
    获取任意指数/ETF 数据（如 SPY、QQQ）
    """
    try:
        normalized_symbol = symbol.upper().strip()
        if not normalized_symbol:
            raise HTTPException(status_code=400, detail="symbol is required")

        # 优先读取本地 PriceHistory 快照，避免页面访问触发 IBKR 自动连接。
        local_snapshot = _build_symbol_snapshot_from_price_history(db, normalized_symbol)
        if isinstance(local_snapshot, dict):
            return local_snapshot

        from app.services.orchestrator import get_orchestrator

        orchestrator = get_orchestrator()
        broker_status = orchestrator.get_broker_status()
        if not broker_status.get('ibkr', {}).get('is_connected', False):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"{normalized_symbol} local snapshot unavailable and IBKR is not connected"
                ),
            )

        symbol_data = await orchestrator.get_spy_data(normalized_symbol)
        if symbol_data is None:
            raise HTTPException(status_code=503, detail=f"Unable to fetch {normalized_symbol} data")

        return symbol_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 {symbol} 数据失败: {e}")
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
            'timestamp': utc_now_iso()
        }
        
    except Exception as e:
        logger.error(f"获取 VIX 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
