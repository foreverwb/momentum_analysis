from __future__ import annotations

from datetime import date as date_type, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import PriceHistory, ScoreSnapshot, Stock, ETF

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - runtime fallback only
    ZoneInfo = None  # type: ignore[assignment]


def _coerce_to_date(value: Any) -> Optional[date_type]:
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
        head = text[:10]
        try:
            return datetime.fromisoformat(head).date()
        except ValueError:
            return None
    return None


def resolve_latest_trade_date(source: Any, fallback: Optional[date_type] = None) -> Optional[date_type]:
    if source is None:
        return fallback

    candidate_source = source
    if not isinstance(source, (str, bytes, datetime, date_type)):
        try:
            candidate_source = source["date"]
        except Exception:
            candidate_source = source

    try:
        candidates = list(candidate_source)
    except TypeError:
        candidates = [candidate_source]

    for value in reversed(candidates):
        parsed = _coerce_to_date(value)
        if parsed is not None:
            return parsed

    return fallback


def _to_beijing_trade_label(trade_date: date_type) -> date_type:
    # Daily bars are US RTH trade dates; map NY close-date label to Beijing calendar date.
    if ZoneInfo is None:
        return trade_date + timedelta(days=1)
    ny_close = datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        16,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    return ny_close.astimezone(ZoneInfo("Asia/Shanghai")).date()


def _normalize_label_timezone(label_tz: str) -> str:
    normalized = (label_tz or "beijing").strip().lower()
    return "market" if normalized == "market" else "beijing"


def _load_price_map(db: Session, symbol: str, limit: int) -> Dict[Any, float]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.symbol == symbol.upper())
        .order_by(PriceHistory.date.desc())
        .limit(limit)
        .all()
    )
    price_map: Dict[Any, float] = {}
    for row in rows:
        if row.close is None:
            continue
        price_map[row.date] = float(row.close)
    return price_map


def _load_price_series(db: Session, symbol: str, limit: int) -> List[Tuple[Any, float]]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.symbol == symbol.upper())
        .order_by(PriceHistory.date.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    series: List[Tuple[Any, float]] = []
    for row in rows:
        if row.close is None:
            continue
        series.append((row.date, float(row.close)))
    return series


def _format_date_labels(dates: List[Any], label_tz: str = "beijing") -> List[str]:
    tz_mode = _normalize_label_timezone(label_tz)
    labels: List[str] = []
    for value in dates:
        parsed = _coerce_to_date(value)
        if parsed is None:
            labels.append(str(value))
            continue
        display_date = _to_beijing_trade_label(parsed) if tz_mode == "beijing" else parsed
        labels.append(f"{display_date.month}/{display_date.day}")
    return labels


def _resolve_symbol_types(db: Session, symbols: List[str]) -> Dict[str, str]:
    if not symbols:
        return {}
    etf_symbols = {
        row[0] for row in db.query(ETF.symbol).filter(ETF.symbol.in_(symbols)).all()
    }
    stock_symbols = {
        row[0] for row in db.query(Stock.symbol).filter(Stock.symbol.in_(symbols)).all()
    }
    mapping: Dict[str, str] = {}
    for symbol in symbols:
        if symbol in etf_symbols:
            mapping[symbol] = "etf"
        elif symbol in stock_symbols:
            mapping[symbol] = "stock"
    return mapping


def _build_price_metric_series(
    db: Session,
    symbols: List[str],
    period: int,
    metric: str,
    extra_buffer: int,
    label_tz: str = "beijing",
) -> Tuple[List[str], List[Dict[str, Any]]]:
    series_data: Dict[str, Dict[Any, float]] = {}
    limit = period + extra_buffer

    for symbol in symbols:
        rows = _load_price_series(db, symbol, limit)
        if not rows:
            series_data[symbol] = {}
            continue

        dates = [item[0] for item in rows]
        closes = [item[1] for item in rows]

        if metric == "sma20":
            data_map: Dict[Any, float] = {}
            if len(closes) >= 20:
                for idx in range(19, len(closes)):
                    window = closes[idx - 19: idx + 1]
                    data_map[dates[idx]] = round(sum(window) / 20, 2)
            series_data[symbol] = data_map
        elif metric == "return20d":
            data_map = {}
            if len(closes) >= 21:
                for idx in range(20, len(closes)):
                    base = closes[idx - 20]
                    if base == 0:
                        continue
                    data_map[dates[idx]] = round((closes[idx] - base) / base * 100, 2)
            series_data[symbol] = data_map
        else:
            series_data[symbol] = {date: close for date, close in rows}

    all_dates = sorted({date for data in series_data.values() for date in data.keys()})
    if len(all_dates) > period:
        all_dates = all_dates[-period:]

    date_labels = _format_date_labels(all_dates, label_tz=label_tz)
    series: List[Dict[str, Any]] = []

    for symbol in symbols:
        data_map = series_data.get(symbol, {})
        values: List[Optional[float]] = []
        if metric == "relative":
            base_value = None
            for date in all_dates:
                if date in data_map:
                    base_value = data_map[date]
                    break
            for date in all_dates:
                close = data_map.get(date)
                if base_value is None or close is None or base_value == 0:
                    values.append(None)
                else:
                    values.append(round((close - base_value) / base_value * 100, 2))
        else:
            for date in all_dates:
                value = data_map.get(date)
                values.append(value if value is not None else None)

        series.append({"symbol": symbol, "values": values})

    return date_labels, series


def _build_score_series(
    db: Session,
    symbols: List[str],
    period: int,
    label_tz: str = "beijing",
) -> Tuple[List[str], List[Dict[str, Any]]]:
    type_map = _resolve_symbol_types(db, symbols)
    data_map: Dict[str, Dict[Any, float]] = {symbol: {} for symbol in symbols}
    latest_price_dates: Dict[str, date_type] = {}

    latest_price_rows = (
        db.query(
            PriceHistory.symbol,
            func.max(PriceHistory.date).label("latest_date"),
        )
        .filter(PriceHistory.symbol.in_(symbols))
        .group_by(PriceHistory.symbol)
        .all()
    )
    for row in latest_price_rows:
        symbol = str(row.symbol or "").upper().strip()
        latest_date = _coerce_to_date(row.latest_date)
        if symbol and latest_date is not None:
            latest_price_dates[symbol] = latest_date

    price_dates = {
        parsed
        for (raw_date,) in (
            db.query(PriceHistory.date)
            .filter(PriceHistory.symbol.in_(symbols))
            .distinct()
            .all()
        )
        if (parsed := _coerce_to_date(raw_date)) is not None
    }
    score_dates: set[date_type] = set()

    rows = (
        db.query(ScoreSnapshot)
        .filter(ScoreSnapshot.symbol.in_(symbols))
        .order_by(ScoreSnapshot.date.asc())
        .all()
    )

    for row in rows:
        if row.total_score is None:
            continue
        symbol = str(row.symbol or "").upper().strip()
        if not symbol:
            continue
        symbol_type = type_map.get(symbol)
        if symbol_type and row.symbol_type and row.symbol_type != symbol_type:
            continue
        row_date = _coerce_to_date(row.date)
        if row_date is None:
            continue
        latest_price_date = latest_price_dates.get(symbol)
        if latest_price_date is not None and row_date > latest_price_date:
            row_date = latest_price_date
        data_map.setdefault(symbol, {})[row_date] = float(row.total_score)
        score_dates.add(row_date)

    all_dates = sorted(price_dates | score_dates)
    if len(all_dates) > period:
        all_dates = all_dates[-period:]

    date_labels = _format_date_labels(all_dates, label_tz=label_tz)
    series: List[Dict[str, Any]] = []

    for symbol in symbols:
        score_items = sorted(data_map.get(symbol, {}).items())
        next_index = 0
        last_value: Optional[float] = None
        values: List[Optional[float]] = []
        for current_date in all_dates:
            while next_index < len(score_items) and score_items[next_index][0] <= current_date:
                last_value = score_items[next_index][1]
                next_index += 1
            values.append(last_value if last_value is not None else None)
        series.append({"symbol": symbol, "values": values})

    return date_labels, series


def build_relative_series(
    db: Session,
    symbols: List[str],
    period: int,
    extra_buffer: int = 10,
    label_tz: str = "beijing",
) -> Tuple[List[str], List[Dict[str, Any]]]:
    return build_metric_series(
        db,
        symbols,
        period,
        metric="relative",
        extra_buffer=extra_buffer,
        label_tz=label_tz,
    )


def build_sma20_comparison_series(
    db: Session,
    symbols: List[str],
    period: int,
    extra_buffer: int = 30,
    label_tz: str = "beijing",
) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    cleaned = [s.upper() for s in symbols if s]
    if not cleaned or period <= 1:
        return [], [], [], []

    limit = period + max(extra_buffer, 30)
    close_maps: Dict[str, Dict[Any, float]] = {}
    sma_maps: Dict[str, Dict[Any, float]] = {}

    for symbol in cleaned:
        rows = _load_price_series(db, symbol, limit)
        close_map: Dict[Any, float] = {}
        sma_map: Dict[Any, float] = {}
        if rows:
            dates = [item[0] for item in rows]
            closes = [item[1] for item in rows]
            close_map = {date: close for date, close in rows}
            if len(closes) >= 20:
                for idx in range(19, len(closes)):
                    window = closes[idx - 19: idx + 1]
                    sma_map[dates[idx]] = round(sum(window) / 20, 2)
        close_maps[symbol] = close_map
        sma_maps[symbol] = sma_map

    all_dates = sorted({date for data in close_maps.values() for date in data.keys()})
    if len(all_dates) > period:
        all_dates = all_dates[-period:]

    date_labels = _format_date_labels(all_dates, label_tz=label_tz)
    price_series: List[Dict[str, Any]] = []
    sma20_series: List[Dict[str, Any]] = []
    deviation_series: List[Dict[str, Any]] = []

    for symbol in cleaned:
        close_map = close_maps.get(symbol, {})
        sma_map = sma_maps.get(symbol, {})
        close_values: List[Optional[float]] = []
        sma_values: List[Optional[float]] = []
        deviation_values: List[Optional[float]] = []

        for date in all_dates:
            close = close_map.get(date)
            sma = sma_map.get(date)
            close_values.append(round(close, 2) if close is not None else None)
            sma_values.append(round(sma, 2) if sma is not None else None)
            if close is None or sma is None or sma == 0:
                deviation_values.append(None)
            else:
                deviation_values.append(round((close - sma) / sma * 100, 2))

        price_series.append({"symbol": symbol, "values": close_values})
        sma20_series.append({"symbol": symbol, "values": sma_values})
        deviation_series.append({"symbol": symbol, "values": deviation_values})

    return date_labels, price_series, sma20_series, deviation_series


def build_metric_series(
    db: Session,
    symbols: List[str],
    period: int,
    metric: str = "relative",
    extra_buffer: int = 30,
    label_tz: str = "beijing",
) -> Tuple[List[str], List[Dict[str, Any]]]:
    cleaned = [s.upper() for s in symbols if s]
    if not cleaned or period <= 1:
        return [], []

    metric_key = metric.lower().strip()
    if metric_key == "score":
        return _build_score_series(db, cleaned, period, label_tz=label_tz)

    if metric_key not in ("relative", "sma20", "return20d"):
        metric_key = "relative"

    return _build_price_metric_series(
        db,
        cleaned,
        period,
        metric_key,
        extra_buffer,
        label_tz=label_tz,
    )
