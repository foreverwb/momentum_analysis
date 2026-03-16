from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - runtime fallback only
    ZoneInfo = None  # type: ignore[assignment]


BEIJING_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo is not None else timezone(timedelta(hours=8))
UTC = timezone.utc


def _ensure_utc_datetime(value: Optional[datetime] = None) -> datetime:
    candidate = value or datetime.now(UTC)
    if candidate.tzinfo is None:
        return candidate.replace(tzinfo=UTC)
    return candidate.astimezone(UTC)


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc_isoformat(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _ensure_utc_datetime(value).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def beijing_now(now_utc: Optional[datetime] = None) -> datetime:
    return _ensure_utc_datetime(now_utc).astimezone(BEIJING_TZ)


def beijing_today(now_utc: Optional[datetime] = None) -> date:
    return beijing_now(now_utc).date()


def format_beijing_datetime(
    value: Optional[datetime],
    fmt: str = "%Y-%m-%d %H:%M",
) -> Optional[str]:
    if value is None:
        return None
    return beijing_now(value).strftime(fmt)


def format_beijing_date(value: Optional[datetime], fmt: str = "%Y-%m-%d") -> Optional[str]:
    if value is None:
        return None
    return beijing_now(value).strftime(fmt)


def get_beijing_cutoff_boundary(
    now_utc: Optional[datetime] = None,
    *,
    cutoff_hour: int = 8,
) -> Dict[str, Any]:
    now_beijing = beijing_now(now_utc)
    boundary_beijing = now_beijing.replace(
        hour=cutoff_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now_beijing < boundary_beijing:
        boundary_beijing -= timedelta(days=1)
    boundary_utc = boundary_beijing.astimezone(UTC).replace(tzinfo=None)
    return {
        "boundary_utc": boundary_utc,
        "boundary_beijing": boundary_beijing,
        "boundary_date": boundary_beijing.date(),
        "sync_date": boundary_beijing.date().isoformat(),
    }
