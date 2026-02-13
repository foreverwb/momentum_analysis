"""
ETF API 端点
从数据库读取 ETF 数据（已移除 mock 数据）
集成 IBKR/Futu API 获取实时数据并计算评分
"""

import asyncio
import json
import logging
import math
import re
import threading
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from pydantic import BaseModel

from app.models import (
    get_db, ETF, ETFHolding, VALID_SECTOR_SYMBOLS, Stock, ImportedData,
    PriceHistory, IVData, ScoreSnapshot
)
from app.core.broker_config import load_broker_config
from app.services.parsers import normalize_heat_type

router = APIRouter()
logger = logging.getLogger(__name__)

COVERAGE_RANGE_PRIORITY = [
    'top10', 'top15', 'top20', 'top25', 'top30',
    'weight60', 'weight65', 'weight70', 'weight75', 'weight80', 'weight85',
    'all',
]
ETF_SCORE_WEIGHTS = {
    'rel_mom': 0.45,
    'trend_quality': 0.25,
    'breadth': 0.20,
    'options_confirm': 0.10,
}
ETF_COMPLETENESS_WEIGHTS = {
    'ibkr_price': 20,
    'ibkr_relmom': 25,
    'ibkr_trend': 15,
    'futu_iv': 10,
    'finviz_breadth': 20,
    'mc_options': 10,
}
HOLDINGS_PROGRESS_TTL_SECONDS = 30 * 60
_refresh_config = load_broker_config().refresh
ETF_REFRESH_COOLDOWN_MINUTES = _refresh_config.etf_cooldown_minutes
ETF_REFRESH_COOLDOWN = timedelta(minutes=ETF_REFRESH_COOLDOWN_MINUTES)
HOLDINGS_REFRESH_COOLDOWN_MINUTES = _refresh_config.holdings_cooldown_minutes
HOLDINGS_REFRESH_COOLDOWN = timedelta(minutes=HOLDINGS_REFRESH_COOLDOWN_MINUTES)
_HOLDINGS_REFRESH_PROGRESS: Dict[str, Dict[str, Any]] = {}
_HOLDINGS_REFRESH_PROGRESS_LOCK = threading.Lock()
_SHARE_CLASS_ALIAS_PATTERN = re.compile(r"^([A-Z][A-Z0-9]{0,5})[.-]([A-Z])$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_progress_token(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if len(token) < 8 or len(token) > 128:
        return None
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(ch not in allowed_chars for ch in token):
        return None
    return token


def _cleanup_holdings_refresh_progress(now: Optional[datetime] = None) -> None:
    now_dt = now or datetime.now(timezone.utc)
    expired_tokens: List[str] = []
    for token, payload in _HOLDINGS_REFRESH_PROGRESS.items():
        updated_at_raw = payload.get("updated_at")
        updated_at_dt: Optional[datetime] = None
        if isinstance(updated_at_raw, str):
            try:
                updated_at_dt = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
            except ValueError:
                updated_at_dt = None
        if updated_at_dt is None:
            updated_at_dt = now_dt
        if (now_dt - updated_at_dt).total_seconds() > HOLDINGS_PROGRESS_TTL_SECONDS:
            expired_tokens.append(token)
    for token in expired_tokens:
        _HOLDINGS_REFRESH_PROGRESS.pop(token, None)


def _set_holdings_refresh_progress(token: str, payload: Dict[str, Any]) -> None:
    with _HOLDINGS_REFRESH_PROGRESS_LOCK:
        _cleanup_holdings_refresh_progress()
        payload_copy = dict(payload)
        payload_copy["updated_at"] = _utc_now_iso()
        _HOLDINGS_REFRESH_PROGRESS[token] = payload_copy


def _patch_holdings_refresh_progress(token: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _HOLDINGS_REFRESH_PROGRESS_LOCK:
        _cleanup_holdings_refresh_progress()
        current = _HOLDINGS_REFRESH_PROGRESS.get(token)
        if not current:
            return None
        next_payload = dict(current)
        next_payload.update(patch)
        next_payload["updated_at"] = _utc_now_iso()
        _HOLDINGS_REFRESH_PROGRESS[token] = next_payload
        return dict(next_payload)


def _get_holdings_refresh_progress(token: str) -> Optional[Dict[str, Any]]:
    with _HOLDINGS_REFRESH_PROGRESS_LOCK:
        _cleanup_holdings_refresh_progress()
        payload = _HOLDINGS_REFRESH_PROGRESS.get(token)
        return dict(payload) if payload else None


def _coerce_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return None
    else:
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _canonical_symbol_key(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return ""
    matched = _SHARE_CLASS_ALIAS_PATTERN.match(normalized)
    if not matched:
        return normalized
    return f"{matched.group(1)}.{matched.group(2)}"


def _symbol_aliases(symbol: Any) -> List[str]:
    canonical = _canonical_symbol_key(symbol)
    if not canonical:
        return []
    aliases = {canonical}
    if "." in canonical:
        aliases.add(canonical.replace(".", "-", 1))
    return sorted(aliases)


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    dt = _coerce_datetime(value)
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _beijing_import_boundary(now_utc: Optional[datetime] = None) -> Dict[str, Any]:
    now_dt = _coerce_datetime(now_utc) or datetime.utcnow()
    now_beijing = now_dt + timedelta(hours=8)
    boundary_beijing = now_beijing.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_beijing < boundary_beijing:
        boundary_beijing -= timedelta(days=1)
    return {
        "boundary_utc": boundary_beijing - timedelta(hours=8),
        "boundary_date": boundary_beijing.date(),
        "boundary_beijing": boundary_beijing,
    }


def _is_fresh_for_boundary(
    record_date: Any,
    created_at: Any,
    *,
    boundary_date: date,
    boundary_utc: datetime,
) -> bool:
    coerced_date = _coerce_date(record_date)
    coerced_created_at = _coerce_datetime(created_at)
    has_fresh_by_date = coerced_date is not None and coerced_date >= boundary_date
    has_fresh_by_time = coerced_created_at is not None and coerced_created_at >= boundary_utc
    return has_fresh_by_date or has_fresh_by_time


def _pick_record_updated_at(record_date: Any, created_at: Any) -> Optional[datetime]:
    coerced_created_at = _coerce_datetime(created_at)
    if coerced_created_at is not None:
        return coerced_created_at
    coerced_date = _coerce_date(record_date)
    if coerced_date is None:
        return None
    return datetime.combine(coerced_date, datetime.min.time())


def _build_etf_source_updated_at(
    symbol: str,
    db: Optional[Session],
) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "finviz": None,
        "marketchameleon": None,
        "ibkr": None,
        "futu": None,
    }
    if db is None:
        return result

    query_symbols = _symbol_aliases(symbol)
    if not query_symbols:
        return result

    boundary = _beijing_import_boundary()
    boundary_utc = boundary["boundary_utc"]
    boundary_date = boundary["boundary_date"]
    latest_by_source: Dict[str, datetime] = {}

    try:
        imported_rows = db.query(
            ImportedData.source,
            ImportedData.date,
            ImportedData.created_at,
        ).filter(
            ImportedData.symbol.in_(query_symbols),
            ImportedData.source.in_(["finviz", "marketchameleon"]),
        ).all()

        for row in imported_rows:
            source_name = str(row.source or "").strip().lower()
            if source_name not in result:
                continue
            if not _is_fresh_for_boundary(
                row.date,
                row.created_at,
                boundary_date=boundary_date,
                boundary_utc=boundary_utc,
            ):
                continue
            candidate_dt = _pick_record_updated_at(row.date, row.created_at)
            if candidate_dt is None:
                continue
            previous_dt = latest_by_source.get(source_name)
            if previous_dt is None or candidate_dt > previous_dt:
                latest_by_source[source_name] = candidate_dt
    except Exception as exc:
        logger.warning("ETF import source status query failed for %s: %s", symbol.upper(), exc)

    try:
        price_rows = db.query(
            PriceHistory.date,
            PriceHistory.created_at,
        ).filter(
            PriceHistory.symbol.in_(query_symbols),
            PriceHistory.source == "ibkr",
        ).all()

        for row in price_rows:
            if not _is_fresh_for_boundary(
                row.date,
                row.created_at,
                boundary_date=boundary_date,
                boundary_utc=boundary_utc,
            ):
                continue
            candidate_dt = _pick_record_updated_at(row.date, row.created_at)
            if candidate_dt is None:
                continue
            previous_dt = latest_by_source.get("ibkr")
            if previous_dt is None or candidate_dt > previous_dt:
                latest_by_source["ibkr"] = candidate_dt
    except Exception as exc:
        logger.warning("ETF IBKR source status query failed for %s: %s", symbol.upper(), exc)

    try:
        iv_rows = db.query(
            IVData.date,
            IVData.created_at,
        ).filter(
            IVData.symbol.in_(query_symbols),
            IVData.source == "futu",
        ).all()

        for row in iv_rows:
            if not _is_fresh_for_boundary(
                row.date,
                row.created_at,
                boundary_date=boundary_date,
                boundary_utc=boundary_utc,
            ):
                continue
            candidate_dt = _pick_record_updated_at(row.date, row.created_at)
            if candidate_dt is None:
                continue
            previous_dt = latest_by_source.get("futu")
            if previous_dt is None or candidate_dt > previous_dt:
                latest_by_source["futu"] = candidate_dt
    except Exception as exc:
        logger.warning("ETF Futu source status query failed for %s: %s", symbol.upper(), exc)

    for source_name, updated_at in latest_by_source.items():
        result[source_name] = _iso_utc(updated_at)
    return result


def _format_beijing_time(value: Optional[datetime]) -> Optional[str]:
    dt = _coerce_datetime(value)
    if dt is None:
        return None
    return (dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def _build_refresh_gate_state(
    latest_at: Optional[datetime],
    now_utc: Optional[datetime] = None,
    cooldown: Optional[timedelta] = None,
) -> Dict[str, Any]:
    cooldown_window = cooldown or ETF_REFRESH_COOLDOWN
    now_dt = _coerce_datetime(now_utc) or datetime.utcnow()
    latest_dt = _coerce_datetime(latest_at)
    if latest_dt is None:
        return {
            "latest_at": None,
            "is_recent": False,
            "age_seconds": None,
            "remaining_seconds": None,
            "next_refresh_at": None,
        }

    elapsed_seconds = max(0.0, (now_dt - latest_dt).total_seconds())
    remaining_seconds = max(0.0, cooldown_window.total_seconds() - elapsed_seconds)
    is_recent = remaining_seconds > 0
    next_refresh_at = latest_dt + cooldown_window
    return {
        "latest_at": latest_dt,
        "is_recent": is_recent,
        "age_seconds": int(round(elapsed_seconds)),
        "remaining_seconds": int(round(remaining_seconds)) if is_recent else 0,
        "next_refresh_at": next_refresh_at,
    }


def _pick_next_refresh_at(states: List[Dict[str, Any]]) -> Optional[datetime]:
    candidates: List[datetime] = []
    for state in states:
        if not state.get("is_recent"):
            continue
        candidate = _coerce_datetime(state.get("next_refresh_at"))
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates)


def _build_refresh_gate_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    latest_at = _coerce_datetime(state.get("latest_at"))
    next_at = _coerce_datetime(state.get("next_refresh_at"))
    return {
        "latest_at": _iso_utc(latest_at),
        "is_recent": bool(state.get("is_recent", False)),
        "age_seconds": state.get("age_seconds"),
        "remaining_seconds": state.get("remaining_seconds"),
        "next_refresh_at": _iso_utc(next_at),
    }


def _filter_holdings_by_coverage(
    holdings: List[ETFHolding],
    coverage_type: str,
    coverage_value: int,
) -> List[ETFHolding]:
    coverage_kind = str(coverage_type or "").strip().lower()
    if coverage_kind == "all":
        return holdings
    if coverage_kind == "top":
        return holdings[:coverage_value]
    if coverage_kind == "weight":
        selected: List[ETFHolding] = []
        accumulated_weight = 0.0
        for holding in holdings:
            selected.append(holding)
            accumulated_weight += float(holding.weight or 0.0)
            if accumulated_weight >= coverage_value:
                break
        return selected
    raise HTTPException(status_code=400, detail=f"Invalid coverage_type: {coverage_type}")


def _format_coverage_label(coverage_type: str, coverage_value: int) -> str:
    coverage_kind = str(coverage_type or "").strip().lower()
    if coverage_kind == "all":
        return "all"
    return f"{coverage_kind}{coverage_value}"


class HoldingsCoverageRequest(BaseModel):
    coverage_type: str
    coverage_value: int
    sources: Optional[List[str]] = None
    concurrent: Optional[bool] = None
    progress_token: Optional[str] = None
    related_etf_symbols: Optional[List[str]] = None


def _default_etf_score_result() -> Dict[str, Dict[str, Any]]:
    return {
        'rel_mom': {'score': 0.0, 'data': None},
        'trend_quality': {'score': 0.0, 'data': None},
        'breadth': {'score': 50.0, 'data': None},
        'options_confirm': {'score': 50.0, 'data': None},
    }


def _normalize_etf_dimension(default: Dict[str, Any], payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return dict(default)

    normalized = {
        "score": float(default.get("score", 0.0) or 0.0),
        "data": default.get("data"),
    }
    score_value = payload.get("score")
    if isinstance(score_value, (int, float)):
        normalized["score"] = float(score_value)
    if payload.get("data") is not None:
        normalized["data"] = payload.get("data")
    return normalized


def _load_etf_score_result(payload: Any) -> Dict[str, Dict[str, Any]]:
    score_result = _default_etf_score_result()
    if not isinstance(payload, dict):
        return score_result

    for key in score_result:
        score_result[key] = _normalize_etf_dimension(score_result[key], payload.get(key))
    return score_result


def _get_latest_import_payload(
    db: Session,
    symbol: str,
    source: str,
) -> Optional[Dict[str, Any]]:
    query_symbols = _symbol_aliases(symbol)
    if not query_symbols:
        return None

    record = db.query(ImportedData).filter(
        ImportedData.symbol.in_(query_symbols),
        ImportedData.source == source,
    ).order_by(
        ImportedData.date.desc(),
        ImportedData.created_at.desc(),
        ImportedData.id.desc(),
    ).first()

    if record and isinstance(record.data, dict):
        return record.data
    return None


def _get_latest_etf_holdings(db: Session, etf_symbol: str) -> List[ETFHolding]:
    latest_date = db.query(func.max(ETFHolding.data_date)).filter(
        ETFHolding.etf_symbol == etf_symbol.upper()
    ).scalar()
    if not latest_date:
        return []

    return db.query(ETFHolding).filter(
        ETFHolding.etf_symbol == etf_symbol.upper(),
        ETFHolding.data_date == latest_date,
    ).order_by(ETFHolding.weight.desc()).all()


def _load_etf_holdings_finviz_payloads(db: Session, etf_symbol: str) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for holding in _get_latest_etf_holdings(db, etf_symbol):
        finviz_payload = _get_latest_import_payload(db, str(holding.ticker or ""), "finviz")
        if isinstance(finviz_payload, dict):
            payloads.append(finviz_payload)
    return payloads


def _compute_snapshot_deltas(
    db: Session,
    symbol: str,
    symbol_type: str,
) -> Dict[str, Optional[float]]:
    snapshots = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == symbol.upper(),
        ScoreSnapshot.symbol_type == symbol_type,
    ).order_by(ScoreSnapshot.date.desc(), ScoreSnapshot.id.desc()).limit(6).all()

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


def _recalculate_etf_score_from_db(
    etf: ETF,
    db: Session,
    *,
    base_breakdown: Optional[Dict[str, Dict[str, Any]]] = None,
    base_data_sources: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    from app.services.calculators.etf_score import ETFScoreCalculator

    latest_snapshot = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == etf.symbol,
        ScoreSnapshot.symbol_type == 'etf',
    ).order_by(ScoreSnapshot.date.desc(), ScoreSnapshot.id.desc()).first()

    seed_payload: Any = base_breakdown
    if seed_payload is None and latest_snapshot and isinstance(latest_snapshot.score_breakdown, dict):
        seed_payload = latest_snapshot.score_breakdown

    score_result = _load_etf_score_result(seed_payload)
    calculator = ETFScoreCalculator()

    latest_ibkr_created_at = _coerce_datetime(
        db.query(func.max(PriceHistory.created_at)).filter(
            PriceHistory.symbol == etf.symbol,
            PriceHistory.source == "ibkr",
        ).scalar()
    )
    latest_futu_created_at = _coerce_datetime(
        db.query(func.max(IVData.created_at)).filter(
            IVData.symbol == etf.symbol,
            IVData.source == "futu",
        ).scalar()
    )

    data_sources = {
        'ibkr_price': latest_ibkr_created_at is not None,
        'ibkr_relmom': score_result['rel_mom'].get('data') is not None,
        'ibkr_trend': score_result['trend_quality'].get('data') is not None,
        'futu_iv': latest_futu_created_at is not None or score_result['options_confirm'].get('data') is not None,
        'finviz_breadth': score_result['breadth'].get('data') is not None,
        'mc_options': False,
    }
    if isinstance(base_data_sources, dict):
        for key in data_sources:
            if key in base_data_sources:
                data_sources[key] = bool(base_data_sources[key])

    holdings = _get_latest_etf_holdings(db, etf.symbol)
    if holdings:
        etf.holdings_count = len(holdings)

    finviz_payloads = _load_etf_holdings_finviz_payloads(db, etf.symbol)
    if finviz_payloads:
        breadth_result = calculator.calculate_breadth_score(etf.symbol, finviz_payloads)
        if breadth_result.get('data') is not None:
            score_result['breadth'] = _normalize_etf_dimension(
                score_result['breadth'],
                breadth_result,
            )
            data_sources['finviz_breadth'] = True

    thresholds_payload = calculator.check_thresholds(
        rel_mom_data=score_result['rel_mom'],
        trend_data=score_result['trend_quality'],
        breadth_data=score_result['breadth'],
    )
    thresholds_pass = bool(thresholds_payload.get('all_pass'))
    threshold_details = thresholds_payload.get('details') or {}

    total_score = round(
        sum(
            ETF_SCORE_WEIGHTS[key] * float((score_result.get(key) or {}).get('score') or 0.0)
            for key in ETF_SCORE_WEIGHTS
        ),
        2,
    )
    completeness = sum(
        ETF_COMPLETENESS_WEIGHTS[key]
        for key, is_ready in data_sources.items()
        if is_ready
    )

    should_persist = base_breakdown is not None or latest_snapshot is not None
    normalized_sources = {key: bool(value) for key, value in data_sources.items()}

    if not should_persist:
        return {
            "score": etf.score,
            "rank": etf.rank,
            "completeness": etf.completeness,
            "thresholds_pass": latest_snapshot.thresholds_pass if latest_snapshot else None,
            "thresholds": threshold_details,
            "breakdown": score_result,
            "data_sources": normalized_sources,
        }

    etf.score = total_score
    etf.completeness = completeness
    etf.updated_at = datetime.utcnow()

    today = date.today()
    existing_snapshot = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == etf.symbol,
        ScoreSnapshot.symbol_type == 'etf',
        ScoreSnapshot.date == today,
    ).first()

    if existing_snapshot:
        existing_snapshot.total_score = total_score
        existing_snapshot.score_breakdown = score_result
        existing_snapshot.thresholds_pass = thresholds_pass
    else:
        db.add(ScoreSnapshot(
            symbol=etf.symbol,
            symbol_type='etf',
            date=today,
            total_score=total_score,
            score_breakdown=score_result,
            thresholds_pass=thresholds_pass,
        ))

    db.flush()
    etf.delta = _compute_snapshot_deltas(db, etf.symbol, 'etf')

    etfs_of_same_type = db.query(ETF).filter(
        ETF.type == etf.type,
        ETF.score > 0,
    ).order_by(ETF.score.desc(), ETF.symbol.asc()).all()
    for idx, peer_etf in enumerate(etfs_of_same_type, 1):
        peer_etf.rank = idx

    db.commit()
    db.refresh(etf)

    return {
        "score": etf.score,
        "rank": etf.rank,
        "completeness": etf.completeness,
        "thresholds_pass": thresholds_pass,
        "thresholds": threshold_details,
        "breakdown": score_result,
        "data_sources": normalized_sources,
    }


def format_etf_response(etf: ETF, include_holdings: bool = False, db: Session = None) -> dict:
    """格式化 ETF 响应数据"""

    # coverageRanges = 持久化导入范围 + 持仓动态推导范围（去重并按优先级排序）
    coverage_ranges: List[str] = []
    coverage_seen = set()

    def add_coverage(value: Optional[str]):
        if not value:
            return
        normalized = str(value).strip().lower()
        if normalized in COVERAGE_RANGE_PRIORITY and normalized not in coverage_seen:
            coverage_seen.add(normalized)
            coverage_ranges.append(normalized)

    persisted_ranges = getattr(etf, 'coverage_ranges', None)
    if isinstance(persisted_ranges, list):
        for item in persisted_ranges:
            add_coverage(item if isinstance(item, str) else None)
    elif isinstance(persisted_ranges, str):
        parsed_ranges: List[str] = []
        try:
            parsed = json.loads(persisted_ranges)
            if isinstance(parsed, list):
                parsed_ranges = [str(item) for item in parsed if isinstance(item, str)]
        except Exception:
            parsed_ranges = []
        for item in parsed_ranges:
            add_coverage(item)

    # 从持仓数据动态计算 coverageRanges
    if etf.holdings:
        # 获取最新日期的持仓
        latest_date = max(h.data_date for h in etf.holdings) if etf.holdings else None
        if latest_date:
            holdings_for_date = [h for h in etf.holdings if h.data_date == latest_date]

            # 检查是否有足够的持仓数据来确定覆盖范围
            if holdings_for_date:
                add_coverage('all')
                total_holdings = len(holdings_for_date)
                total_weight = sum(h.weight for h in holdings_for_date)

                # 检查可能的 Top 覆盖范围
                for top_n in [10, 15, 20, 30]:
                    if total_holdings >= top_n:
                        add_coverage(f'top{top_n}')

                # 检查可能的 Weight 覆盖范围
                for weight_pct in [60, 65, 70, 75, 80, 85]:
                    accumulated_weight = 0
                    for h in sorted(holdings_for_date, key=lambda x: x.weight, reverse=True):
                        accumulated_weight += h.weight
                        if accumulated_weight >= weight_pct:
                            add_coverage(f'weight{weight_pct}')
                            break

    # 按固定优先级输出，保证前端 tab 顺序稳定
    ordered_coverage_ranges = [item for item in COVERAGE_RANGE_PRIORITY if item in coverage_seen]

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
        "coverageRanges": ordered_coverage_ranges,
        "sourceUpdatedAt": _build_etf_source_updated_at(etf.symbol, db),
        # 兼容旧字段(lastUpdated)并提供统一字段(updatedAt)
        "updatedAt": etf.updated_at.isoformat() if etf.updated_at else None,
        "lastUpdated": etf.updated_at.isoformat() if etf.updated_at else None,
    }

    if etf.type == "industry" and etf.parent_sector:
        result["parentSector"] = etf.parent_sector

    if include_holdings and etf.holdings:
        # 只返回最新日期的持仓，并附带最新评分（若有）
        latest_date = max(h.data_date for h in etf.holdings) if etf.holdings else None
        if latest_date:
            holdings_today = [h for h in etf.holdings if h.data_date == latest_date]

            score_map = {}
            updated_map = {}
            stock_updated_dt_map: Dict[str, Optional[datetime]] = {}
            stock_metrics_map: Dict[str, Dict[str, Any]] = {}
            stock_price_map: Dict[str, Optional[float]] = {}
            source_map: Dict[str, Dict[str, bool]] = {}
            import_updated_dt_map: Dict[str, datetime] = {}
            if db:
                try:
                    tickers = list(dict.fromkeys(str(h.ticker).upper() for h in holdings_today if h.ticker))
                    if tickers:
                        ticker_key_map = {
                            ticker: _canonical_symbol_key(ticker) for ticker in tickers
                        }
                        canonical_to_ticker: Dict[str, str] = {}
                        for ticker, canonical in ticker_key_map.items():
                            if canonical and canonical not in canonical_to_ticker:
                                canonical_to_ticker[canonical] = ticker
                        ticker_query_symbols = sorted(
                            {
                                alias
                                for ticker in tickers
                                for alias in _symbol_aliases(ticker)
                            }
                        )

                        stocks = db.query(Stock).filter(Stock.symbol.in_(ticker_query_symbols)).all()
                        for stock in stocks:
                            stock_symbol = str(stock.symbol or "").upper()
                            resolved_ticker = canonical_to_ticker.get(
                                _canonical_symbol_key(stock_symbol),
                                stock_symbol,
                            )
                            if not resolved_ticker:
                                continue
                            score_map[resolved_ticker] = stock.score_total
                            stock_updated_dt_map[resolved_ticker] = _coerce_datetime(stock.updated_at)
                            stock_metrics_map[resolved_ticker] = stock.metrics if isinstance(stock.metrics, dict) else {}
                            stock_price_value = None
                            try:
                                parsed_price = float(stock.price) if stock.price is not None else None
                                if parsed_price is not None and math.isfinite(parsed_price):
                                    stock_price_value = parsed_price
                            except (TypeError, ValueError):
                                stock_price_value = None
                            stock_price_map[resolved_ticker] = stock_price_value

                        # 北京时间 08:00 为日切边界
                        now_utc = datetime.utcnow()
                        now_beijing = now_utc + timedelta(hours=8)
                        boundary_beijing = now_beijing.replace(hour=8, minute=0, second=0, microsecond=0)
                        if now_beijing < boundary_beijing:
                            boundary_beijing -= timedelta(days=1)
                        boundary_utc = boundary_beijing - timedelta(hours=8)
                        boundary_date = boundary_beijing.date()

                        source_map = {
                            ticker: {
                                "finviz": False,
                                "market_chameleon": False,
                                "marketchameleon": False,
                                "ibkr": False,
                                "futu": False,
                            }
                            for ticker in tickers
                        }

                        try:
                            imported_rows = db.query(
                                ImportedData.symbol,
                                ImportedData.source,
                                ImportedData.date,
                                ImportedData.created_at,
                            ).filter(
                                ImportedData.symbol.in_(ticker_query_symbols),
                                ImportedData.source.in_(["finviz", "marketchameleon"]),
                            ).all()

                            for row in imported_rows:
                                symbol_name = str(row.symbol).upper()
                                symbol_canonical = _canonical_symbol_key(symbol_name)
                                resolved_ticker = canonical_to_ticker.get(symbol_canonical)
                                if not resolved_ticker:
                                    continue
                                source_name = str(row.source).lower()
                                imported_date = _coerce_date(row.date)
                                imported_created_at = _coerce_datetime(row.created_at)

                                has_fresh_by_date = imported_date is not None and imported_date >= boundary_date
                                has_fresh_by_time = (
                                    imported_created_at is not None and
                                    imported_created_at >= boundary_utc
                                )
                                if not (has_fresh_by_date or has_fresh_by_time):
                                    continue

                                source_flags = source_map.setdefault(
                                    resolved_ticker,
                                    {
                                        "finviz": False,
                                        "market_chameleon": False,
                                        "marketchameleon": False,
                                        "ibkr": False,
                                        "futu": False,
                                    },
                                )
                                if source_name == "finviz":
                                    source_flags["finviz"] = True
                                elif source_name == "marketchameleon":
                                    source_flags["market_chameleon"] = True
                                    source_flags["marketchameleon"] = True

                                candidate_dt = imported_created_at if imported_created_at is not None else boundary_utc
                                previous_dt = import_updated_dt_map.get(resolved_ticker)
                                if previous_dt is None or candidate_dt > previous_dt:
                                    import_updated_dt_map[resolved_ticker] = candidate_dt
                        except Exception as exc:
                            logger.warning(f"ImportedData query failed, skip import flags: {exc}")

                        try:
                            ibkr_price_rows = db.query(
                                PriceHistory.symbol,
                                func.max(PriceHistory.date).label("latest_date"),
                                func.max(PriceHistory.created_at).label("latest_created_at"),
                            ).filter(
                                PriceHistory.symbol.in_(ticker_query_symbols),
                                PriceHistory.source == "ibkr",
                            ).group_by(
                                PriceHistory.symbol
                            ).all()

                            for row in ibkr_price_rows:
                                symbol_name = str(row.symbol).upper()
                                resolved_ticker = canonical_to_ticker.get(_canonical_symbol_key(symbol_name))
                                if not resolved_ticker:
                                    continue
                                latest_price_date = _coerce_date(row.latest_date)
                                latest_price_created_at = _coerce_datetime(row.latest_created_at)
                                has_fresh_by_date = (
                                    latest_price_date is not None and
                                    latest_price_date >= boundary_date
                                )
                                has_fresh_by_time = (
                                    latest_price_created_at is not None and
                                    latest_price_created_at >= boundary_utc
                                )
                                if not (has_fresh_by_date or has_fresh_by_time):
                                    continue

                                source_map.setdefault(resolved_ticker, {}).update({"ibkr": True})
                                candidate_dt = (
                                    latest_price_created_at
                                    if latest_price_created_at is not None
                                    else boundary_utc
                                )
                                previous_dt = import_updated_dt_map.get(resolved_ticker)
                                if previous_dt is None or candidate_dt > previous_dt:
                                    import_updated_dt_map[resolved_ticker] = candidate_dt
                        except Exception as exc:
                            logger.warning(f"IBKR price query failed, skip ibkr flags: {exc}")

                        try:
                            iv_rows = db.query(
                                IVData.symbol,
                                IVData.date,
                                IVData.created_at,
                            ).filter(
                                IVData.symbol.in_(ticker_query_symbols),
                            ).all()

                            for row in iv_rows:
                                symbol_name = str(row.symbol).upper()
                                resolved_ticker = canonical_to_ticker.get(_canonical_symbol_key(symbol_name))
                                if not resolved_ticker:
                                    continue
                                iv_date = _coerce_date(row.date)
                                iv_created_at = _coerce_datetime(row.created_at)
                                has_fresh_by_date = iv_date is not None and iv_date >= boundary_date
                                has_fresh_by_time = (
                                    iv_created_at is not None and
                                    iv_created_at >= boundary_utc
                                )
                                if not (has_fresh_by_date or has_fresh_by_time):
                                    continue

                                source_map.setdefault(resolved_ticker, {}).update({"futu": True})
                                candidate_dt = iv_created_at if iv_created_at is not None else boundary_utc
                                previous_dt = import_updated_dt_map.get(resolved_ticker)
                                if previous_dt is None or candidate_dt > previous_dt:
                                    import_updated_dt_map[resolved_ticker] = candidate_dt
                        except Exception as exc:
                            logger.warning(f"Futu IV query failed, skip futu flags: {exc}")

                        for ticker in tickers:
                            stock_updated_dt = stock_updated_dt_map.get(ticker)
                            if stock_updated_dt is None or stock_updated_dt < boundary_utc:
                                continue
                            source_flags = source_map.setdefault(
                                ticker,
                                {
                                    "finviz": False,
                                    "market_chameleon": False,
                                    "marketchameleon": False,
                                    "ibkr": False,
                                    "futu": False,
                                },
                            )
                            source_flags["ibkr"] = True
                            stock_metrics = stock_metrics_map.get(ticker, {})
                            has_futu_metrics = any(
                                stock_metrics.get(metric_key) is not None
                                for metric_key in ("iv7", "iv60", "iv90", "openInterest", "total_oi")
                            )
                            if has_futu_metrics:
                                source_flags["futu"] = True
                            previous_dt = import_updated_dt_map.get(ticker)
                            if previous_dt is None or stock_updated_dt > previous_dt:
                                import_updated_dt_map[ticker] = stock_updated_dt

                        for ticker in tickers:
                            candidates = []
                            stock_dt = stock_updated_dt_map.get(ticker)
                            import_dt = import_updated_dt_map.get(ticker)
                            if isinstance(stock_dt, datetime):
                                candidates.append(stock_dt)
                            if isinstance(import_dt, datetime):
                                candidates.append(import_dt)
                            if not candidates:
                                updated_map[ticker] = None
                                continue
                            latest_dt = max(candidates)
                            if latest_dt.tzinfo is None:
                                latest_dt = latest_dt.replace(tzinfo=timezone.utc)
                            else:
                                latest_dt = latest_dt.astimezone(timezone.utc)
                            updated_map[ticker] = latest_dt.isoformat().replace("+00:00", "Z")
                except Exception as exc:
                    logger.warning(f"Stock score query failed, skip scores: {exc}")

            holdings_payload: List[Dict[str, Any]] = []
            for h in holdings_today:
                ticker = str(h.ticker).upper()
                source_flags = source_map.get(
                    ticker,
                    {
                        "finviz": False,
                        "market_chameleon": False,
                        "marketchameleon": False,
                        "ibkr": False,
                        "futu": False,
                    },
                )
                stock_metrics = stock_metrics_map.get(ticker, {})
                deviation_raw = stock_metrics.get("deviationFrom20ma")
                deviation_value: Optional[float] = None
                if isinstance(deviation_raw, (int, float)):
                    parsed_deviation = float(deviation_raw)
                    if math.isfinite(parsed_deviation):
                        deviation_value = parsed_deviation

                has_finviz = bool(source_flags.get("finviz"))
                has_mc = bool(source_flags.get("market_chameleon") or source_flags.get("marketchameleon"))
                has_ibkr = bool(source_flags.get("ibkr"))
                has_futu = bool(source_flags.get("futu"))
                holding_completeness = (
                    (20.0 if has_finviz else 0.0) +
                    (10.0 if has_mc else 0.0) +
                    (40.0 if has_ibkr else 0.0) +
                    (30.0 if has_futu else 0.0)
                )
                if holding_completeness >= 80.0:
                    holding_status = "complete"
                elif holding_completeness >= 50.0:
                    holding_status = "pending"
                else:
                    holding_status = "missing"
                holdings_payload.append(
                    {
                        "ticker": h.ticker,
                        "weight": h.weight,
                        "score": score_map.get(ticker),
                        "price": stock_price_map.get(ticker),
                        "deviationFrom20ma": deviation_value,
                        "aboveSma20": (deviation_value > 0) if deviation_value is not None else None,
                        "updatedAt": updated_map.get(ticker),
                        "dataSources": source_flags,
                        "dataStatus": holding_status,
                        "completeness": holding_completeness,
                    }
                )

            result["holdings"] = holdings_payload

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
    
    etf = db.query(ETF).filter(ETF.symbol == symbol.upper()).first()
    
    if not etf:
        raise HTTPException(status_code=404, detail=f"ETF '{symbol}' not found")
    
    # 跟踪数据完整性
    data_sources = {
        'ibkr_price': False,
        'ibkr_relmom': False,
        'ibkr_trend': False,
        'futu_iv': False,
        'finviz_breadth': False,
        'mc_options': False
    }
    
    score_result = _default_etf_score_result()

    latest_snapshot = db.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == etf.symbol,
        ScoreSnapshot.symbol_type == 'etf'
    ).order_by(ScoreSnapshot.date.desc(), ScoreSnapshot.id.desc()).first()

    if latest_snapshot and isinstance(latest_snapshot.score_breakdown, dict):
        score_result = _load_etf_score_result(latest_snapshot.score_breakdown)

    now_utc = datetime.utcnow()
    latest_ibkr_created_at = _coerce_datetime(
        db.query(func.max(PriceHistory.created_at)).filter(
            PriceHistory.symbol == etf.symbol,
            PriceHistory.source == "ibkr",
        ).scalar()
    )
    latest_futu_created_at = _coerce_datetime(
        db.query(func.max(IVData.created_at)).filter(
            IVData.symbol == etf.symbol,
            IVData.source == "futu",
        ).scalar()
    )
    ibkr_gate_state = _build_refresh_gate_state(latest_ibkr_created_at, now_utc=now_utc)
    futu_gate_state = _build_refresh_gate_state(latest_futu_created_at, now_utc=now_utc)
    has_cached_ibkr_breakdown = (
        score_result['rel_mom'].get('data') is not None
        and score_result['trend_quality'].get('data') is not None
    )
    has_cached_futu_breakdown = score_result['options_confirm'].get('data') is not None
    skip_ibkr_refresh = bool(ibkr_gate_state.get("is_recent")) and has_cached_ibkr_breakdown
    skip_futu_refresh = bool(futu_gate_state.get("is_recent")) and (
        has_cached_futu_breakdown or latest_futu_created_at is not None
    )
    next_refresh_at = _pick_next_refresh_at([ibkr_gate_state, futu_gate_state])

    if skip_ibkr_refresh:
        data_sources['ibkr_price'] = latest_ibkr_created_at is not None
        data_sources['ibkr_relmom'] = score_result['rel_mom'].get('data') is not None
        data_sources['ibkr_trend'] = score_result['trend_quality'].get('data') is not None
    if skip_futu_refresh:
        data_sources['futu_iv'] = (
            latest_futu_created_at is not None
            or score_result['options_confirm'].get('data') is not None
        )

    if skip_ibkr_refresh and skip_futu_refresh:
        recalculated = _recalculate_etf_score_from_db(
            etf,
            db,
            base_breakdown=score_result,
            base_data_sources=data_sources,
        )
        next_refresh_bjt = _format_beijing_time(next_refresh_at)
        skip_message = (
            f"IBKR 与 Futu 数据在 {ETF_REFRESH_COOLDOWN_MINUTES} 分钟内已刷新，已跳过。"
            + (f"下次可刷新时间（北京时间）{next_refresh_bjt}" if next_refresh_bjt else "")
        )
        return {
            "status": "snapshot",
            "symbol": etf.symbol,
            "message": skip_message,
            "score": recalculated["score"],
            "rank": recalculated["rank"],
            "completeness": recalculated["completeness"],
            "thresholds_pass": recalculated["thresholds_pass"],
            "breakdown": recalculated["breakdown"],
            "data_sources": recalculated["data_sources"],
            "next_refresh_at": _iso_utc(next_refresh_at),
            "refresh_gate": {
                "cooldown_minutes": ETF_REFRESH_COOLDOWN_MINUTES,
                "ibkr": _build_refresh_gate_payload(ibkr_gate_state),
                "futu": _build_refresh_gate_payload(futu_gate_state),
            },
            "warnings": [skip_message],
        }

    warnings = []
    if skip_ibkr_refresh:
        next_ibkr_text = _format_beijing_time(_coerce_datetime(ibkr_gate_state.get("next_refresh_at")))
        warnings.append(
            f"IBKR 数据在 {ETF_REFRESH_COOLDOWN_MINUTES} 分钟内已刷新，跳过 IBKR 拉取"
            + (f"（北京时间可刷新时间 {next_ibkr_text}）" if next_ibkr_text else "")
        )
    if skip_futu_refresh:
        next_futu_text = _format_beijing_time(_coerce_datetime(futu_gate_state.get("next_refresh_at")))
        warnings.append(
            f"Futu 数据在 {ETF_REFRESH_COOLDOWN_MINUTES} 分钟内已刷新，跳过 Futu 拉取"
            + (f"（北京时间可刷新时间 {next_futu_text}）" if next_futu_text else "")
        )

    orchestrator = get_orchestrator()
    broker_status = orchestrator.get_broker_status()

    price_df = None
    ibkr_started_at = perf_counter()
    ibkr_price_log = "N/A (not_started)"
    ibkr_relmom_log = "N/A (not_started)"
    ibkr_trend_log = "N/A (not_started)"

    def _fmt_float(value: Optional[Any], digits: int = 2) -> str:
        if isinstance(value, (int, float)):
            return f"{float(value):.{digits}f}"
        return "N/A"
    
    # ==================== 1. 从 IBKR 获取数据 ====================
    ibkr_status = broker_status.get('ibkr', {})
    ibkr_connected = ibkr_status.get('is_connected', False)
    ibkr_disconnect_reason = ibkr_status.get('last_error')
    
    if (not skip_ibkr_refresh) and (not ibkr_connected):
        # 尝试连接 IBKR
        try:
            ibkr_connected = await orchestrator.connect_ibkr()
            if ibkr_connected:
                warnings.append("已自动连接 IBKR")
            else:
                ibkr_disconnect_reason = "connect_failed"
        except Exception as e:
            warnings.append(f"IBKR 连接失败: {str(e)}")
            ibkr_disconnect_reason = str(e)
    
    if skip_ibkr_refresh:
        ibkr_refresh_time = _format_beijing_time(_coerce_datetime(ibkr_gate_state.get("next_refresh_at")))
        ibkr_price_log = (
            f"N/A (skip_cooldown_until_bjt={ibkr_refresh_time})"
            if ibkr_refresh_time
            else "N/A (skip_cooldown)"
        )
        ibkr_relmom_log = ibkr_price_log
        ibkr_trend_log = ibkr_price_log
    elif ibkr_connected:
        # 1.1 获取价格数据
        try:
            price_df = await orchestrator.get_ohlcv_data(etf.symbol, '100 D')
            if price_df is not None and not price_df.empty:
                data_sources['ibkr_price'] = True
                ibkr_rows = len(price_df)
                ibkr_new_rows = 0
                last_date = price_df['date'].iloc[-1]
                last_date_str = (
                    last_date.strftime('%Y-%m-%d')
                    if hasattr(last_date, 'strftime')
                    else str(last_date)
                )
                last_close = price_df['close'].iloc[-1]
                
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
                            ibkr_new_rows += 1
                    except Exception:
                        pass  # 忽略单条记录的错误
                db.commit()
                ibkr_price_log = (
                    f"{ibkr_rows} bars, last={last_date_str}, "
                    f"close={_fmt_float(last_close, 2)}, new_rows={ibkr_new_rows}"
                )
            else:
                warnings.append("IBKR 价格数据为空")
                ibkr_price_log = "N/A (empty_data)"
        except Exception as e:
            warnings.append(f"IBKR 价格数据获取失败: {str(e)}")
            ibkr_price_log = "N/A (request_failed)"
            logger.warning("ibkr_price_fetch_failed symbol=%s error=%s", etf.symbol, str(e))
        
        # 1.2 计算相对动量 (RelMom)
        try:
            relmom_result = await orchestrator.calculate_relative_momentum(etf.symbol, 'SPY')
            if relmom_result and not relmom_result.get('error'):
                data_sources['ibkr_relmom'] = True
                
                # RelMom 值转换为 0-100 分数 (范围 [-0.1, 0.15] 映射到 [0, 100])
                rel_mom = relmom_result.get('RelMom', 0) or 0
                rel_mom_score = (rel_mom + 0.1) / 0.25 * 100
                rel_mom_score = min(100, max(0, rel_mom_score))

                strength = 'NEUTRAL'
                description = '中性,与大盘同步'
                if rel_mom > 0.05:
                    strength = 'STRONG'
                    description = '强势，显著跑赢大盘'
                elif rel_mom > 0.02:
                    strength = 'MODERATE_STRONG'
                    description = '较强,略微跑赢大盘'
                elif rel_mom > -0.02:
                    strength = 'NEUTRAL'
                    description = '中性,与大盘同步'
                elif rel_mom > -0.05:
                    strength = 'MODERATE_WEAK'
                    description = '较弱,略微跑输大盘'
                else:
                    strength = 'WEAK'
                    description = '弱势,显著跑输大盘'
                
                score_result['rel_mom'] = {
                    'score': round(rel_mom_score, 2),
                    'data': {
                        'RS': relmom_result.get('RS'),
                        'RS_5D': relmom_result.get('RS_5D'),
                        'RS_20D': relmom_result.get('RS_20D'),
                        'RS_63D': relmom_result.get('RS_63D'),
                        'RelMom': relmom_result.get('RelMom'),
                        'strength': strength,
                        'description': description
                    }
                }
                ibkr_relmom_log = (
                    f"RelMom={_fmt_float(rel_mom, 4)}, "
                    f"RS20D={_fmt_float(relmom_result.get('RS_20D'), 4)}, "
                    f"score={_fmt_float(rel_mom_score, 2)}"
                )
            else:
                warnings.append("RelMom 数据不可用")
                relmom_reason = relmom_result.get('error') if isinstance(relmom_result, dict) else "no_data"
                ibkr_relmom_log = f"N/A ({relmom_reason})"
        except Exception as e:
            warnings.append(f"RelMom 计算失败: {str(e)}")
            ibkr_relmom_log = "N/A (request_failed)"
            logger.warning("ibkr_relmom_failed symbol=%s error=%s", etf.symbol, str(e))
        
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
                ibkr_trend_log = (
                    f"score={_fmt_float(trend_score, 0)}, "
                    f"P>SMA50={price_above_sma50}, "
                    f"SMA20>SMA50={sma20_above_sma50}, "
                    f"slope5={_fmt_float(sma20_slope, 4)}, "
                    f"maxDD20={_fmt_float(max_dd, 4)}"
                )
            else:
                ibkr_trend_log = "N/A (insufficient_price_bars)"
        except Exception as e:
            warnings.append(f"趋势质量计算失败: {str(e)}")
            ibkr_trend_log = "N/A (request_failed)"
            logger.warning("ibkr_trend_calc_failed symbol=%s error=%s", etf.symbol, str(e))
    else:
        warnings.append("IBKR 未连接，无法获取价格数据和计算 RelMom")
        reason = ibkr_disconnect_reason or "disconnected"
        ibkr_price_log = f"N/A ({reason})"
        ibkr_relmom_log = f"N/A ({reason})"
        ibkr_trend_log = f"N/A ({reason})"
        logger.warning("ibkr_refresh_skipped symbol=%s reason=%s", etf.symbol, reason)

    ibkr_elapsed_ms = (perf_counter() - ibkr_started_at) * 1000
    logger.info(
        "\n".join(
            [
                f"IBKR- [1/1] {etf.symbol}",
                f" - OHLCV(100D): {ibkr_price_log}",
                f" - RelMom vs SPY: {ibkr_relmom_log}",
                f" - Trend Quality: {ibkr_trend_log}",
                f" - Elapsed: {ibkr_elapsed_ms:.1f} ms",
                "---",
            ]
        )
    )
    
    # ==================== 2. 从 Futu 获取 IV 数据 ====================
    futu_connected = broker_status.get('futu', {}).get('is_connected', False)
    
    if (not skip_futu_refresh) and (not futu_connected):
        # 尝试连接 Futu
        try:
            futu_connected = await orchestrator.connect_futu()
            if futu_connected:
                warnings.append("已自动连接 Futu")
        except Exception:
            pass  # Futu 是可选的

    if skip_futu_refresh:
        pass
    elif futu_connected and orchestrator._futu:
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
                        existing_iv.oi_bucket_0_7 = getattr(iv_data, "oi_bucket_0_7", None)
                        existing_iv.oi_bucket_8_30 = getattr(iv_data, "oi_bucket_8_30", None)
                        existing_iv.oi_bucket_31_90 = getattr(iv_data, "oi_bucket_31_90", None)
                        existing_iv.call_oi_bucket_0_7 = getattr(iv_data, "call_oi_bucket_0_7", None)
                        existing_iv.call_oi_bucket_8_30 = getattr(iv_data, "call_oi_bucket_8_30", None)
                        existing_iv.call_oi_bucket_31_90 = getattr(iv_data, "call_oi_bucket_31_90", None)
                        existing_iv.put_oi_bucket_0_7 = getattr(iv_data, "put_oi_bucket_0_7", None)
                        existing_iv.put_oi_bucket_8_30 = getattr(iv_data, "put_oi_bucket_8_30", None)
                        existing_iv.put_oi_bucket_31_90 = getattr(iv_data, "put_oi_bucket_31_90", None)
                    else:
                        iv_record = IVData(
                            symbol=etf.symbol,
                            date=today,
                            iv7=iv_data.iv7,
                            iv30=iv_data.iv30,
                            iv60=iv_data.iv60,
                            iv90=iv_data.iv90,
                            total_oi=iv_data.total_oi,
                            oi_bucket_0_7=getattr(iv_data, "oi_bucket_0_7", None),
                            oi_bucket_8_30=getattr(iv_data, "oi_bucket_8_30", None),
                            oi_bucket_31_90=getattr(iv_data, "oi_bucket_31_90", None),
                            call_oi_bucket_0_7=getattr(iv_data, "call_oi_bucket_0_7", None),
                            call_oi_bucket_8_30=getattr(iv_data, "call_oi_bucket_8_30", None),
                            call_oi_bucket_31_90=getattr(iv_data, "call_oi_bucket_31_90", None),
                            put_oi_bucket_0_7=getattr(iv_data, "put_oi_bucket_0_7", None),
                            put_oi_bucket_8_30=getattr(iv_data, "put_oi_bucket_8_30", None),
                            put_oi_bucket_31_90=getattr(iv_data, "put_oi_bucket_31_90", None),
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
    
    recalculated = _recalculate_etf_score_from_db(
        etf,
        db,
        base_breakdown=score_result,
        base_data_sources=data_sources,
    )

    return {
        "status": "success",
        "symbol": etf.symbol,
        "message": f"ETF {etf.symbol} 数据已刷新",
        "score": recalculated["score"],
        "rank": recalculated["rank"],
        "completeness": recalculated["completeness"],
        "thresholds_pass": recalculated["thresholds_pass"],
        "thresholds": recalculated["thresholds"],
        "breakdown": recalculated["breakdown"],
        "data_sources": recalculated["data_sources"],
        "warnings": warnings if warnings else None,
        "next_refresh_at": _iso_utc(next_refresh_at),
        "refresh_gate": {
            "cooldown_minutes": ETF_REFRESH_COOLDOWN_MINUTES,
            "ibkr": _build_refresh_gate_payload(ibkr_gate_state),
            "futu": _build_refresh_gate_payload(futu_gate_state),
        },
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


@router.get("/symbol/{symbol}/refresh-holdings-progress/{progress_token}", response_model=dict)
async def get_refresh_holdings_progress(
    symbol: str,
    progress_token: str,
):
    """查询 refresh-holdings-by-coverage 的实时进度。"""
    normalized_symbol = symbol.upper().strip()
    token = _normalize_progress_token(progress_token)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid progress_token")

    snapshot = _get_holdings_refresh_progress(token)
    if not snapshot:
        return {
            "status": "pending",
            "symbol": normalized_symbol,
            "coverage": None,
            "completed": 0,
            "total": 0,
            "failed": 0,
            "current_item": "",
            "message": "等待任务启动...",
            "progress_percentage": 0,
            "started_at": None,
            "finished_at": None,
            "updated_at": _utc_now_iso(),
        }

    if str(snapshot.get("symbol", "")).upper() != normalized_symbol:
        raise HTTPException(status_code=404, detail="Progress token not found for this symbol")

    completed = int(snapshot.get("completed") or 0)
    total = int(snapshot.get("total") or 0)
    snapshot["progress_percentage"] = round((completed / total) * 100) if total > 0 else 0
    return snapshot


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
    - coverage_type: 覆盖范围类型 ("top"、"weight" 或 "all")
    - coverage_value: 覆盖范围值 (如果 type=top 则为数字如 10、15；如果 type=weight 则为百分比如 60、70；如果 type=all 则忽略)

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
    filtered_holdings = _filter_holdings_by_coverage(all_holdings, coverage_type, coverage_value)

    coverage_label = _format_coverage_label(coverage_type, coverage_value)
    progress_token = _normalize_progress_token(request.progress_token)
    if request.progress_token and not progress_token:
        raise HTTPException(status_code=400, detail="Invalid progress_token")

    progress_completed = 0
    progress_failed = 0
    total_targets = len(filtered_holdings)

    if progress_token:
        _set_holdings_refresh_progress(
            progress_token,
            {
                "status": "running",
                "symbol": symbol.upper(),
                "coverage": coverage_label,
                "completed": 0,
                "total": total_targets,
                "failed": 0,
                "current_item": "",
                "message": "正在校验导入数据...",
                "started_at": _utc_now_iso(),
                "finished_at": None,
            },
        )

    # 刷新前置校验：当前覆盖范围下，Finviz + MarketChameleon 必须是北京时间 08:00 起算后的最新导入数据
    def _beijing_import_boundary() -> Dict[str, Any]:
        now_utc = datetime.utcnow()
        now_beijing = now_utc + timedelta(hours=8)
        boundary_beijing = now_beijing.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_beijing < boundary_beijing:
            boundary_beijing -= timedelta(days=1)
        return {
            "boundary_utc": boundary_beijing - timedelta(hours=8),
            "boundary_beijing": boundary_beijing,
            "boundary_date": boundary_beijing.date(),
        }

    def _summarize_missing(symbols: List[str], max_items: int = 6) -> str:
        if not symbols:
            return ""
        if len(symbols) <= max_items:
            return ", ".join(symbols)
        return f"{', '.join(symbols[:max_items])} 等{len(symbols)}只"

    coverage_symbols = list(dict.fromkeys(h.ticker.upper() for h in filtered_holdings if h.ticker))
    coverage_key_to_symbol: Dict[str, str] = {}
    for symbol_name in coverage_symbols:
        symbol_key = _canonical_symbol_key(symbol_name)
        if symbol_key and symbol_key not in coverage_key_to_symbol:
            coverage_key_to_symbol[symbol_key] = symbol_name
    coverage_query_symbols = sorted(
        {
            alias
            for symbol_name in coverage_symbols
            for alias in _symbol_aliases(symbol_name)
        }
    )
    coverage_fresh_imports: Dict[str, set] = {}
    if coverage_symbols and coverage_query_symbols:
        boundary = _beijing_import_boundary()
        boundary_utc = boundary["boundary_utc"]
        boundary_date = boundary["boundary_date"]
        boundary_bjt = boundary["boundary_beijing"].strftime("%Y-%m-%d %H:%M")

        imported_rows = db.query(
            ImportedData.symbol,
            ImportedData.source,
            ImportedData.date,
            ImportedData.created_at
        ).filter(
            ImportedData.symbol.in_(coverage_query_symbols),
            ImportedData.source.in_(["finviz", "marketchameleon"])
        ).all()

        fresh_imports = set()
        fresh_imports_by_symbol: Dict[str, set] = {}
        for row in imported_rows:
            symbol_name = str(row.symbol).upper()
            symbol_key = _canonical_symbol_key(symbol_name)
            resolved_symbol = coverage_key_to_symbol.get(symbol_key)
            if not resolved_symbol:
                continue
            source_name = str(row.source).lower()
            imported_date = row.date
            imported_created_at = row.created_at

            has_fresh_by_date = imported_date is not None and imported_date >= boundary_date
            has_fresh_by_time = (
                isinstance(imported_created_at, datetime) and
                imported_created_at >= boundary_utc
            )

            if has_fresh_by_date or has_fresh_by_time:
                fresh_imports.add((resolved_symbol, source_name))
                fresh_imports_by_symbol.setdefault(resolved_symbol, set()).add(source_name)

        missing_finviz = [s for s in coverage_symbols if (s, "finviz") not in fresh_imports]
        missing_mc = [s for s in coverage_symbols if (s, "marketchameleon") not in fresh_imports]

        if missing_finviz or missing_mc:
            detail_parts = [
                f"请先导入当前覆盖范围（{coverage_label}）Finviz 与 MarketChameleon 最新数据（北京时间 {boundary_bjt} 起算）"
            ]
            if missing_finviz:
                detail_parts.append(f"Finviz 缺失: {_summarize_missing(missing_finviz)}")
            if missing_mc:
                detail_parts.append(f"MarketChameleon 缺失: {_summarize_missing(missing_mc)}")
            detail = "；".join(detail_parts)
            if progress_token:
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "status": "error",
                        "message": detail,
                        "finished_at": _utc_now_iso(),
                    },
                )
            raise HTTPException(status_code=400, detail=detail)

        logger.info(
            "refresh_holdings_import_guard_passed symbol=%s coverage=%s boundary_bjt=%s symbols=%s",
            symbol.upper(),
            coverage_label,
            boundary_bjt,
            len(coverage_symbols),
        )
        coverage_fresh_imports = fresh_imports_by_symbol
        if progress_token:
            _patch_holdings_refresh_progress(
                progress_token,
                {
                    "message": f"导入校验通过，准备刷新 {len(filtered_holdings)} 个标的...",
                },
            )

    related_etf_symbols: List[str] = []
    if isinstance(request.related_etf_symbols, list):
        for candidate in request.related_etf_symbols:
            if not isinstance(candidate, str):
                continue
            normalized = candidate.strip().upper()
            if not normalized or normalized == symbol.upper():
                continue
            if normalized not in related_etf_symbols:
                related_etf_symbols.append(normalized)
    has_related_etf_scope = len(related_etf_symbols) > 0
    coverage_symbol_set = set(coverage_symbols)
    duplicate_scope_symbols: set[str] = set()
    if has_related_etf_scope and coverage_symbols:
        for peer_symbol in related_etf_symbols:
            peer_latest_date = db.query(func.max(ETFHolding.data_date)).filter(
                ETFHolding.etf_symbol == peer_symbol
            ).scalar()
            if not peer_latest_date:
                continue
            peer_holdings_all = db.query(ETFHolding).filter(
                ETFHolding.etf_symbol == peer_symbol,
                ETFHolding.data_date == peer_latest_date
            ).order_by(ETFHolding.weight.desc()).all()
            if not peer_holdings_all:
                continue
            peer_filtered_holdings = _filter_holdings_by_coverage(
                peer_holdings_all,
                coverage_type=coverage_type,
                coverage_value=coverage_value,
            )

            for peer_holding in peer_filtered_holdings:
                ticker_name = str(peer_holding.ticker).upper() if peer_holding.ticker else ""
                if ticker_name and ticker_name in coverage_symbol_set:
                    duplicate_scope_symbols.add(ticker_name)

        logger.info(
            "refresh_holdings_related_scope symbol=%s coverage=%s related_etfs=%s duplicate_symbols=%s",
            symbol.upper(),
            coverage_label,
            len(related_etf_symbols),
            len(duplicate_scope_symbols),
        )

    now_utc = datetime.utcnow()
    ibkr_latest_rows = []
    futu_latest_rows = []
    if coverage_symbols:
        ibkr_latest_rows = db.query(
            PriceHistory.symbol,
            func.max(PriceHistory.created_at).label("latest_created_at"),
        ).filter(
            PriceHistory.symbol.in_(coverage_symbols),
            PriceHistory.source == "ibkr",
        ).group_by(PriceHistory.symbol).all()
        futu_latest_rows = db.query(
            IVData.symbol,
            func.max(IVData.created_at).label("latest_created_at"),
        ).filter(
            IVData.symbol.in_(coverage_symbols),
            IVData.source == "futu",
        ).group_by(IVData.symbol).all()

    ibkr_latest_map = {
        str(row.symbol).upper(): _coerce_datetime(getattr(row, "latest_created_at", None))
        for row in ibkr_latest_rows
    }
    futu_latest_map = {
        str(row.symbol).upper(): _coerce_datetime(getattr(row, "latest_created_at", None))
        for row in futu_latest_rows
    }
    ibkr_gate_by_symbol = {
        ticker: _build_refresh_gate_state(
            ibkr_latest_map.get(ticker),
            now_utc=now_utc,
            cooldown=HOLDINGS_REFRESH_COOLDOWN,
        )
        for ticker in coverage_symbols
    }
    futu_gate_by_symbol = {
        ticker: _build_refresh_gate_state(
            futu_latest_map.get(ticker),
            now_utc=now_utc,
            cooldown=HOLDINGS_REFRESH_COOLDOWN,
        )
        for ticker in coverage_symbols
    }
    ibkr_recent_all = bool(coverage_symbols) and all(
        bool(state.get("is_recent")) for state in ibkr_gate_by_symbol.values()
    )
    futu_recent_all = bool(coverage_symbols) and all(
        bool(state.get("is_recent")) for state in futu_gate_by_symbol.values()
    )
    if (not has_related_etf_scope) and ibkr_recent_all and futu_recent_all:
        _recalculate_etf_score_from_db(etf, db)
        all_gate_states = list(ibkr_gate_by_symbol.values()) + list(futu_gate_by_symbol.values())
        next_refresh_at = _pick_next_refresh_at(all_gate_states)
        next_refresh_bjt = _format_beijing_time(next_refresh_at)
        skip_message = (
            f"IBKR 与 Futu 数据在 {HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟内已刷新，已跳过。"
            + (f"下次可刷新时间（北京时间）{next_refresh_bjt}" if next_refresh_bjt else "")
        )
        if progress_token:
            _patch_holdings_refresh_progress(
                progress_token,
                {
                    "status": "completed",
                    "completed": total_targets,
                    "failed": 0,
                    "current_item": "",
                    "message": skip_message,
                    "finished_at": _utc_now_iso(),
                },
            )
        total_weight = sum(h.weight for h in filtered_holdings)
        return {
            "status": "snapshot",
            "symbol": symbol.upper(),
            "coverage": coverage_label,
            "stocks_count": len(filtered_holdings),
            "total_weight": round(total_weight, 2),
            "futu_failed_count": 0,
            "completeness": {},
            "updated_stocks": [],
            "updated_at": _utc_now_iso(),
            "message": skip_message,
            "next_refresh_at": _iso_utc(next_refresh_at),
            "refresh_gate": {
                "cooldown_minutes": HOLDINGS_REFRESH_COOLDOWN_MINUTES,
                "ibkr": {
                    "all_recent": ibkr_recent_all,
                    "recent_count": sum(1 for state in ibkr_gate_by_symbol.values() if state.get("is_recent")),
                    "total": len(coverage_symbols),
                    "next_refresh_at": _iso_utc(_pick_next_refresh_at(list(ibkr_gate_by_symbol.values()))),
                },
                "futu": {
                    "all_recent": futu_recent_all,
                    "recent_count": sum(1 for state in futu_gate_by_symbol.values() if state.get("is_recent")),
                    "total": len(coverage_symbols),
                    "next_refresh_at": _iso_utc(_pick_next_refresh_at(list(futu_gate_by_symbol.values()))),
                },
            },
        }

    completeness_calculator = DataCompletenessCalculator(db)
    cooldown_scope_symbols = set(coverage_symbols)
    if has_related_etf_scope:
        cooldown_scope_symbols = set(duplicate_scope_symbols)

    recent_skip_symbol_set = {
        ticker
        for ticker in cooldown_scope_symbols
        if bool(ibkr_gate_by_symbol.get(ticker, {}).get("is_recent"))
        and bool(futu_gate_by_symbol.get(ticker, {}).get("is_recent"))
    }
    if has_related_etf_scope:
        ibkr_recent_duplicates = sum(
            1 for ticker in cooldown_scope_symbols if bool(ibkr_gate_by_symbol.get(ticker, {}).get("is_recent"))
        )
        futu_recent_duplicates = sum(
            1 for ticker in cooldown_scope_symbols if bool(futu_gate_by_symbol.get(ticker, {}).get("is_recent"))
        )
        logger.info(
            "refresh_holdings_duplicate_cooldown_eval symbol=%s coverage=%s duplicates=%s both_recent=%s ibkr_recent=%s futu_recent=%s",
            symbol.upper(),
            coverage_label,
            len(cooldown_scope_symbols),
            len(recent_skip_symbol_set),
            ibkr_recent_duplicates,
            futu_recent_duplicates,
        )
    skipped_recent_holdings: List[ETFHolding] = []
    holdings_to_refresh: List[ETFHolding] = []
    for holding in filtered_holdings:
        ticker_text = str(holding.ticker).upper() if holding.ticker else ""
        if ticker_text and ticker_text in recent_skip_symbol_set:
            skipped_recent_holdings.append(holding)
        else:
            holdings_to_refresh.append(holding)

    skipped_recent_count = len(skipped_recent_holdings)
    refresh_targets_count = len(holdings_to_refresh)
    duplicate_scope_count = len(duplicate_scope_symbols)
    if skipped_recent_count > 0:
        skipped_symbols_preview = ", ".join(
            str(h.ticker).upper() for h in skipped_recent_holdings[:6] if h.ticker
        )
        if has_related_etf_scope:
            skip_reason = (
                f"同任务重复标的共 {duplicate_scope_count} 只，"
                f"其中 {skipped_recent_count} 只在 {HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟冷却内已具备市场+期权数据"
            )
        else:
            skip_reason = f"已跳过 {skipped_recent_count} 只（{HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟内已有市场+期权数据）"
        logger.info(
            "refresh_holdings_symbol_skip_recent symbol=%s coverage=%s skipped=%s total=%s cooldown_scope=%s preview=%s",
            symbol.upper(),
            coverage_label,
            skipped_recent_count,
            total_targets,
            len(cooldown_scope_symbols),
            skipped_symbols_preview,
        )
        progress_completed = skipped_recent_count
        if progress_token:
            _patch_holdings_refresh_progress(
                progress_token,
                {
                    "completed": progress_completed,
                    "failed": progress_failed,
                    "message": (
                        f"{skip_reason}，待刷新 {refresh_targets_count} 只..."
                    ),
                },
            )

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
        latest_row = df.iloc[-1]
        latest_row_date = latest_row['date'].date() if hasattr(latest_row['date'], 'date') else latest_row['date']
        existing_latest = db.query(PriceHistory).filter(
            PriceHistory.symbol == symbol.upper(),
            PriceHistory.date == latest_row_date,
        ).first()
        if existing_latest:
            # Refresh latest bar's created_at so "today freshness" can be inferred by API consumers.
            existing_latest.open = float(latest_row.get('open', 0) or 0)
            existing_latest.high = float(latest_row.get('high', 0) or 0)
            existing_latest.low = float(latest_row.get('low', 0) or 0)
            existing_latest.close = float(latest_row.get('close', 0) or 0)
            existing_latest.volume = int(latest_row.get('volume', 0) or 0)
            existing_latest.source = source
            existing_latest.created_at = datetime.utcnow()
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
        query_symbols = _symbol_aliases(symbol)
        if not query_symbols:
            return None
        record = db.query(ImportedData).filter(
            ImportedData.symbol.in_(query_symbols),
            ImportedData.source == source
        ).order_by(
            ImportedData.date.desc(),
            ImportedData.created_at.desc(),
            ImportedData.id.desc()
        ).first()
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

    def _as_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_bucket_totals(row: Dict[str, Any]) -> Dict[str, Dict[str, Optional[int]]]:
        payload: Dict[str, Dict[str, Optional[int]]] = {}
        for suffix in ("0_7", "8_30", "31_90"):
            net_value = _as_int(row.get(f"oi_bucket_{suffix}"))
            call_value = _as_int(row.get(f"call_oi_bucket_{suffix}"))
            put_value = _as_int(row.get(f"put_oi_bucket_{suffix}"))
            if net_value is None and call_value is not None and put_value is not None:
                net_value = call_value + put_value
            payload[suffix] = {
                "net": net_value,
                "call": call_value,
                "put": put_value,
            }
        return payload

    def _compute_bucket_delta_payload(
        ticker: str,
        today: date,
        bucket_totals: Dict[str, Dict[str, Optional[int]]],
        total_oi_value: Optional[int],
    ) -> Dict[str, Any]:
        previous_rows = db.query(IVData).filter(
            IVData.symbol == ticker.upper(),
            IVData.date < today,
        ).order_by(IVData.date.desc(), IVData.id.desc()).limit(5).all()

        prev1 = previous_rows[0] if len(previous_rows) >= 1 else None
        prev3 = previous_rows[2] if len(previous_rows) >= 3 else None
        prev5 = previous_rows[4] if len(previous_rows) >= 5 else None

        def _delta(current: Optional[int], previous: Optional[int]) -> Optional[int]:
            if current is None or previous is None:
                return None
            return int(current - previous)

        by_bucket: Dict[str, Dict[str, Optional[int]]] = {}
        for suffix in ("0_7", "8_30", "31_90"):
            net_attr = f"oi_bucket_{suffix}"
            call_attr = f"call_oi_bucket_{suffix}"
            put_attr = f"put_oi_bucket_{suffix}"

            current_net = bucket_totals.get(suffix, {}).get("net")
            current_call = bucket_totals.get(suffix, {}).get("call")
            current_put = bucket_totals.get(suffix, {}).get("put")

            by_bucket[suffix] = {
                "net_1d": _delta(current_net, _as_int(getattr(prev1, net_attr, None)) if prev1 else None),
                "call_1d": _delta(current_call, _as_int(getattr(prev1, call_attr, None)) if prev1 else None),
                "put_1d": _delta(current_put, _as_int(getattr(prev1, put_attr, None)) if prev1 else None),
                "net_3d": _delta(current_net, _as_int(getattr(prev3, net_attr, None)) if prev3 else None),
                "net_5d": _delta(current_net, _as_int(getattr(prev5, net_attr, None)) if prev5 else None),
            }

        total_delta_1d = _delta(total_oi_value, _as_int(getattr(prev1, "total_oi", None)) if prev1 else None)
        return {
            "total_oi_1d": total_delta_1d,
            "by_bucket": by_bucket,
        }

    def _fmt_float(value: Optional[Any], digits: int = 2) -> str:
        if isinstance(value, (int, float)):
            return f"{float(value):.{digits}f}"
        return "N/A"

    def _build_skipped_recent_result(holding: ETFHolding) -> Dict[str, Any]:
        ticker = str(holding.ticker).upper() if holding.ticker else ""
        imported_sources = coverage_fresh_imports.get(ticker, set())
        data_sources: List[str] = []
        if "finviz" in imported_sources:
            data_sources.append("finviz")
        if "marketchameleon" in imported_sources:
            data_sources.extend(["marketchameleon", "market_chameleon", "mc"])
        data_sources.extend(["ibkr", "market_data", "futu", "options_data"])
        data_sources = list(dict.fromkeys(data_sources))

        latest_candidates = [
            dt
            for dt in (
                ibkr_latest_map.get(ticker),
                futu_latest_map.get(ticker),
            )
            if isinstance(dt, datetime)
        ]
        if latest_candidates:
            latest_dt = max(latest_candidates)
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.replace(tzinfo=timezone.utc)
            else:
                latest_dt = latest_dt.astimezone(timezone.utc)
            updated_at = latest_dt.isoformat().replace("+00:00", "Z")
        else:
            updated_at = _utc_now_iso()

        completeness_status = completeness_calculator.calculate_holding_data_completeness(
            ticker,
            {
                "price_data": None,
                "volume": None,
                "change_1d": None,
                "iv30": None,
                "data_sources": data_sources,
                "updated_at": updated_at,
            },
        )

        return {
            "ticker": ticker,
            "weight": holding.weight,
            "price": None,
            "change_1d": None,
            "data_sources": data_sources,
            "iv7": None,
            "iv30": None,
            "iv60": None,
            "iv90": None,
            "total_oi": None,
            "oi_bucket_0_7": None,
            "oi_bucket_8_30": None,
            "oi_bucket_31_90": None,
            "call_oi_bucket_0_7": None,
            "call_oi_bucket_8_30": None,
            "call_oi_bucket_31_90": None,
            "put_oi_bucket_0_7": None,
            "put_oi_bucket_8_30": None,
            "put_oi_bucket_31_90": None,
            "data_status": completeness_status.status,
            "completeness": completeness_status.completeness_score,
            "score": None,
            "updated_at": updated_at,
            "skipped_recent": True,
        }

    skipped_recent_results = [_build_skipped_recent_result(holding) for holding in skipped_recent_holdings]
    for item in skipped_recent_results:
        logger.info(
            "HOLDINGS- [SKIP] %s - 市场数据与期权数据在 %s 分钟冷却内，跳过抓取",
            str(item.get("ticker") or "").upper(),
            HOLDINGS_REFRESH_COOLDOWN_MINUTES,
        )

    # 并发获取股票数据
    from app.services.orchestrator import get_orchestrator
    from app.services.broker.futu import estimate_iv_fetch_time
    orchestrator = get_orchestrator()

    if progress_token:
        _patch_holdings_refresh_progress(
            progress_token,
            {
                "message": "正在连接/检查 IBKR 与 Futu...",
            },
        )

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

    if progress_token:
        start_fetch_message = "开始并发抓取持仓数据..."
        if skipped_recent_count > 0:
            if has_related_etf_scope:
                start_fetch_message = (
                    f"同任务重复标的 {duplicate_scope_count} 只，"
                    f"已跳过 {skipped_recent_count} 只（{HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟冷却），"
                    f"开始抓取剩余 {refresh_targets_count} 只..."
                )
            else:
                start_fetch_message = (
                    f"已跳过 {skipped_recent_count} 只（{HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟内已有市场+期权数据），"
                    f"开始抓取剩余 {refresh_targets_count} 只..."
                )
        _patch_holdings_refresh_progress(
            progress_token,
            {
                "message": start_fetch_message,
            },
        )

    # 预取板块（或父板块）价格用于相对强度计算
    sector_symbol = etf.parent_sector if etf.type == "industry" and etf.parent_sector else etf.symbol
    sector_df = _load_price_history(sector_symbol)
    ibkr_connected = orchestrator.get_broker_status().get("ibkr", {}).get("is_connected", False)
    if not ibkr_connected:
        logger.warning(
            "refresh_holdings_ibkr_unavailable symbol=%s coverage=%s",
            symbol.upper(),
            coverage_label,
        )
    ibkr_price_timeout_seconds = 30
    if sector_df is None and ibkr_connected:
        logger.info(
            "refresh_holdings_sector_prefetch symbol=%s coverage=%s sector_symbol=%s",
            symbol.upper(),
            coverage_label,
            sector_symbol,
        )
        try:
            sector_fetched = await asyncio.wait_for(
                orchestrator.get_ohlcv_data(sector_symbol, '1 Y'),
                timeout=ibkr_price_timeout_seconds,
            )
            if sector_fetched is not None and not sector_fetched.empty:
                _save_price_history(sector_symbol, sector_fetched)
                sector_df = sector_fetched
                logger.info(
                    "refresh_holdings_sector_prefetch_ok symbol=%s coverage=%s sector_symbol=%s bars=%s",
                    symbol.upper(),
                    coverage_label,
                    sector_symbol,
                    len(sector_fetched),
                )
        except asyncio.TimeoutError:
            logger.warning(
                "refresh_holdings_sector_price_timeout symbol=%s timeout_seconds=%s",
                sector_symbol,
                ibkr_price_timeout_seconds,
            )
        except Exception as e:
            logger.warning(f"Failed to get sector price data for {sector_symbol}: {e}")

    updated_stocks = list(skipped_recent_results)
    stock_semaphore = asyncio.Semaphore(5)  # 限制并发数为 5
    futu_symbols = list(
        dict.fromkeys(
            str(holding.ticker).upper()
            for holding in holdings_to_refresh
            if isinstance(getattr(holding, "ticker", None), str) and holding.ticker.strip()
        )
    )
    estimated_futu_seconds = estimate_iv_fetch_time(symbol_count=max(1, len(futu_symbols)))
    futu_iv_timeout_seconds = max(45, int(estimated_futu_seconds + 15))
    logger.info(
        "refresh_holdings_futu_timeout_budget symbol=%s coverage=%s timeout_seconds=%s tickers=%s",
        symbol.upper(),
        coverage_label,
        futu_iv_timeout_seconds,
        len(futu_symbols),
    )

    async def _fetch_futu_iv_batch(symbols: List[str]) -> Dict[str, Any]:
        normalized_symbols = list(dict.fromkeys(str(item).upper() for item in symbols if str(item).strip()))
        if not normalized_symbols or not orchestrator._futu or not orchestrator._futu.is_connected():
            return {}

        batch_started_at = perf_counter()
        logger.info(
            "refresh_holdings_futu_batch_start symbol=%s coverage=%s tickers=%s",
            symbol.upper(),
            coverage_label,
            len(normalized_symbols),
        )
        try:
            iv_results = await asyncio.wait_for(
                asyncio.to_thread(
                    orchestrator._futu.fetch_iv_terms,
                    normalized_symbols,
                    max_days=120,
                    max_retries=0,
                    progress_total=len(normalized_symbols),
                    progress_offset=0,
                    log_progress=False,
                    log_fetch_summary=False,
                ),
                timeout=futu_iv_timeout_seconds,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (perf_counter() - batch_started_at) * 1000
            logger.warning(
                "refresh_holdings_futu_iv_timeout_batch symbol=%s coverage=%s tickers=%s timeout_seconds=%s elapsed_ms=%s",
                symbol.upper(),
                coverage_label,
                len(normalized_symbols),
                futu_iv_timeout_seconds,
                round(elapsed_ms, 1),
            )
            if progress_token:
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "message": "Futu 批量期权数据获取超时，将继续完成其余流程。",
                    },
                )
            return {}
        except Exception as exc:
            elapsed_ms = (perf_counter() - batch_started_at) * 1000
            logger.warning(
                "refresh_holdings_futu_batch_failed symbol=%s coverage=%s tickers=%s elapsed_ms=%s error=%s",
                symbol.upper(),
                coverage_label,
                len(normalized_symbols),
                round(elapsed_ms, 1),
                str(exc),
            )
            if progress_token:
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "message": "Futu 批量期权数据获取失败，将继续完成其余流程。",
                    },
                )
            return {}

        payload = iv_results if isinstance(iv_results, dict) else {}
        ok_count = 0
        for ticker in normalized_symbols:
            item = payload.get(ticker)
            try:
                if item is not None and item.is_valid():
                    ok_count += 1
            except Exception:
                continue
        elapsed_ms = (perf_counter() - batch_started_at) * 1000
        logger.info(
            "refresh_holdings_futu_batch_done symbol=%s coverage=%s tickers=%s ok=%s fail=%s elapsed_ms=%s",
            symbol.upper(),
            coverage_label,
            len(normalized_symbols),
            ok_count,
            max(0, len(normalized_symbols) - ok_count),
            round(elapsed_ms, 1),
        )
        return payload

    futu_iv_task: Optional[asyncio.Task] = None
    if futu_symbols and orchestrator._futu and orchestrator._futu.is_connected():
        futu_iv_task = asyncio.create_task(_fetch_futu_iv_batch(futu_symbols))

    async def fetch_stock_data(holding: ETFHolding, idx: int, total_count: int):
        async with stock_semaphore:
            try:
                ticker = str(holding.ticker).upper()
                if progress_token:
                    _patch_holdings_refresh_progress(
                        progress_token,
                        {
                            "current_item": ticker,
                            "message": f"正在抓取 {ticker} ({idx}/{total_count})...",
                        },
                    )

                # 从 IBKR 获取价格数据
                price_data = None
                change_1d = None
                volume_data = None
                data_sources = []
                imported_sources = coverage_fresh_imports.get(ticker, set())
                if "finviz" in imported_sources:
                    data_sources.append("finviz")
                if "marketchameleon" in imported_sources:
                    data_sources.extend(["marketchameleon", "market_chameleon", "mc"])
                data_sources = list(dict.fromkeys(data_sources))

                stock_df = None
                ibkr_price_log = "N/A (not_connected)"
                if ibkr_connected:
                    try:
                        # 获取股票的日线数据（用于动能评分）
                        stock_df = await asyncio.wait_for(
                            orchestrator.get_ohlcv_data(holding.ticker, '1 Y'),
                            timeout=ibkr_price_timeout_seconds,
                        )
                        if stock_df is not None and not stock_df.empty:
                            latest_row = stock_df.iloc[-1]
                            price_data = float(latest_row.get('close', 0))
                            volume_data = float(latest_row.get('volume', 0))
                            data_sources.append('ibkr')
                            last_date = latest_row.get('date')
                            if hasattr(last_date, 'strftime'):
                                last_date_str = last_date.strftime('%Y-%m-%d')
                            else:
                                last_date_str = str(last_date)
                            ibkr_price_log = (
                                f"{len(stock_df)} bars, last={last_date_str}, "
                                f"close={_fmt_float(price_data, 2)}, volume={_fmt_float(volume_data, 0)}"
                            )

                            # 计算 1 日涨跌幅
                            if len(stock_df) >= 2:
                                prev_close = float(stock_df.iloc[-2].get('close', 0))
                                if prev_close > 0:
                                    change_1d = ((price_data - prev_close) / prev_close) * 100
                        else:
                            ibkr_price_log = "N/A (empty_data)"
                    except asyncio.TimeoutError:
                        ibkr_price_log = "N/A (request_timeout)"
                        logger.warning(
                            "ibkr_holding_price_fetch_timeout symbol=%s timeout_seconds=%s",
                            ticker,
                            ibkr_price_timeout_seconds,
                        )
                    except Exception as e:
                        ibkr_price_log = "N/A (request_failed)"
                        logger.warning("ibkr_holding_price_fetch_failed symbol=%s error=%s", ticker, str(e))
                else:
                    stock_df = _load_price_history(holding.ticker)
                    if stock_df is not None and not stock_df.empty:
                        latest_row = stock_df.iloc[-1]
                        price_data = float(latest_row.get('close', 0))
                        volume_data = float(latest_row.get('volume', 0))
                        ibkr_price_log = f"N/A (not_connected; cache_rows={len(stock_df)})"

                # 从 Futu 获取 IV 数据（可选）
                iv30 = None
                iv7 = None
                iv60 = None
                iv90 = None
                total_oi = None
                oi_bucket_0_7 = None
                oi_bucket_8_30 = None
                oi_bucket_31_90 = None
                call_oi_bucket_0_7 = None
                call_oi_bucket_8_30 = None
                call_oi_bucket_31_90 = None
                put_oi_bucket_0_7 = None
                put_oi_bucket_8_30 = None
                put_oi_bucket_31_90 = None
                futu_failed = False
                if futu_iv_task is not None:
                    iv_results = await asyncio.shield(futu_iv_task)
                    iv_data = iv_results.get(ticker)
                    if iv_data is not None and iv_data.is_valid():
                        iv30 = iv_data.iv30
                        iv7 = iv_data.iv7
                        iv60 = iv_data.iv60
                        iv90 = iv_data.iv90
                        total_oi = iv_data.total_oi
                        oi_bucket_0_7 = iv_data.oi_bucket_0_7
                        oi_bucket_8_30 = iv_data.oi_bucket_8_30
                        oi_bucket_31_90 = iv_data.oi_bucket_31_90
                        call_oi_bucket_0_7 = getattr(iv_data, 'call_oi_bucket_0_7', None)
                        call_oi_bucket_8_30 = getattr(iv_data, 'call_oi_bucket_8_30', None)
                        call_oi_bucket_31_90 = getattr(iv_data, 'call_oi_bucket_31_90', None)
                        put_oi_bucket_0_7 = getattr(iv_data, 'put_oi_bucket_0_7', None)
                        put_oi_bucket_8_30 = getattr(iv_data, 'put_oi_bucket_8_30', None)
                        put_oi_bucket_31_90 = getattr(iv_data, 'put_oi_bucket_31_90', None)
                        data_sources.append('futu')
                    else:
                        futu_failed = True

                data_sources = list(dict.fromkeys(data_sources))

                # 构建持仓数据字典用于完整度评估
                holding_data = {
                    'price_data': price_data,
                    'volume': volume_data,
                    'change_1d': change_1d,
                    'iv30': iv30,
                    'data_sources': data_sources,
                    'updated_at': _utc_now_iso()
                }

                return {
                    "ticker": holding.ticker,
                    "weight": holding.weight,
                    "price": price_data,
                    "change_1d": change_1d,
                    "data_sources": data_sources,
                    "iv7": iv7,
                    "iv30": iv30,
                    "iv60": iv60,
                    "iv90": iv90,
                    "total_oi": total_oi,
                    "oi_bucket_0_7": oi_bucket_0_7,
                    "oi_bucket_8_30": oi_bucket_8_30,
                    "oi_bucket_31_90": oi_bucket_31_90,
                    "call_oi_bucket_0_7": call_oi_bucket_0_7,
                    "call_oi_bucket_8_30": call_oi_bucket_8_30,
                    "call_oi_bucket_31_90": call_oi_bucket_31_90,
                    "put_oi_bucket_0_7": put_oi_bucket_0_7,
                    "put_oi_bucket_8_30": put_oi_bucket_8_30,
                    "put_oi_bucket_31_90": put_oi_bucket_31_90,
                    "price_df": stock_df,
                    "holding_data": holding_data,
                    "updated_at": _utc_now_iso(),
                    "_log_idx": idx,
                    "_log_total": total_count,
                    "_log_ibkr": ibkr_price_log,
                    "_futu_failed": futu_failed,
                }

            except Exception as e:
                logger.error(f"Error fetching data for {holding.ticker}: {e}")
                return {
                    "ticker": holding.ticker,
                    "weight": holding.weight,
                    "price": None,
                    "change_1d": None,
                    "data_sources": [],
                    "iv7": None,
                    "iv30": None,
                    "iv60": None,
                    "iv90": None,
                    "total_oi": None,
                    "oi_bucket_0_7": None,
                    "oi_bucket_8_30": None,
                    "oi_bucket_31_90": None,
                    "call_oi_bucket_0_7": None,
                    "call_oi_bucket_8_30": None,
                    "call_oi_bucket_31_90": None,
                    "put_oi_bucket_0_7": None,
                    "put_oi_bucket_8_30": None,
                    "put_oi_bucket_31_90": None,
                    "holding_data": {
                        'price_data': None,
                        'volume': None,
                        'change_1d': None,
                        'iv30': None,
                        'data_sources': [],
                        'updated_at': _utc_now_iso()
                    },
                    "updated_at": _utc_now_iso(),
                    "_log_idx": idx,
                    "_log_total": total_count,
                    "_log_ibkr": "N/A (fetch_failed)",
                    "_futu_failed": False,
                }

    # 并发获取所有股票数据（按完成顺序处理，便于前端实时读取进度）
    fetch_tasks = [
        asyncio.create_task(fetch_stock_data(h, idx, max(1, refresh_targets_count)))
        for idx, h in enumerate(holdings_to_refresh, start=1)
    ]

    futu_failed_count = 0

    for future in asyncio.as_completed(fetch_tasks):
        try:
            result = await future
        except Exception as exc:
            progress_completed += 1
            progress_failed += 1
            logger.error("refresh_holdings_task_failed symbol=%s error=%s", symbol.upper(), str(exc))
            if progress_token:
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "completed": progress_completed,
                        "failed": progress_failed,
                        "message": f"处理异常，已完成 {progress_completed}/{total_targets}",
                    },
                )
            continue

        if isinstance(result, dict):
            holding_data = result.pop('holding_data', {})
            price_df = result.pop('price_df', None)
            ticker_text = str(result.get('ticker') or '').upper()
            log_idx = int(result.pop('_log_idx', 0) or 0)
            log_total = int(result.pop('_log_total', total_targets) or total_targets)
            ibkr_price_log = str(result.pop('_log_ibkr', 'N/A'))
            futu_failed_flag = bool(result.pop('_futu_failed', False))
            if futu_failed_flag:
                futu_failed_count += 1
            if progress_token:
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "current_item": ticker_text,
                        "message": f"正在计算 {ticker_text} 的评分...",
                    },
                )

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
            data_sources_list = result.get('data_sources') or []

            # 即使 IBKR 价格缺失，也应持久化已抓取的 Futu IV，避免前端静默重拉后回退为“缺失”。
            if 'futu' in data_sources_list:
                today = date.today()
                ticker_upper = str(result['ticker']).upper()
                total_oi_int = _as_int(result.get('total_oi'))
                bucket_totals = _extract_bucket_totals(result)
                delta_payload = _compute_bucket_delta_payload(
                    ticker=ticker_upper,
                    today=today,
                    bucket_totals=bucket_totals,
                    total_oi_value=total_oi_int,
                )

                for suffix in ("0_7", "8_30", "31_90"):
                    result[f"oi_bucket_{suffix}"] = bucket_totals[suffix]["net"]
                    result[f"call_oi_bucket_{suffix}"] = bucket_totals[suffix]["call"]
                    result[f"put_oi_bucket_{suffix}"] = bucket_totals[suffix]["put"]
                    result[f"net_delta_oi_{suffix}"] = delta_payload["by_bucket"][suffix]["net_1d"]
                    result[f"call_delta_oi_{suffix}"] = delta_payload["by_bucket"][suffix]["call_1d"]
                    result[f"put_delta_oi_{suffix}"] = delta_payload["by_bucket"][suffix]["put_1d"]
                    result[f"net_delta3d_{suffix}"] = delta_payload["by_bucket"][suffix]["net_3d"]
                    result[f"net_delta5d_{suffix}"] = delta_payload["by_bucket"][suffix]["net_5d"]
                result["delta_oi_1d"] = delta_payload.get("total_oi_1d")

                existing_iv = db.query(IVData).filter(
                    IVData.symbol == ticker_upper,
                    IVData.date == today,
                ).first()
                if existing_iv:
                    existing_iv.iv7 = result.get('iv7')
                    existing_iv.iv30 = result.get('iv30')
                    existing_iv.iv60 = result.get('iv60')
                    existing_iv.iv90 = result.get('iv90')
                    existing_iv.total_oi = result.get('total_oi')
                    existing_iv.delta_oi_1d = result.get('delta_oi_1d')
                    existing_iv.oi_bucket_0_7 = result.get('oi_bucket_0_7')
                    existing_iv.oi_bucket_8_30 = result.get('oi_bucket_8_30')
                    existing_iv.oi_bucket_31_90 = result.get('oi_bucket_31_90')
                    existing_iv.call_oi_bucket_0_7 = result.get('call_oi_bucket_0_7')
                    existing_iv.call_oi_bucket_8_30 = result.get('call_oi_bucket_8_30')
                    existing_iv.call_oi_bucket_31_90 = result.get('call_oi_bucket_31_90')
                    existing_iv.put_oi_bucket_0_7 = result.get('put_oi_bucket_0_7')
                    existing_iv.put_oi_bucket_8_30 = result.get('put_oi_bucket_8_30')
                    existing_iv.put_oi_bucket_31_90 = result.get('put_oi_bucket_31_90')
                    existing_iv.net_delta_oi_0_7 = result.get('net_delta_oi_0_7')
                    existing_iv.net_delta_oi_8_30 = result.get('net_delta_oi_8_30')
                    existing_iv.net_delta_oi_31_90 = result.get('net_delta_oi_31_90')
                    existing_iv.call_delta_oi_0_7 = result.get('call_delta_oi_0_7')
                    existing_iv.call_delta_oi_8_30 = result.get('call_delta_oi_8_30')
                    existing_iv.call_delta_oi_31_90 = result.get('call_delta_oi_31_90')
                    existing_iv.put_delta_oi_0_7 = result.get('put_delta_oi_0_7')
                    existing_iv.put_delta_oi_8_30 = result.get('put_delta_oi_8_30')
                    existing_iv.put_delta_oi_31_90 = result.get('put_delta_oi_31_90')
                    existing_iv.source = 'futu'
                    existing_iv.created_at = datetime.utcnow()
                else:
                    db.add(IVData(
                        symbol=ticker_upper,
                        date=today,
                        iv7=result.get('iv7'),
                        iv30=result.get('iv30'),
                        iv60=result.get('iv60'),
                        iv90=result.get('iv90'),
                        total_oi=result.get('total_oi'),
                        delta_oi_1d=result.get('delta_oi_1d'),
                        oi_bucket_0_7=result.get('oi_bucket_0_7'),
                        oi_bucket_8_30=result.get('oi_bucket_8_30'),
                        oi_bucket_31_90=result.get('oi_bucket_31_90'),
                        call_oi_bucket_0_7=result.get('call_oi_bucket_0_7'),
                        call_oi_bucket_8_30=result.get('call_oi_bucket_8_30'),
                        call_oi_bucket_31_90=result.get('call_oi_bucket_31_90'),
                        put_oi_bucket_0_7=result.get('put_oi_bucket_0_7'),
                        put_oi_bucket_8_30=result.get('put_oi_bucket_8_30'),
                        put_oi_bucket_31_90=result.get('put_oi_bucket_31_90'),
                        net_delta_oi_0_7=result.get('net_delta_oi_0_7'),
                        net_delta_oi_8_30=result.get('net_delta_oi_8_30'),
                        net_delta_oi_31_90=result.get('net_delta_oi_31_90'),
                        call_delta_oi_0_7=result.get('call_delta_oi_0_7'),
                        call_delta_oi_8_30=result.get('call_delta_oi_8_30'),
                        call_delta_oi_31_90=result.get('call_delta_oi_31_90'),
                        put_delta_oi_0_7=result.get('put_delta_oi_0_7'),
                        put_delta_oi_8_30=result.get('put_delta_oi_8_30'),
                        put_delta_oi_31_90=result.get('put_delta_oi_31_90'),
                        source='futu',
                    ))

            if price_df is None:
                price_df = _load_price_history(result['ticker'])

            if price_df is not None and not price_df.empty:
                if 'ibkr' in data_sources_list:
                    _save_price_history(result['ticker'], price_df)

                finviz_data = _get_imported(result['ticker'], 'finviz')
                mc_data = _get_imported(result['ticker'], 'marketchameleon')
                iv_data = _get_latest_iv(result['ticker'])

                pool_payload = await orchestrator.calculate_momentum_pool_score(
                    symbol=result['ticker'],
                    sector_etf=sector_symbol,
                    finviz_data=finviz_data,
                    mc_data=mc_data,
                    iv_data=iv_data,
                    duration='1 Y',
                )

                if pool_payload and pool_payload.get('total_score') is not None:
                    score_value = pool_payload.get('total_score')
                    pool_scores = pool_payload.get('scores') or {}
                    pool_metrics = pool_payload.get('metrics') or {}
                    extra_metrics: Dict[str, Any] = {}

                    def _to_float(value: Any) -> Optional[float]:
                        try:
                            return float(value) if value is not None else None
                        except (TypeError, ValueError):
                            return None

                    if result.get('iv7') is not None:
                        extra_metrics['iv7'] = _to_float(result.get('iv7'))
                    if result.get('iv30') is not None:
                        extra_metrics['iv30'] = _to_float(result.get('iv30'))
                    if result.get('iv60') is not None:
                        extra_metrics['iv60'] = _to_float(result.get('iv60'))
                    if result.get('iv90') is not None:
                        extra_metrics['iv90'] = _to_float(result.get('iv90'))
                    if result.get('total_oi') is not None:
                        extra_metrics['openInterest'] = result.get('total_oi')

                    bucket_payload = [
                        {
                            'suffix': '0_7',
                            'label': '0-7',
                            'net_total': _to_float(result.get('oi_bucket_0_7')),
                            'call_total': _to_float(result.get('call_oi_bucket_0_7')),
                            'put_total': _to_float(result.get('put_oi_bucket_0_7')),
                            'net_delta_1d': _to_float(result.get('net_delta_oi_0_7')),
                            'call_delta_1d': _to_float(result.get('call_delta_oi_0_7')),
                            'put_delta_1d': _to_float(result.get('put_delta_oi_0_7')),
                            'net_delta_3d': _to_float(result.get('net_delta3d_0_7')),
                            'net_delta_5d': _to_float(result.get('net_delta5d_0_7')),
                        },
                        {
                            'suffix': '8_30',
                            'label': '8-30',
                            'net_total': _to_float(result.get('oi_bucket_8_30')),
                            'call_total': _to_float(result.get('call_oi_bucket_8_30')),
                            'put_total': _to_float(result.get('put_oi_bucket_8_30')),
                            'net_delta_1d': _to_float(result.get('net_delta_oi_8_30')),
                            'call_delta_1d': _to_float(result.get('call_delta_oi_8_30')),
                            'put_delta_1d': _to_float(result.get('put_delta_oi_8_30')),
                            'net_delta_3d': _to_float(result.get('net_delta3d_8_30')),
                            'net_delta_5d': _to_float(result.get('net_delta5d_8_30')),
                        },
                        {
                            'suffix': '31_90',
                            'label': '31-90',
                            'net_total': _to_float(result.get('oi_bucket_31_90')),
                            'call_total': _to_float(result.get('call_oi_bucket_31_90')),
                            'put_total': _to_float(result.get('put_oi_bucket_31_90')),
                            'net_delta_1d': _to_float(result.get('net_delta_oi_31_90')),
                            'call_delta_1d': _to_float(result.get('call_delta_oi_31_90')),
                            'put_delta_1d': _to_float(result.get('put_delta_oi_31_90')),
                            'net_delta_3d': _to_float(result.get('net_delta3d_31_90')),
                            'net_delta_5d': _to_float(result.get('net_delta5d_31_90')),
                        },
                    ]
                    options_positioning = []
                    for bucket in bucket_payload:
                        bucket_net_total = bucket['net_total']
                        bucket_call_total = bucket['call_total']
                        bucket_put_total = bucket['put_total']
                        bucket_net_1d = bucket['net_delta_1d']
                        bucket_call_1d = bucket['call_delta_1d']
                        bucket_put_1d = bucket['put_delta_1d']
                        bucket_net_3d = bucket['net_delta_3d']
                        bucket_net_5d = bucket['net_delta_5d']

                        if bucket_net_total is None and bucket_call_total is not None and bucket_put_total is not None:
                            bucket_net_total = bucket_call_total + bucket_put_total
                        if bucket_net_1d is None and bucket_call_1d is not None and bucket_put_1d is not None:
                            bucket_net_1d = bucket_call_1d - bucket_put_1d

                        if all(
                            value is None
                            for value in (
                                bucket_net_total, bucket_call_total, bucket_put_total,
                                bucket_net_1d, bucket_call_1d, bucket_put_1d,
                                bucket_net_3d, bucket_net_5d,
                            )
                        ):
                            continue

                        if bucket_net_total is not None:
                            extra_metrics[f"oi_bucket_{bucket['suffix']}"] = bucket_net_total
                        if bucket_call_total is not None:
                            extra_metrics[f"call_oi_{bucket['suffix']}"] = bucket_call_total
                        if bucket_put_total is not None:
                            extra_metrics[f"put_oi_{bucket['suffix']}"] = bucket_put_total
                        if bucket_net_1d is not None:
                            extra_metrics[f"net_delta_oi_{bucket['suffix']}"] = bucket_net_1d
                            extra_metrics[f"delta_oi_{bucket['suffix']}"] = bucket_net_1d
                        if bucket_call_1d is not None:
                            extra_metrics[f"call_delta_oi_{bucket['suffix']}"] = bucket_call_1d
                        if bucket_put_1d is not None:
                            extra_metrics[f"put_delta_oi_{bucket['suffix']}"] = bucket_put_1d
                        if bucket_net_3d is not None:
                            extra_metrics[f"net_delta3d_{bucket['suffix']}"] = bucket_net_3d
                            extra_metrics[f"delta3d_{bucket['suffix']}"] = bucket_net_3d
                        if bucket_net_5d is not None:
                            extra_metrics[f"net_delta5d_{bucket['suffix']}"] = bucket_net_5d
                            extra_metrics[f"delta5d_{bucket['suffix']}"] = bucket_net_5d

                        trend = '中性'
                        trend_ref = bucket_net_1d
                        if trend_ref is None and bucket_call_1d is not None and bucket_put_1d is not None:
                            trend_ref = bucket_call_1d - bucket_put_1d
                        if trend_ref is None:
                            trend_ref = bucket_net_3d
                        if trend_ref is not None:
                            trend = '偏多' if trend_ref >= 0 else '偏空'

                        options_positioning.append({
                            'bucket': bucket['label'],
                            'callOI': bucket_call_1d,
                            'putOI': bucket_put_1d,
                            'netOI': bucket_net_1d,
                            'delta3d': bucket_net_3d,
                            'delta5d': bucket_net_5d,
                            'trend': trend,
                        })
                    if options_positioning:
                        extra_metrics['optionsPositioning'] = options_positioning

                    if mc_data:
                        mc_rel_notional = _to_float(
                            mc_data.get('rel_notional')
                            if mc_data.get('rel_notional') is not None
                            else mc_data.get('rel_notional_to_90d')
                        )
                        mc_rel_volume = _to_float(
                            mc_data.get('rel_vol')
                            if mc_data.get('rel_vol') is not None
                            else mc_data.get('rel_vol_to_90d')
                        )
                        mc_iv30_change = _to_float(
                            mc_data.get('iv30_chg_pct')
                            if mc_data.get('iv30_chg_pct') is not None
                            else mc_data.get('iv_change')
                        )
                        if mc_data.get('heat_score') is not None:
                            extra_metrics['heat_score'] = _to_float(mc_data.get('heat_score'))
                        if mc_data.get('risk_score') is not None:
                            extra_metrics['risk_score'] = _to_float(mc_data.get('risk_score'))
                        if mc_rel_notional is not None:
                            extra_metrics['rel_notional'] = mc_rel_notional
                            extra_metrics['rel_notional_to_90d'] = mc_rel_notional
                        if mc_rel_volume is not None:
                            extra_metrics['rel_vol'] = mc_rel_volume
                            extra_metrics['rel_vol_to_90d'] = mc_rel_volume
                        if mc_data.get('trade_count') is not None:
                            extra_metrics['trade_count'] = mc_data.get('trade_count')
                        if mc_iv30_change is not None:
                            extra_metrics['iv_change'] = mc_iv30_change
                            extra_metrics['iv30_chg_pct'] = mc_iv30_change

                    merged_metrics = dict(pool_metrics)
                    for metric_key, metric_value in extra_metrics.items():
                        if metric_value is None:
                            continue
                        merged_metrics[metric_key] = metric_value

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
                    stock.score_total = score_value
                    stock.scores = pool_scores
                    stock.metrics = merged_metrics
                    db.add(stock)
                    db.flush()

                    today = date.today()
                    existing_snapshot = db.query(ScoreSnapshot).filter(
                        ScoreSnapshot.symbol == stock.symbol,
                        ScoreSnapshot.symbol_type == 'stock',
                        ScoreSnapshot.date == today
                    ).first()
                    snapshot_payload = {
                        'scores': pool_scores,
                        'metrics': pool_metrics
                    }
                    thresholds_pass = (pool_scores.get('momentum', 0) >= 50 and pool_scores.get('trend', 0) >= 50)
                    stock.thresholds_pass = thresholds_pass
                    if mc_data:
                        try:
                            mc_heat_score = _to_float(mc_data.get('heat_score'))
                            if mc_heat_score is not None:
                                stock.heat_score = mc_heat_score
                            mc_risk_score = _to_float(mc_data.get('risk_score'))
                            if mc_risk_score is not None:
                                stock.risk_score = mc_risk_score
                            mc_heat_type = mc_data.get('heat_type')
                            if isinstance(mc_heat_type, str) and mc_heat_type.strip():
                                stock.heat_type = normalize_heat_type(mc_heat_type)
                        except Exception:
                            pass
                    if existing_snapshot:
                        existing_snapshot.total_score = score_value
                        existing_snapshot.score_breakdown = snapshot_payload
                        existing_snapshot.thresholds_pass = thresholds_pass
                    else:
                        db.add(ScoreSnapshot(
                            symbol=stock.symbol,
                            symbol_type='stock',
                            date=today,
                            total_score=score_value,
                            score_breakdown=snapshot_payload,
                            thresholds_pass=thresholds_pass
                        ))

                    stock.changes = _compute_deltas(stock.symbol)

            result['score'] = score_value

            total_oi_raw = result.get("total_oi")
            total_oi_text = (
                str(int(total_oi_raw))
                if isinstance(total_oi_raw, (int, float)) and total_oi_raw is not None
                else "N/A"
            )
            oi_0_7_raw = result.get("oi_bucket_0_7")
            oi_8_30_raw = result.get("oi_bucket_8_30")
            oi_31_90_raw = result.get("oi_bucket_31_90")
            oi_0_7_text = str(int(oi_0_7_raw)) if isinstance(oi_0_7_raw, (int, float)) else "N/A"
            oi_8_30_text = str(int(oi_8_30_raw)) if isinstance(oi_8_30_raw, (int, float)) else "N/A"
            oi_31_90_text = str(int(oi_31_90_raw)) if isinstance(oi_31_90_raw, (int, float)) else "N/A"
            logger.info(
                "\n".join(
                    [
                        f"HOLDINGS- [{log_idx}/{max(log_total, 1)}] {ticker_text}",
                        f" - OHLCV(1Y): {ibkr_price_log}",
                        (
                            " - IV7/30/60/90: "
                            f"{_fmt_float(result.get('iv7'), 2)}% / "
                            f"{_fmt_float(result.get('iv30'), 2)}% / "
                            f"{_fmt_float(result.get('iv60'), 2)}% / "
                            f"{_fmt_float(result.get('iv90'), 2)}%"
                        ),
                        (
                            f"-  Δ OI: {total_oi_text} "
                            f"(0-7D: {oi_0_7_text}, 8-30D: {oi_8_30_text}, 31-90D: {oi_31_90_text})"
                        ),
                        "---",
                    ]
                )
            )

            updated_stocks.append(result)
            progress_completed += 1
            if progress_token:
                ticker_text = str(result.get('ticker') or '').upper()
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "completed": progress_completed,
                        "failed": progress_failed,
                        "current_item": ticker_text,
                        "message": f"已完成 {progress_completed}/{total_targets}",
                    },
                )
        else:
            progress_completed += 1
            progress_failed += 1
            if progress_token:
                _patch_holdings_refresh_progress(
                    progress_token,
                    {
                        "completed": progress_completed,
                        "failed": progress_failed,
                        "message": f"处理异常，已完成 {progress_completed}/{total_targets}",
                    },
                )

    if futu_iv_task is not None:
        await asyncio.gather(futu_iv_task, return_exceptions=True)

    db.commit()
    _recalculate_etf_score_from_db(etf, db)

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

    total_weight = sum(h.weight for h in filtered_holdings)
    refreshed_count = len(holdings_to_refresh)
    if has_related_etf_scope:
        final_message = (
            f"覆盖 {len(filtered_holdings)} 只持仓：同任务重复标的 {duplicate_scope_count} 只，"
            f"刷新 {refreshed_count} 只，跳过 {skipped_recent_count} 只（{HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟冷却），"
            f"平均完备度 {round(coverage_completeness.average_completeness, 1)}%"
        )
    else:
        final_message = (
            f"覆盖 {len(filtered_holdings)} 只持仓：刷新 {refreshed_count} 只，"
            f"跳过 {skipped_recent_count} 只（{HOLDINGS_REFRESH_COOLDOWN_MINUTES} 分钟内已有市场+期权数据），"
            f"平均完备度 {round(coverage_completeness.average_completeness, 1)}%"
        )
    if futu_failed_count > 0:
        final_message += f"（Futu 期权数据部分缺失 {futu_failed_count} 只）"

    if progress_token:
        _patch_holdings_refresh_progress(
            progress_token,
            {
                "status": "completed",
                "completed": len(filtered_holdings),
                "failed": progress_failed,
                "current_item": "",
                "message": final_message,
                "finished_at": _utc_now_iso(),
            },
        )

    return {
        "status": "success",
        "symbol": symbol.upper(),
        "coverage": coverage_label,
        "stocks_count": len(filtered_holdings),
        "refreshed_stocks_count": refreshed_count,
        "skipped_recent_count": skipped_recent_count,
        "duplicate_scope_count": duplicate_scope_count,
        "total_weight": round(total_weight, 2),
        "futu_failed_count": futu_failed_count,
        "completeness": coverage_completeness.to_dict(),
        "updated_stocks": updated_stocks,
        "updated_at": _utc_now_iso(),
        "message": final_message
    }
