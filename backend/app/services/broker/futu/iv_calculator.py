"""
Futu IV term and OI/delta-OI calculations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from ....core.paths import resolve_backend_storage_paths
from ....core.time_utils import beijing_today
from .connection import FutuConnection
from .options_data import (
    FUTU_OPTION_CHAIN_MAX_CALLS,
    FUTU_SNAPSHOT_MAX_CALLS,
    FUTU_SNAPSHOT_MAX_CODES_PER_REQUEST,
    FutuOptionsDataFetcher,
    OptionContract,
)
from .utils import OPTION_TYPE

logger = structlog.get_logger(__name__)


@dataclass
class IVTermResult:
    iv7: Optional[float] = None
    iv30: Optional[float] = None
    iv60: Optional[float] = None
    iv90: Optional[float] = None
    total_oi: Optional[int] = None
    risk_total_oi: Optional[int] = None
    oi_bucket_0_7: Optional[int] = None
    oi_bucket_8_30: Optional[int] = None
    oi_bucket_31_90: Optional[int] = None
    risk_oi_bucket_0_7: Optional[int] = None
    risk_oi_bucket_8_30: Optional[int] = None
    risk_oi_bucket_31_90: Optional[int] = None
    call_oi_bucket_0_7: Optional[int] = None
    call_oi_bucket_8_30: Optional[int] = None
    call_oi_bucket_31_90: Optional[int] = None
    put_oi_bucket_0_7: Optional[int] = None
    put_oi_bucket_8_30: Optional[int] = None
    put_oi_bucket_31_90: Optional[int] = None
    delta_oi_1d: Optional[int] = None
    net_delta_oi_0_7: Optional[int] = None
    net_delta_oi_8_30: Optional[int] = None
    net_delta_oi_31_90: Optional[int] = None
    call_delta_oi_0_7: Optional[int] = None
    call_delta_oi_8_30: Optional[int] = None
    call_delta_oi_31_90: Optional[int] = None
    put_delta_oi_0_7: Optional[int] = None
    put_delta_oi_8_30: Optional[int] = None
    put_delta_oi_31_90: Optional[int] = None
    clipped_net_delta_oi_0_7: Optional[int] = None
    clipped_net_delta_oi_8_30: Optional[int] = None
    clipped_net_delta_oi_31_90: Optional[int] = None
    net_delta3d_0_7: Optional[int] = None
    net_delta3d_8_30: Optional[int] = None
    net_delta3d_31_90: Optional[int] = None
    net_delta5d_0_7: Optional[int] = None
    net_delta5d_8_30: Optional[int] = None
    net_delta5d_31_90: Optional[int] = None
    # alias: 与策略层说明文档一致的命名（保留已有 net_delta3d/net_delta5d 字段）
    delta_oi_bucket_0_7_3d: Optional[int] = None
    delta_oi_bucket_8_30_3d: Optional[int] = None
    delta_oi_bucket_31_90_3d: Optional[int] = None
    delta_oi_bucket_0_7_5d: Optional[int] = None
    delta_oi_bucket_8_30_5d: Optional[int] = None
    delta_oi_bucket_31_90_5d: Optional[int] = None
    _snapshot_payload: Optional[Dict[str, Any]] = field(default=None, repr=False, compare=False)
    _fetch_incomplete: bool = field(default=False, repr=False, compare=False)
    _fetch_error: Optional[str] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if not key.startswith("_")
        }

    def is_valid(self) -> bool:
        return any([self.iv7 is not None, self.iv30 is not None, self.iv60 is not None, self.iv90 is not None])


class FutuIVCalculator:
    """Compute IV7/30/60/90 and OI metrics using option-chain snapshots."""

    # Keep OI cache in a dedicated sqlite file to avoid lock contention with main app DB.
    DEFAULT_OI_CACHE_DB_FILE = str(resolve_backend_storage_paths().futu_oi_cache_db)
    CACHE_TABLE = "futu_oi_cache"
    CACHE_LOCK = threading.Lock()
    BUCKET_SUFFIXES = ("0_7", "8_30", "31_90")
    CACHE_RETENTION_DAYS = 60
    CACHE_DB_TIMEOUT_SECONDS = 15
    CACHE_DB_BUSY_TIMEOUT_MS = 12000
    CACHE_SAVE_RETRY_ATTEMPTS = 5

    def __init__(
        self,
        connection: FutuConnection,
        options_fetcher: FutuOptionsDataFetcher,
        oi_cache_file: str = DEFAULT_OI_CACHE_DB_FILE,
    ):
        self.connection = connection
        self.options_fetcher = options_fetcher
        # Keep parameter name for backward compatibility; storage is now SQLite.
        self.oi_cache_db_file = str(oi_cache_file)
        self.oi_cache_file = self.oi_cache_db_file
        set_cache_db_file = getattr(self.options_fetcher, "set_cache_db_file", None)
        if callable(set_cache_db_file):
            set_cache_db_file(self.oi_cache_db_file)
        elif hasattr(self.options_fetcher, "cache_db_file"):
            try:
                setattr(self.options_fetcher, "cache_db_file", self.oi_cache_db_file)
            except Exception:
                pass
        self._ensure_cache_table()

    def fetch_iv_terms(
        self,
        symbols: Iterable[str],
        max_days: int = 120,
        window_days: int = 30,
        max_retries: int = 2,
        progress_total: Optional[int] = None,
        progress_offset: int = 0,
        log_progress: bool = True,
        log_fetch_summary: bool = True,
    ) -> Dict[str, IVTermResult]:
        symbols_list = list(symbols)
        if not symbols_list:
            return {}

        if not self.connection.is_connected():
            if not self.connection.connect():
                logger.warning("futu_fetch_iv_terms_not_connected")
                return {symbol: IVTermResult() for symbol in symbols_list}

        results: Dict[str, IVTermResult] = {}
        total = progress_total if progress_total is not None else len(symbols_list)
        today = beijing_today()
        cache = self._load_oi_cache()
        cache_changed = False
        option_types = self._resolve_option_types()
        symbol_catalogs: Dict[str, Dict[str, List[OptionContract]]] = {}
        symbol_catalog_meta: Dict[str, Any] = {}
        symbol_codes: Dict[str, List[str]] = {}

        for idx, symbol in enumerate(symbols_list, start=1 + progress_offset):
            try:
                expirations, fetch_meta = self._load_symbol_contract_catalog_with_retry(
                    symbol=symbol,
                    max_days=max_days,
                    window_days=window_days,
                    max_retries=max_retries,
                    option_types=option_types,
                    log_fetch_summary=log_fetch_summary,
                )
                symbol_catalogs[symbol] = expirations
                symbol_catalog_meta[symbol] = fetch_meta
                symbol_codes[symbol] = list(
                    dict.fromkeys(
                        contract.code
                        for contracts in expirations.values()
                        for contract in contracts
                        if getattr(contract, "code", None)
                    )
                )
            except Exception as exc:
                logger.warning(
                    "futu_fetch_iv_terms_catalog_failed",
                    symbol=symbol,
                    index=idx,
                    total=total,
                    error=str(exc),
                )
                symbol_catalogs[symbol] = {}
                symbol_catalog_meta[symbol] = None
                symbol_codes[symbol] = []

        all_codes = list(
            dict.fromkeys(
                code
                for codes in symbol_codes.values()
                for code in codes
            )
        )
        if all_codes:
            fetch_snapshot_with_failures = getattr(
                self.options_fetcher,
                "fetch_snapshot_map_from_codes_with_failures",
                None,
            )
            if callable(fetch_snapshot_with_failures):
                global_snapshot_map, failed_snapshot_codes = fetch_snapshot_with_failures(all_codes)
            else:
                fetch_snapshot_from_codes = getattr(self.options_fetcher, "fetch_snapshot_map_from_codes", None)
                if callable(fetch_snapshot_from_codes):
                    global_snapshot_map = fetch_snapshot_from_codes(all_codes)
                    failed_snapshot_codes = set()
                else:
                    global_snapshot_map = {}
                    for expirations in symbol_catalogs.values():
                        global_snapshot_map.update(self.options_fetcher.fetch_snapshot_map(expirations))
                    failed_snapshot_codes = set()
        else:
            global_snapshot_map = {}
            failed_snapshot_codes = set()

        for idx, symbol in enumerate(symbols_list, start=1 + progress_offset):
            try:
                result = self._build_symbol_iv_terms(
                    symbol=symbol,
                    expirations=symbol_catalogs.get(symbol, {}),
                    fetch_meta=symbol_catalog_meta.get(symbol),
                    snapshot_map={
                        code: global_snapshot_map[code]
                        for code in symbol_codes.get(symbol, [])
                        if code in global_snapshot_map
                    },
                    today=today,
                    snapshot_failed=bool(set(symbol_codes.get(symbol, [])) & failed_snapshot_codes),
                )

                if any(
                    value is not None
                    for value in (
                        result.total_oi,
                        result.oi_bucket_0_7,
                        result.oi_bucket_8_30,
                        result.oi_bucket_31_90,
                    )
                ):
                    delta_payload = self._compute_bucket_delta_payload(
                        symbol=symbol,
                        today=today,
                        result=result,
                        cache=cache,
                    )
                    self._apply_delta_payload(result=result, delta_payload=delta_payload)
                    cache_changed = True

                results[symbol] = result

                if log_progress:
                    logger.info(
                        "\n".join(
                            [
                                f"FUTU- [{idx}/{total}] {symbol}",
                                (
                                    f" - IV7/30/60/90: "
                                    f"{self.options_fetcher.fmt_iv(result.iv7)}% / "
                                    f"{self.options_fetcher.fmt_iv(result.iv30)}% / "
                                    f"{self.options_fetcher.fmt_iv(result.iv60)}% / "
                                    f"{self.options_fetcher.fmt_iv(result.iv90)}%"
                                ),
                                (
                                    f"-  OI: {result.total_oi if result.total_oi is not None else 'N/A'} "
                                    f"(Δ1D: {result.delta_oi_1d if result.delta_oi_1d is not None else 'N/A'}) "
                                    f"(0-7D: {result.oi_bucket_0_7 if result.oi_bucket_0_7 is not None else 'N/A'}, "
                                    f"8-30D: {result.oi_bucket_8_30 if result.oi_bucket_8_30 is not None else 'N/A'}, "
                                    f"31-90D: {result.oi_bucket_31_90 if result.oi_bucket_31_90 is not None else 'N/A'})"
                                ),
                                "---",
                            ]
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "futu_fetch_iv_terms_symbol_failed",
                    symbol=symbol,
                    index=idx,
                    total=total,
                    error=str(exc),
                )
                results[symbol] = IVTermResult()

        if cache_changed:
            self._save_oi_cache(cache)

        return results

    def batch_compute_delta_oi(
        self,
        symbol_to_oi: Dict[str, Optional[int]],
    ) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        cache = self._load_oi_cache()
        today = beijing_today()

        results: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        for symbol, current_oi in symbol_to_oi.items():
            if current_oi is None:
                results[symbol] = (None, None)
                continue

            prev_snapshot = self._find_latest_snapshot_before(
                symbol=symbol,
                before_date=today.strftime("%Y-%m-%d"),
                cache=cache,
            )
            prev_total_oi = self._as_int((prev_snapshot or {}).get("total_oi"))
            delta_oi = current_oi - prev_total_oi if prev_total_oi is not None else None

            self._upsert_symbol_snapshot(
                symbol=symbol,
                date_str=today.strftime("%Y-%m-%d"),
                snapshot={"total_oi": int(current_oi), "buckets": {}},
                cache=cache,
            )
            results[symbol] = (current_oi, delta_oi)

        self._save_oi_cache(cache)
        return results

    def _fetch_symbol_iv_terms_with_retry(
        self,
        symbol: str,
        max_days: int,
        window_days: int,
        max_retries: int,
        log_fetch_summary: bool,
    ) -> IVTermResult:
        for attempt in range(max_retries + 1):
            try:
                return self._fetch_symbol_iv_terms(
                    symbol,
                    max_days=max_days,
                    window_days=window_days,
                    log_fetch_summary=log_fetch_summary,
                )
            except Exception as exc:
                if attempt < max_retries:
                    sleep_seconds = min(30.0, 2 ** attempt)
                    logger.warning(
                        "futu_fetch_iv_terms_retry",
                        symbol=symbol,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        sleep_seconds=sleep_seconds,
                        error=str(exc),
                    )
                    time.sleep(sleep_seconds)
                    continue
                raise
        return IVTermResult()

    def _fetch_symbol_iv_terms(
        self,
        symbol: str,
        max_days: int,
        window_days: int,
        log_fetch_summary: bool = True,
    ) -> IVTermResult:
        expirations, fetch_meta = self._load_symbol_contract_catalog(
            symbol=symbol,
            max_days=max_days,
            window_days=window_days,
            option_types=self._resolve_option_types(),
            log_fetch_summary=log_fetch_summary,
        )
        snapshot_map = self.options_fetcher.fetch_snapshot_map(expirations)
        return self._build_symbol_iv_terms(
            symbol=symbol,
            expirations=expirations,
            fetch_meta=fetch_meta,
            snapshot_map=snapshot_map,
            today=beijing_today(),
        )

    def _resolve_option_types(self) -> List[Any]:
        option_types_resolver = getattr(self.options_fetcher, "default_option_types", None)
        if callable(option_types_resolver):
            return option_types_resolver()
        return FutuOptionsDataFetcher.default_option_types()

    def _load_symbol_contract_catalog(
        self,
        symbol: str,
        max_days: int,
        window_days: int,
        option_types: Optional[List[Any]],
        log_fetch_summary: bool,
    ) -> Tuple[Dict[str, List[OptionContract]], Any]:
        catalog_loader = getattr(self.options_fetcher, "get_or_refresh_contract_catalog", None)
        if callable(catalog_loader):
            return catalog_loader(
                symbol=symbol,
                max_days=max_days,
                window_days=window_days,
                option_types=option_types,
                force_refresh=False,
                log_fetch_summary=log_fetch_summary,
            )
        return self.options_fetcher.collect_expirations_with_meta(
            symbol=symbol,
            max_days=max_days,
            window_days=window_days,
            option_types=option_types,
            log_fetch_summary=log_fetch_summary,
        )

    def _load_symbol_contract_catalog_with_retry(
        self,
        symbol: str,
        max_days: int,
        window_days: int,
        max_retries: int,
        option_types: Optional[List[Any]],
        log_fetch_summary: bool,
    ) -> Tuple[Dict[str, List[OptionContract]], Any]:
        for attempt in range(max_retries + 1):
            try:
                return self._load_symbol_contract_catalog(
                    symbol=symbol,
                    max_days=max_days,
                    window_days=window_days,
                    option_types=option_types,
                    log_fetch_summary=log_fetch_summary,
                )
            except Exception as exc:
                if attempt < max_retries:
                    sleep_seconds = min(30.0, 2 ** attempt)
                    logger.warning(
                        "futu_load_contract_catalog_retry",
                        symbol=symbol,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        sleep_seconds=sleep_seconds,
                        error=str(exc),
                    )
                    time.sleep(sleep_seconds)
                    continue
                raise
        return {}, None

    def _build_symbol_iv_terms(
        self,
        symbol: str,
        expirations: Dict[str, List[OptionContract]],
        fetch_meta: Any,
        snapshot_map: Dict[str, Dict],
        today: Any,
        snapshot_failed: bool = False,
    ) -> IVTermResult:
        fetch_strategy = getattr(fetch_meta, "strategy", "none")
        failed_requests = getattr(fetch_meta, "failed_requests", 0)
        success_requests = getattr(fetch_meta, "success_requests", 0)
        unique_expirations = getattr(fetch_meta, "unique_expirations", 0)
        if not expirations:
            logger.warning(
                "futu_no_option_expiration",
                symbol=symbol,
                strategy=fetch_strategy,
                failed_requests=failed_requests,
                success_requests=success_requests,
            )
            return IVTermResult(
                _fetch_incomplete=snapshot_failed,
                _fetch_error="no_catalog",
            )

        near_term_expirations = self._count_near_term_expirations(expirations, today, max_day=90)
        if near_term_expirations == 0:
            logger.warning(
                "futu_option_chain_near_term_missing",
                symbol=symbol,
                strategy=fetch_strategy,
                failed_requests=failed_requests,
                success_requests=success_requests,
                unique_expirations=unique_expirations,
            )
            return IVTermResult(
                _fetch_incomplete=snapshot_failed,
                _fetch_error="near_term_missing",
            )

        if not snapshot_map:
            return IVTermResult(
                _fetch_incomplete=snapshot_failed,
                _fetch_error="snapshot_missing",
            )

        points = self._build_iv_points(expirations, snapshot_map, today)

        iv7 = self._interpolate_iv(points, 7)
        iv30 = self._interpolate_iv(points, 30)
        iv60 = self._interpolate_iv(points, 60)
        iv90 = self._interpolate_iv(points, 90)

        snapshot_payload = self._build_oi_snapshot_payload(
            symbol=symbol,
            expirations=expirations,
            snapshot_map=snapshot_map,
            today=today,
        )
        result = IVTermResult(
            iv7=iv7,
            iv30=iv30,
            iv60=iv60,
            iv90=iv90,
            total_oi=self._as_int(snapshot_payload.get("total_oi")),
            risk_total_oi=self._as_int(snapshot_payload.get("risk_total_oi")),
            oi_bucket_0_7=self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "net"),
            oi_bucket_8_30=self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "net"),
            oi_bucket_31_90=self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "net"),
            risk_oi_bucket_0_7=self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "risk_net"),
            risk_oi_bucket_8_30=self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "risk_net"),
            risk_oi_bucket_31_90=self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "risk_net"),
            call_oi_bucket_0_7=self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "call"),
            call_oi_bucket_8_30=self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "call"),
            call_oi_bucket_31_90=self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "call"),
            put_oi_bucket_0_7=self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "put"),
            put_oi_bucket_8_30=self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "put"),
            put_oi_bucket_31_90=self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "put"),
            _fetch_incomplete=snapshot_failed,
            _fetch_error="snapshot_chunk_failed" if snapshot_failed else None,
        )
        result._snapshot_payload = snapshot_payload
        return result

    def _compute_bucket_delta_payload(
        self,
        symbol: str,
        today: Any,
        result: IVTermResult,
        cache: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        today_str = today.strftime("%Y-%m-%d")
        current_snapshot = self._normalize_snapshot_payload(getattr(result, "_snapshot_payload", None))
        if current_snapshot is None:
            current_snapshot = self._build_snapshot_from_result(result)
        previous_snapshot = self._find_latest_snapshot_before(
            symbol=symbol,
            before_date=today_str,
            cache=cache,
        )

        self._upsert_symbol_snapshot(
            symbol=symbol,
            date_str=today_str,
            snapshot=current_snapshot,
            cache=cache,
        )

        history_entries = self._get_symbol_entries(symbol=symbol, cache=cache)
        current_delta_summary = self._summarize_contract_delta(
            current_snapshot=current_snapshot,
            previous_snapshot=previous_snapshot,
        )
        total_oi_1d = current_delta_summary.get("total_1d")

        by_bucket: Dict[str, Dict[str, Optional[int]]] = {}
        for suffix in self.BUCKET_SUFFIXES:
            summary_bucket = (current_delta_summary.get("by_bucket") or {}).get(suffix, {})
            raw_net_1d = self._as_int(summary_bucket.get("net"))
            raw_call_1d = self._as_int(summary_bucket.get("call"))
            raw_put_1d = self._as_int(summary_bucket.get("put"))

            daily_net_series = self._build_daily_delta_series(
                entries=history_entries,
                suffix=suffix,
                side="net",
            )
            clipped_daily_net_series = self._clip_series_by_quantile(daily_net_series)
            clipped_net_1d = (
                clipped_daily_net_series[-1] if clipped_daily_net_series else raw_net_1d
            )

            by_bucket[suffix] = {
                "net_1d": raw_net_1d,
                "call_1d": raw_call_1d,
                "put_1d": raw_put_1d,
                "clipped_net_1d": clipped_net_1d,
                "net_3d": self._rolling_sum(clipped_daily_net_series, window=3),
                "net_5d": self._rolling_sum(clipped_daily_net_series, window=5),
            }

        return {
            "total_oi_1d": total_oi_1d,
            "by_bucket": by_bucket,
        }

    def _apply_delta_payload(self, result: IVTermResult, delta_payload: Dict[str, Any]) -> None:
        result.delta_oi_1d = delta_payload.get("total_oi_1d")
        by_bucket = delta_payload.get("by_bucket") or {}

        for suffix in self.BUCKET_SUFFIXES:
            bucket_payload = by_bucket.get(suffix) or {}
            setattr(result, f"net_delta_oi_{suffix}", bucket_payload.get("net_1d"))
            setattr(result, f"call_delta_oi_{suffix}", bucket_payload.get("call_1d"))
            setattr(result, f"put_delta_oi_{suffix}", bucket_payload.get("put_1d"))
            setattr(result, f"clipped_net_delta_oi_{suffix}", bucket_payload.get("clipped_net_1d"))
            setattr(result, f"net_delta3d_{suffix}", bucket_payload.get("net_3d"))
            setattr(result, f"net_delta5d_{suffix}", bucket_payload.get("net_5d"))
            setattr(result, f"delta_oi_bucket_{suffix}_3d", bucket_payload.get("net_3d"))
            setattr(result, f"delta_oi_bucket_{suffix}_5d", bucket_payload.get("net_5d"))

    def _build_snapshot_from_result(self, result: IVTermResult) -> Dict[str, Any]:
        internal_snapshot = self._normalize_snapshot_payload(getattr(result, "_snapshot_payload", None))
        if internal_snapshot is not None:
            return internal_snapshot

        snapshot = {
            "total_oi": self._as_int(result.total_oi),
            "risk_total_oi": self._as_int(getattr(result, "risk_total_oi", None)),
            "buckets": {},
            "contracts": {},
        }

        for suffix in self.BUCKET_SUFFIXES:
            net_value = self._as_int(getattr(result, f"oi_bucket_{suffix}", None))
            call_value = self._as_int(getattr(result, f"call_oi_bucket_{suffix}", None))
            put_value = self._as_int(getattr(result, f"put_oi_bucket_{suffix}", None))
            risk_net_value = self._as_int(getattr(result, f"risk_oi_bucket_{suffix}", None))

            if net_value is None and call_value is not None and put_value is not None:
                net_value = call_value + put_value

            snapshot["buckets"][suffix] = {
                "net": net_value,
                "call": call_value,
                "put": put_value,
                "risk_net": risk_net_value,
            }

        if snapshot["total_oi"] is None:
            bucket_totals = [
                (snapshot.get("buckets") or {}).get(suffix, {}).get("net")
                for suffix in self.BUCKET_SUFFIXES
            ]
            valid_totals = [value for value in bucket_totals if value is not None]
            if valid_totals:
                snapshot["total_oi"] = int(sum(valid_totals))
        if snapshot["risk_total_oi"] is None:
            risk_bucket_totals = [
                (snapshot.get("buckets") or {}).get(suffix, {}).get("risk_net")
                for suffix in self.BUCKET_SUFFIXES
            ]
            valid_risk_totals = [value for value in risk_bucket_totals if value is not None]
            if valid_risk_totals:
                snapshot["risk_total_oi"] = int(sum(valid_risk_totals))
        return snapshot

    def _build_daily_delta_series(
        self,
        entries: List[Tuple[str, Dict[str, Any]]],
        suffix: str,
        side: str,
    ) -> List[int]:
        deltas: List[int] = []
        if len(entries) < 2:
            return deltas

        for idx in range(1, len(entries)):
            prev_snapshot = entries[idx - 1][1]
            curr_snapshot = entries[idx][1]
            delta_summary = self._summarize_contract_delta(
                current_snapshot=curr_snapshot,
                previous_snapshot=prev_snapshot,
            )
            delta_value = self._extract_delta_summary_value(
                delta_summary=delta_summary,
                suffix=suffix,
                side=side,
            )
            if delta_value is not None:
                deltas.append(delta_value)
        return deltas

    @staticmethod
    def _delta(current: Optional[int], previous: Optional[int]) -> Optional[int]:
        if current is None or previous is None:
            return None
        return int(current - previous)

    @staticmethod
    def _rolling_sum(values: List[int], window: int) -> Optional[int]:
        if not values:
            return None
        effective_window = max(1, int(window))
        window_values = values[-effective_window:]
        return int(round(sum(window_values)))

    def _clip_series_by_quantile(self, values: List[int], lower_q: float = 0.05, upper_q: float = 0.95) -> List[int]:
        if not values:
            return []
        if len(values) < 5:
            return list(values)

        history = values[:-1] if len(values) > 1 else values
        lower_bound = self._quantile(history, lower_q)
        upper_bound = self._quantile(history, upper_q)
        if lower_bound is None or upper_bound is None:
            return list(values)

        clipped: List[int] = []
        for value in values:
            clipped_value = min(max(float(value), lower_bound), upper_bound)
            clipped.append(int(round(clipped_value)))
        return clipped

    @staticmethod
    def _quantile(values: List[int], q: float) -> Optional[float]:
        if not values:
            return None

        sorted_values = sorted(float(v) for v in values)
        if len(sorted_values) == 1:
            return sorted_values[0]

        clipped_q = min(1.0, max(0.0, float(q)))
        pos = clipped_q * (len(sorted_values) - 1)
        lo = int(pos)
        hi = min(len(sorted_values) - 1, lo + 1)
        weight = pos - lo
        return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight

    def _extract_bucket_side(self, snapshot: Dict[str, Any], suffix: str, side: str) -> Optional[int]:
        buckets = snapshot.get("buckets") if isinstance(snapshot, dict) else {}
        if isinstance(buckets, dict):
            bucket_payload = buckets.get(suffix)
            if isinstance(bucket_payload, dict):
                value = self._as_int(bucket_payload.get(side))
                if value is not None:
                    return value

        key_map = {
            "net": f"oi_bucket_{suffix}",
            "call": f"call_oi_bucket_{suffix}",
            "put": f"put_oi_bucket_{suffix}",
        }
        key = key_map.get(side)
        if key and isinstance(snapshot, dict):
            return self._as_int(snapshot.get(key))
        return None

    def _summarize_contract_delta(
        self,
        current_snapshot: Optional[Dict[str, Any]],
        previous_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        empty_by_bucket = {
            suffix: {"net": None, "call": None, "put": None}
            for suffix in self.BUCKET_SUFFIXES
        }
        current_contracts = (
            current_snapshot.get("contracts")
            if isinstance(current_snapshot, dict) and isinstance(current_snapshot.get("contracts"), dict)
            else {}
        )
        previous_contracts = (
            previous_snapshot.get("contracts")
            if isinstance(previous_snapshot, dict) and isinstance(previous_snapshot.get("contracts"), dict)
            else {}
        )
        if not current_contracts or not previous_contracts:
            return {
                "total_1d": None,
                "by_bucket": empty_by_bucket,
            }

        totals: Dict[str, Dict[str, float]] = {
            suffix: {"net": 0.0, "call": 0.0, "put": 0.0}
            for suffix in self.BUCKET_SUFFIXES
        }
        has_value: Dict[str, Dict[str, bool]] = {
            suffix: {"net": False, "call": False, "put": False}
            for suffix in self.BUCKET_SUFFIXES
        }
        total_1d = 0.0
        has_total = False

        for contract_code in set(current_contracts.keys()) | set(previous_contracts.keys()):
            current_contract = current_contracts.get(contract_code)
            previous_contract = previous_contracts.get(contract_code)

            current_oi = self._as_int((current_contract or {}).get("oi"))
            previous_oi = self._as_int((previous_contract or {}).get("oi"))
            if current_oi is None and previous_oi is None:
                continue

            delta_oi = (current_oi or 0) - (previous_oi or 0)
            if delta_oi == 0:
                continue

            risk_weight = self._as_float((current_contract or {}).get("risk_weight"))
            if risk_weight is None:
                risk_weight = self._as_float((previous_contract or {}).get("risk_weight"))
            if risk_weight is None or risk_weight <= 0:
                continue

            contract_payload = current_contract if current_contract is not None else previous_contract
            bucket = str((contract_payload or {}).get("bucket") or "").strip()
            if bucket not in self.BUCKET_SUFFIXES:
                continue
            side = str((contract_payload or {}).get("side") or "").strip().lower()

            contribution = float(delta_oi) * float(risk_weight)
            totals[bucket]["net"] += contribution
            has_value[bucket]["net"] = True
            total_1d += contribution
            has_total = True

            if side in {"call", "put"}:
                totals[bucket][side] += contribution
                has_value[bucket][side] = True

        by_bucket = {
            suffix: {
                side: int(round(totals[suffix][side])) if has_value[suffix][side] else None
                for side in ("net", "call", "put")
            }
            for suffix in self.BUCKET_SUFFIXES
        }
        return {
            "total_1d": int(round(total_1d)) if has_total else None,
            "by_bucket": by_bucket,
        }

    @staticmethod
    def _extract_delta_summary_value(
        delta_summary: Dict[str, Any],
        suffix: str,
        side: str,
    ) -> Optional[int]:
        if side == "total":
            value = delta_summary.get("total_1d") if isinstance(delta_summary, dict) else None
            return int(value) if value is not None else None
        by_bucket = delta_summary.get("by_bucket") if isinstance(delta_summary, dict) else {}
        bucket_payload = by_bucket.get(suffix) if isinstance(by_bucket, dict) else {}
        value = bucket_payload.get(side) if isinstance(bucket_payload, dict) else None
        return int(value) if value is not None else None

    def _find_latest_snapshot_before(
        self,
        symbol: str,
        before_date: str,
        cache: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        entries = self._get_symbol_entries(symbol=symbol, cache=cache)
        for date_str, snapshot in reversed(entries):
            if date_str < before_date:
                return snapshot
        return None

    def _upsert_symbol_snapshot(
        self,
        symbol: str,
        date_str: str,
        snapshot: Dict[str, Any],
        cache: Dict[str, Dict[str, Any]],
    ) -> None:
        symbol_key = str(symbol).upper()
        symbol_cache = cache.setdefault(symbol_key, {})
        if not isinstance(symbol_cache, dict):
            symbol_cache = {}
            cache[symbol_key] = symbol_cache

        symbol_cache[date_str] = snapshot

        cutoff_str = (
            datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=self.CACHE_RETENTION_DAYS)
        ).strftime("%Y-%m-%d")
        cache[symbol_key] = {
            key: value
            for key, value in symbol_cache.items()
            if isinstance(key, str) and key >= cutoff_str
        }

    def _get_symbol_entries(
        self,
        symbol: str,
        cache: Dict[str, Dict[str, Any]],
    ) -> List[Tuple[str, Dict[str, Any]]]:
        symbol_key = str(symbol).upper()
        raw_symbol_cache = cache.get(symbol_key, {})
        if not isinstance(raw_symbol_cache, dict):
            cache[symbol_key] = {}
            return []

        normalized_cache: Dict[str, Dict[str, Any]] = {}
        for date_key, raw_payload in raw_symbol_cache.items():
            if not isinstance(date_key, str):
                continue
            snapshot = self._normalize_snapshot_payload(raw_payload)
            if snapshot is None:
                continue
            normalized_cache[date_key] = snapshot

        cache[symbol_key] = normalized_cache
        return sorted(normalized_cache.items(), key=lambda item: item[0])

    def _normalize_snapshot_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        if payload is None:
            return None

        if isinstance(payload, (int, float)):
            return {
                "total_oi": self._as_int(payload),
                "risk_total_oi": None,
                "buckets": {},
                "contracts": {},
            }

        if not isinstance(payload, dict):
            return None

        total_oi = self._as_int(payload.get("total_oi"))
        risk_total_oi = self._as_int(payload.get("risk_total_oi"))
        buckets_payload = payload.get("buckets") if isinstance(payload.get("buckets"), dict) else {}

        buckets: Dict[str, Dict[str, Optional[int]]] = {}
        for suffix in self.BUCKET_SUFFIXES:
            raw_bucket_payload = buckets_payload.get(suffix) if isinstance(buckets_payload, dict) else {}
            raw_bucket_payload = raw_bucket_payload if isinstance(raw_bucket_payload, dict) else {}

            net_value = self._as_int(raw_bucket_payload.get("net"))
            call_value = self._as_int(raw_bucket_payload.get("call"))
            put_value = self._as_int(raw_bucket_payload.get("put"))
            risk_net_value = self._as_int(raw_bucket_payload.get("risk_net"))

            if net_value is None:
                net_value = self._as_int(payload.get(f"oi_bucket_{suffix}"))
            if call_value is None:
                call_value = self._as_int(payload.get(f"call_oi_bucket_{suffix}"))
            if put_value is None:
                put_value = self._as_int(payload.get(f"put_oi_bucket_{suffix}"))
            if risk_net_value is None:
                risk_net_value = self._as_int(payload.get(f"risk_oi_bucket_{suffix}"))
            if net_value is None and call_value is not None and put_value is not None:
                net_value = call_value + put_value

            buckets[suffix] = {
                "net": net_value,
                "call": call_value,
                "put": put_value,
                "risk_net": risk_net_value,
            }

        if total_oi is None:
            bucket_totals = [buckets[suffix].get("net") for suffix in self.BUCKET_SUFFIXES]
            valid_totals = [value for value in bucket_totals if value is not None]
            if valid_totals:
                total_oi = int(sum(valid_totals))
        if risk_total_oi is None:
            risk_bucket_totals = [buckets[suffix].get("risk_net") for suffix in self.BUCKET_SUFFIXES]
            valid_risk_totals = [value for value in risk_bucket_totals if value is not None]
            if valid_risk_totals:
                risk_total_oi = int(sum(valid_risk_totals))

        raw_contracts = payload.get("contracts") if isinstance(payload.get("contracts"), dict) else {}
        contracts: Dict[str, Dict[str, Any]] = {}
        for contract_code, raw_contract in raw_contracts.items():
            if not isinstance(raw_contract, dict):
                continue
            contract_oi = self._as_int(raw_contract.get("oi"))
            if contract_oi is None:
                continue
            bucket = str(raw_contract.get("bucket") or "").strip()
            if bucket not in self.BUCKET_SUFFIXES:
                continue
            side = str(raw_contract.get("side") or "").strip().lower()
            if side not in {"call", "put"}:
                side = None
            contracts[str(contract_code)] = {
                "oi": contract_oi,
                "bucket": bucket,
                "side": side,
                "risk_weight": self._as_float(raw_contract.get("risk_weight")),
            }

        return {
            "total_oi": total_oi,
            "risk_total_oi": risk_total_oi,
            "buckets": buckets,
            "contracts": contracts,
        }

    @staticmethod
    def _as_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_iv_points(
        self,
        expirations: Dict[str, List[OptionContract]],
        snapshot_map: Dict[str, Dict],
        today: Any,
    ) -> List[Tuple[int, float]]:
        points: List[Tuple[int, float]] = []
        for expiry_str, contracts in expirations.items():
            expiry_date = self.options_fetcher.parse_date(expiry_str)
            if not expiry_date:
                continue

            dte = (expiry_date - today).days
            if dte <= 0:
                continue

            chosen_iv = self._pick_atm_iv(contracts, snapshot_map)
            if chosen_iv is not None:
                points.append((dte, chosen_iv))

        points.sort(key=lambda x: x[0])
        return points

    def _pick_atm_iv(
        self,
        contracts: List[OptionContract],
        snapshot_map: Dict[str, Dict],
    ) -> Optional[float]:
        best_iv = None
        best_diff = None

        for contract in contracts:
            if self._resolve_option_side(contract.option_type, contract.code) != "call":
                continue

            snapshot = snapshot_map.get(contract.code)
            if not snapshot:
                continue

            delta = self.options_fetcher.get_snapshot_value(snapshot, ["option_delta", "delta"])
            iv = self.options_fetcher.get_snapshot_value(
                snapshot,
                ["option_implied_volatility", "implied_volatility", "iv"],
            )
            if delta is None or iv is None:
                continue

            diff = abs(delta - 0.5)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_iv = self.options_fetcher.normalize_iv(iv)

        return best_iv

    def _sum_open_interest(self, snapshot_map: Dict[str, Dict]) -> Optional[int]:
        total = 0
        found = False
        for snapshot in snapshot_map.values():
            oi = self.options_fetcher.get_snapshot_value(snapshot, ["option_open_interest", "open_interest", "oi"])
            if oi is not None:
                found = True
                total += int(oi)
        return total if found else None

    def _sum_open_interest_by_bucket(
        self,
        expirations: Dict[str, List[OptionContract]],
        snapshot_map: Dict[str, Dict],
        today: Any,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        bucket_components = self._sum_open_interest_bucket_components(expirations, snapshot_map, today)
        return (
            bucket_components["0-7"]["total"],
            bucket_components["8-30"]["total"],
            bucket_components["31-90"]["total"],
        )

    def _build_oi_snapshot_payload(
        self,
        symbol: str,
        expirations: Dict[str, List[OptionContract]],
        snapshot_map: Dict[str, Dict],
        today: Any,
    ) -> Dict[str, Any]:
        bucket_keys = ("0-7", "8-30", "31-90")
        bucket_to_suffix = {
            "0-7": "0_7",
            "8-30": "8_30",
            "31-90": "31_90",
        }
        raw_buckets: Dict[str, Dict[str, int]] = {
            bucket: {"net": 0, "call": 0, "put": 0} for bucket in bucket_keys
        }
        raw_has_value: Dict[str, Dict[str, bool]] = {
            bucket: {"net": False, "call": False, "put": False} for bucket in bucket_keys
        }
        risk_buckets: Dict[str, Dict[str, float]] = {
            bucket: {"net": 0.0, "call": 0.0, "put": 0.0} for bucket in bucket_keys
        }
        risk_has_value: Dict[str, Dict[str, bool]] = {
            bucket: {"net": False, "call": False, "put": False} for bucket in bucket_keys
        }
        contracts_payload: Dict[str, Dict[str, Any]] = {}

        underlying_price = None
        current_price_resolver = getattr(self.options_fetcher, "get_current_price", None)
        if symbol and callable(current_price_resolver):
            try:
                underlying_price = current_price_resolver(symbol)
            except Exception as exc:
                logger.warning("futu_get_underlying_price_failed", symbol=symbol, error=str(exc))

        for expiry_str, contracts in expirations.items():
            expiry_date = self.options_fetcher.parse_date(expiry_str)
            if not expiry_date:
                continue

            dte = (expiry_date - today).days
            if dte <= 0:
                continue

            if dte <= 7:
                bucket = "0-7"
            elif dte <= 30:
                bucket = "8-30"
            elif dte <= 90:
                bucket = "31-90"
            else:
                continue

            for contract in contracts:
                snapshot = snapshot_map.get(contract.code)
                if not snapshot:
                    continue

                oi = self.options_fetcher.get_snapshot_value(snapshot, ["option_open_interest", "open_interest", "oi"])
                if oi is None:
                    continue
                oi_value = int(oi)
                raw_buckets[bucket]["net"] += oi_value
                raw_has_value[bucket]["net"] = True

                option_side = self._resolve_option_side(contract.option_type, contract.code)
                if option_side in {"call", "put"}:
                    raw_buckets[bucket][option_side] += oi_value
                    raw_has_value[bucket][option_side] = True

                risk_weight = self._resolve_risk_weight(
                    snapshot=snapshot,
                    option_code=contract.code,
                    underlying_price=underlying_price,
                )
                if risk_weight is not None:
                    risk_value = float(oi_value) * float(risk_weight)
                    risk_buckets[bucket]["net"] += risk_value
                    risk_has_value[bucket]["net"] = True
                    if option_side in {"call", "put"}:
                        risk_buckets[bucket][option_side] += risk_value
                        risk_has_value[bucket][option_side] = True

                contracts_payload[contract.code] = {
                    "oi": oi_value,
                    "bucket": bucket_to_suffix[bucket],
                    "side": option_side,
                    "risk_weight": risk_weight,
                }

        buckets_payload: Dict[str, Dict[str, Optional[int]]] = {}
        for bucket in bucket_keys:
            suffix = bucket_to_suffix[bucket]
            buckets_payload[suffix] = {
                "net": raw_buckets[bucket]["net"] if raw_has_value[bucket]["net"] else None,
                "call": raw_buckets[bucket]["call"] if raw_has_value[bucket]["call"] else None,
                "put": raw_buckets[bucket]["put"] if raw_has_value[bucket]["put"] else None,
                "risk_net": int(round(risk_buckets[bucket]["net"])) if risk_has_value[bucket]["net"] else None,
            }
        raw_bucket_totals = [buckets_payload[suffix].get("net") for suffix in self.BUCKET_SUFFIXES]
        valid_raw_bucket_totals = [value for value in raw_bucket_totals if value is not None]
        risk_bucket_totals = [buckets_payload[suffix].get("risk_net") for suffix in self.BUCKET_SUFFIXES]
        valid_risk_bucket_totals = [value for value in risk_bucket_totals if value is not None]
        return {
            "total_oi": int(sum(valid_raw_bucket_totals)) if valid_raw_bucket_totals else None,
            "risk_total_oi": int(sum(valid_risk_bucket_totals)) if valid_risk_bucket_totals else None,
            "buckets": buckets_payload,
            "contracts": contracts_payload,
        }

    def _sum_open_interest_bucket_components(
        self,
        expirations: Dict[str, List[OptionContract]],
        snapshot_map: Dict[str, Dict],
        today: Any,
    ) -> Dict[str, Dict[str, Optional[int]]]:
        snapshot_payload = self._build_oi_snapshot_payload(
            symbol="",
            expirations=expirations,
            snapshot_map=snapshot_map,
            today=today,
        )
        return {
            "0-7": {
                "total": self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "net"),
                "call": self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "call"),
                "put": self._extract_snapshot_bucket_metric(snapshot_payload, "0_7", "put"),
            },
            "8-30": {
                "total": self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "net"),
                "call": self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "call"),
                "put": self._extract_snapshot_bucket_metric(snapshot_payload, "8_30", "put"),
            },
            "31-90": {
                "total": self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "net"),
                "call": self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "call"),
                "put": self._extract_snapshot_bucket_metric(snapshot_payload, "31_90", "put"),
            },
        }

    @staticmethod
    def _extract_snapshot_bucket_metric(
        snapshot_payload: Dict[str, Any],
        suffix: str,
        metric: str,
    ) -> Optional[int]:
        buckets = snapshot_payload.get("buckets") if isinstance(snapshot_payload, dict) else {}
        bucket_payload = buckets.get(suffix) if isinstance(buckets, dict) else {}
        value = bucket_payload.get(metric) if isinstance(bucket_payload, dict) else None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _resolve_risk_weight(
        self,
        snapshot: Dict[str, Any],
        option_code: str,
        underlying_price: Optional[float],
    ) -> Optional[float]:
        price = self._as_float(underlying_price)
        abs_delta = self._extract_abs_delta(snapshot)
        multiplier = self._extract_option_multiplier(snapshot, option_code)
        if price is None or price <= 0 or abs_delta is None or multiplier is None or multiplier <= 0:
            return None
        return float(price) * float(multiplier) * float(abs_delta)

    def _extract_abs_delta(self, snapshot: Dict[str, Any]) -> Optional[float]:
        delta = self.options_fetcher.get_snapshot_value(snapshot, ["option_delta", "delta"])
        if delta is None:
            return None
        return abs(float(delta))

    def _extract_option_multiplier(self, snapshot: Dict[str, Any], option_code: str) -> Optional[float]:
        multiplier = self.options_fetcher.get_snapshot_value(
            snapshot,
            [
                "contract_multiplier",
                "option_contract_size",
                "contract_size",
                "lot_size",
                "multiplier",
            ],
        )
        if multiplier is not None and multiplier > 0:
            return float(multiplier)

        # Futu snapshots do not always expose contract size; US equity options are
        # typically 100-share contracts, so keep a conservative fallback.
        code_text = str(option_code or "").strip().upper()
        if code_text.startswith("US."):
            return 100.0
        return 100.0

    @staticmethod
    def _resolve_option_side(option_type: Any, option_code: Optional[str] = None) -> Optional[str]:
        try:
            if option_type == OPTION_TYPE.CALL:
                return "call"
            if option_type == OPTION_TYPE.PUT:
                return "put"
        except Exception:
            pass

        text = str(option_type).strip().upper() if option_type is not None else ""
        if "CALL" in text:
            return "call"
        if "PUT" in text:
            return "put"

        code_text = str(option_code).strip().upper() if option_code else ""
        if code_text:
            if "CALL" in code_text:
                return "call"
            if "PUT" in code_text:
                return "put"
            # US option symbols commonly end with C/P followed by strike digits.
            # Example: US.AAPL260320C00190000
            match = re.search(r"([CP])\d{1,}$", code_text)
            if match:
                return "call" if match.group(1) == "C" else "put"
        return None

    @staticmethod
    def _interpolate_iv(points: List[Tuple[int, float]], target_day: int) -> Optional[float]:
        if not points:
            return None

        lower = None
        upper = None

        for dte, iv in points:
            if dte == target_day:
                return iv
            if dte < target_day:
                lower = (dte, iv)
            if dte > target_day and upper is None:
                upper = (dte, iv)
                break

        if lower and upper:
            d1, iv1 = lower
            d2, iv2 = upper
            if d2 == d1:
                return iv1
            var1 = (iv1 / 100.0) ** 2
            var2 = (iv2 / 100.0) ** 2
            weight = (target_day - d1) / (d2 - d1)
            var_t = var1 + (var2 - var1) * weight
            return (var_t ** 0.5) * 100.0

        one_sided_max_gap = {
            7: 7,
            30: 10,
            60: 15,
            90: 20,
        }.get(target_day, max(10, target_day // 4))

        if lower and not upper:
            d1, iv1 = lower
            if (target_day - d1) <= one_sided_max_gap:
                return iv1
            return None
        if upper and not lower:
            d2, iv2 = upper
            if (d2 - target_day) <= one_sided_max_gap:
                return iv2
            return None
        return None

    @staticmethod
    def _count_near_term_expirations(
        expirations: Dict[str, List[OptionContract]],
        today: Any,
        max_day: int = 90,
    ) -> int:
        total = 0
        for expiry_str, contracts in expirations.items():
            expiry_date = FutuOptionsDataFetcher.parse_date(expiry_str)
            if not expiry_date:
                continue
            dte = (expiry_date - today).days
            if dte <= 0 or dte > max_day:
                continue
            if contracts:
                total += 1
        return total

    def _connect_cache_db(self) -> sqlite3.Connection:
        db_path = Path(self.oi_cache_db_file).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(db_path),
            timeout=self.CACHE_DB_TIMEOUT_SECONDS,
        )
        try:
            conn.execute(f"PRAGMA busy_timeout = {self.CACHE_DB_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            # PRAGMA failures are non-fatal; keep using default sqlite settings.
            pass
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_cache_table(self) -> None:
        with self.CACHE_LOCK:
            try:
                with self._connect_cache_db() as conn:
                    conn.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {self.CACHE_TABLE} (
                            symbol TEXT NOT NULL,
                            snapshot_date TEXT NOT NULL,
                            total_oi INTEGER,
                            oi_bucket_0_7 INTEGER,
                            call_oi_bucket_0_7 INTEGER,
                            put_oi_bucket_0_7 INTEGER,
                            oi_bucket_8_30 INTEGER,
                            call_oi_bucket_8_30 INTEGER,
                            put_oi_bucket_8_30 INTEGER,
                            oi_bucket_31_90 INTEGER,
                            call_oi_bucket_31_90 INTEGER,
                            put_oi_bucket_31_90 INTEGER,
                            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (symbol, snapshot_date)
                        )
                        """
                    )
                    columns = {
                        str(row["name"])
                        for row in conn.execute(f"PRAGMA table_info({self.CACHE_TABLE})").fetchall()
                    }
                    if "snapshot_json" not in columns:
                        conn.execute(
                            f"ALTER TABLE {self.CACHE_TABLE} ADD COLUMN snapshot_json TEXT"
                        )
            except Exception as exc:
                logger.warning(f"futu_init_oi_cache_table_failed db_file={self.oi_cache_db_file} error={exc}")

    def _load_oi_cache(self) -> Dict[str, Dict[str, Any]]:
        self._ensure_cache_table()
        with self.CACHE_LOCK:
            try:
                cache: Dict[str, Dict[str, Any]] = {}
                with self._connect_cache_db() as conn:
                    rows = conn.execute(
                        f"""
                        SELECT
                            symbol,
                            snapshot_date,
                            total_oi,
                            oi_bucket_0_7,
                            call_oi_bucket_0_7,
                            put_oi_bucket_0_7,
                            oi_bucket_8_30,
                            call_oi_bucket_8_30,
                            put_oi_bucket_8_30,
                            oi_bucket_31_90,
                            call_oi_bucket_31_90,
                            put_oi_bucket_31_90,
                            snapshot_json
                        FROM {self.CACHE_TABLE}
                        ORDER BY symbol ASC, snapshot_date ASC
                        """
                    ).fetchall()

                for row in rows:
                    symbol = str(row["symbol"]).upper()
                    date_str = row["snapshot_date"]
                    if not isinstance(date_str, str):
                        continue

                    snapshot_payload = None
                    snapshot_json = row["snapshot_json"]
                    if isinstance(snapshot_json, str) and snapshot_json.strip():
                        try:
                            snapshot_payload = json.loads(snapshot_json)
                        except Exception:
                            snapshot_payload = None
                    if snapshot_payload is None:
                        snapshot_payload = {
                            "total_oi": self._as_int(row["total_oi"]),
                            "buckets": {
                                "0_7": {
                                    "net": self._as_int(row["oi_bucket_0_7"]),
                                    "call": self._as_int(row["call_oi_bucket_0_7"]),
                                    "put": self._as_int(row["put_oi_bucket_0_7"]),
                                },
                                "8_30": {
                                    "net": self._as_int(row["oi_bucket_8_30"]),
                                    "call": self._as_int(row["call_oi_bucket_8_30"]),
                                    "put": self._as_int(row["put_oi_bucket_8_30"]),
                                },
                                "31_90": {
                                    "net": self._as_int(row["oi_bucket_31_90"]),
                                    "call": self._as_int(row["call_oi_bucket_31_90"]),
                                    "put": self._as_int(row["put_oi_bucket_31_90"]),
                                },
                            },
                            "contracts": {},
                        }
                    normalized_snapshot = self._normalize_snapshot_payload(snapshot_payload)
                    if normalized_snapshot is None:
                        continue
                    cache.setdefault(symbol, {})[date_str] = normalized_snapshot
                return cache
            except Exception as exc:
                logger.warning(f"futu_load_oi_cache_failed db_file={self.oi_cache_db_file} error={exc}")
                return {}

    def _save_oi_cache(self, cache: Dict[str, Dict[str, Any]]) -> None:
        self._ensure_cache_table()
        with self.CACHE_LOCK:
            rows: List[Tuple[Any, ...]] = []
            for symbol, symbol_cache in cache.items():
                if not isinstance(symbol_cache, dict):
                    continue
                symbol_key = str(symbol).upper()
                for date_str, payload in symbol_cache.items():
                    if not isinstance(date_str, str):
                        continue
                    snapshot = self._normalize_snapshot_payload(payload)
                    if snapshot is None:
                        continue

                    bucket_0_7 = (snapshot.get("buckets") or {}).get("0_7", {})
                    bucket_8_30 = (snapshot.get("buckets") or {}).get("8_30", {})
                    bucket_31_90 = (snapshot.get("buckets") or {}).get("31_90", {})

                    rows.append(
                        (
                            symbol_key,
                            date_str,
                            self._as_int(snapshot.get("total_oi")),
                            self._as_int(bucket_0_7.get("net")),
                            self._as_int(bucket_0_7.get("call")),
                            self._as_int(bucket_0_7.get("put")),
                            self._as_int(bucket_8_30.get("net")),
                            self._as_int(bucket_8_30.get("call")),
                            self._as_int(bucket_8_30.get("put")),
                            self._as_int(bucket_31_90.get("net")),
                            self._as_int(bucket_31_90.get("call")),
                            self._as_int(bucket_31_90.get("put")),
                            json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")),
                        )
                    )

            last_exc: Optional[Exception] = None
            for attempt in range(1, self.CACHE_SAVE_RETRY_ATTEMPTS + 1):
                try:
                    with self._connect_cache_db() as conn:
                        # Incremental upsert keeps lock windows small versus full-table rewrite.
                        if rows:
                            conn.executemany(
                                f"""
                                INSERT INTO {self.CACHE_TABLE} (
                                    symbol,
                                    snapshot_date,
                                    total_oi,
                                    oi_bucket_0_7,
                                    call_oi_bucket_0_7,
                                    put_oi_bucket_0_7,
                                    oi_bucket_8_30,
                                    call_oi_bucket_8_30,
                                    put_oi_bucket_8_30,
                                    oi_bucket_31_90,
                                    call_oi_bucket_31_90,
                                    put_oi_bucket_31_90,
                                    snapshot_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(symbol, snapshot_date) DO UPDATE SET
                                    total_oi = excluded.total_oi,
                                    oi_bucket_0_7 = excluded.oi_bucket_0_7,
                                    call_oi_bucket_0_7 = excluded.call_oi_bucket_0_7,
                                    put_oi_bucket_0_7 = excluded.put_oi_bucket_0_7,
                                    oi_bucket_8_30 = excluded.oi_bucket_8_30,
                                    call_oi_bucket_8_30 = excluded.call_oi_bucket_8_30,
                                    put_oi_bucket_8_30 = excluded.put_oi_bucket_8_30,
                                    oi_bucket_31_90 = excluded.oi_bucket_31_90,
                                    call_oi_bucket_31_90 = excluded.call_oi_bucket_31_90,
                                    put_oi_bucket_31_90 = excluded.put_oi_bucket_31_90,
                                    snapshot_json = excluded.snapshot_json,
                                    updated_at = CURRENT_TIMESTAMP
                                """,
                                rows,
                            )
                        cutoff_str = (
                            beijing_today() - timedelta(days=self.CACHE_RETENTION_DAYS)
                        ).strftime("%Y-%m-%d")
                        conn.execute(
                            f"DELETE FROM {self.CACHE_TABLE} WHERE snapshot_date < ?",
                            (cutoff_str,),
                        )
                    return
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc).lower()
                    should_retry = "database is locked" in msg or "database table is locked" in msg
                    if should_retry and attempt < self.CACHE_SAVE_RETRY_ATTEMPTS:
                        time.sleep(min(1.2, 0.2 * (2 ** (attempt - 1))))
                        continue
                    break

            if last_exc is not None:
                logger.warning(
                    f"futu_save_oi_cache_failed db_file={self.oi_cache_db_file} "
                    f"attempts={self.CACHE_SAVE_RETRY_ATTEMPTS} error={last_exc}"
                )


def estimate_iv_fetch_time(
    symbol_count: int,
    estimated_code_count: Optional[int] = None,
    windows_per_symbol: int = 4,
    option_type_count: int = 1,
) -> float:
    option_chain_calls = symbol_count * windows_per_symbol * option_type_count
    if estimated_code_count is not None:
        snapshot_calls = max(
            1,
            (max(1, int(estimated_code_count)) + FUTU_SNAPSHOT_MAX_CODES_PER_REQUEST - 1)
            // FUTU_SNAPSHOT_MAX_CODES_PER_REQUEST,
        )
    else:
        snapshot_calls = symbol_count

    chain_batches = (option_chain_calls + FUTU_OPTION_CHAIN_MAX_CALLS - 1) // FUTU_OPTION_CHAIN_MAX_CALLS
    snapshot_batches = (snapshot_calls + FUTU_SNAPSHOT_MAX_CALLS - 1) // FUTU_SNAPSHOT_MAX_CALLS
    return max(chain_batches, snapshot_batches) * 30.0
