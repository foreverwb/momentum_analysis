"""
Futu IV term and OI/delta-OI calculations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from .connection import FutuConnection
from .options_data import FutuOptionsDataFetcher, OptionContract
from .utils import OPTION_TYPE

logger = structlog.get_logger(__name__)


@dataclass
class IVTermResult:
    iv7: Optional[float] = None
    iv30: Optional[float] = None
    iv60: Optional[float] = None
    iv90: Optional[float] = None
    total_oi: Optional[int] = None
    oi_bucket_0_7: Optional[int] = None
    oi_bucket_8_30: Optional[int] = None
    oi_bucket_31_90: Optional[int] = None
    call_oi_bucket_0_7: Optional[int] = None
    call_oi_bucket_8_30: Optional[int] = None
    call_oi_bucket_31_90: Optional[int] = None
    put_oi_bucket_0_7: Optional[int] = None
    put_oi_bucket_8_30: Optional[int] = None
    put_oi_bucket_31_90: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_valid(self) -> bool:
        return any([self.iv7 is not None, self.iv30 is not None, self.iv60 is not None, self.iv90 is not None])


class FutuIVCalculator:
    """Compute IV7/30/60/90 and OI metrics using option-chain snapshots."""

    CACHE_LOCK = threading.Lock()

    def __init__(
        self,
        connection: FutuConnection,
        options_fetcher: FutuOptionsDataFetcher,
        oi_cache_file: str = "oi_cache.json",
    ):
        self.connection = connection
        self.options_fetcher = options_fetcher
        self.oi_cache_file = oi_cache_file

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

        for idx, symbol in enumerate(symbols_list, start=1 + progress_offset):
            try:
                result = self._fetch_symbol_iv_terms_with_retry(
                    symbol=symbol,
                    max_days=max_days,
                    window_days=window_days,
                    max_retries=max_retries,
                    log_fetch_summary=log_fetch_summary,
                )
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
                                    f"-  Δ OI: {result.total_oi if result.total_oi is not None else 'N/A'} "
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

        return results

    def batch_compute_delta_oi(
        self,
        symbol_to_oi: Dict[str, Optional[int]],
    ) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        cache = self._load_oi_cache()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        results: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        for symbol, current_oi in symbol_to_oi.items():
            if current_oi is None:
                results[symbol] = (None, None)
                continue

            symbol_cache = cache.get(symbol, {})
            yesterday_oi = None

            for days_ago in range(1, 8):
                past_date = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                if past_date in symbol_cache:
                    yesterday_oi = symbol_cache[past_date]
                    break

            delta_oi = current_oi - yesterday_oi if yesterday_oi is not None else None

            if symbol not in cache:
                cache[symbol] = {}
            cache[symbol][today] = current_oi
            cache[symbol] = {
                date: oi for date, oi in cache[symbol].items() if date >= cutoff
            }

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
        log_fetch_summary: bool,
    ) -> IVTermResult:
        expirations, fetch_meta = self.options_fetcher.collect_expirations_with_meta(
            symbol=symbol,
            max_days=max_days,
            window_days=window_days,
            option_types=[OPTION_TYPE.CALL, OPTION_TYPE.PUT],
            log_fetch_summary=log_fetch_summary,
        )
        if not expirations:
            logger.warning(
                "futu_no_option_expiration",
                symbol=symbol,
                strategy=fetch_meta.strategy,
                failed_requests=fetch_meta.failed_requests,
                success_requests=fetch_meta.success_requests,
            )
            return IVTermResult()

        today = datetime.now().date()
        near_term_expirations = self._count_near_term_expirations(expirations, today, max_day=90)
        if near_term_expirations == 0:
            logger.warning(
                "futu_option_chain_near_term_missing",
                symbol=symbol,
                strategy=fetch_meta.strategy,
                failed_requests=fetch_meta.failed_requests,
                success_requests=fetch_meta.success_requests,
                unique_expirations=fetch_meta.unique_expirations,
            )
            return IVTermResult()

        snapshot_map = self.options_fetcher.fetch_snapshot_map(expirations)
        if not snapshot_map:
            return IVTermResult()

        points = self._build_iv_points(expirations, snapshot_map, today)

        iv7 = self._interpolate_iv(points, 7)
        iv30 = self._interpolate_iv(points, 30)
        iv60 = self._interpolate_iv(points, 60)
        iv90 = self._interpolate_iv(points, 90)

        bucket_components = self._sum_open_interest_bucket_components(expirations, snapshot_map, today)
        bucket_0_7 = bucket_components["0-7"]["total"]
        bucket_8_30 = bucket_components["8-30"]["total"]
        bucket_31_90 = bucket_components["31-90"]["total"]
        call_bucket_0_7 = bucket_components["0-7"]["call"]
        call_bucket_8_30 = bucket_components["8-30"]["call"]
        call_bucket_31_90 = bucket_components["31-90"]["call"]
        put_bucket_0_7 = bucket_components["0-7"]["put"]
        put_bucket_8_30 = bucket_components["8-30"]["put"]
        put_bucket_31_90 = bucket_components["31-90"]["put"]
        bucket_values = [v for v in [bucket_0_7, bucket_8_30, bucket_31_90] if v is not None]
        if bucket_values:
            total_oi = sum(bucket_values)
        elif fetch_meta.failed_requests == 0:
            total_oi = self._sum_open_interest(snapshot_map)
        else:
            # Do not emit potentially biased OI when option-chain fetch is partial.
            total_oi = None

        return IVTermResult(
            iv7=iv7,
            iv30=iv30,
            iv60=iv60,
            iv90=iv90,
            total_oi=total_oi,
            oi_bucket_0_7=bucket_0_7,
            oi_bucket_8_30=bucket_8_30,
            oi_bucket_31_90=bucket_31_90,
            call_oi_bucket_0_7=call_bucket_0_7,
            call_oi_bucket_8_30=call_bucket_8_30,
            call_oi_bucket_31_90=call_bucket_31_90,
            put_oi_bucket_0_7=put_bucket_0_7,
            put_oi_bucket_8_30=put_bucket_8_30,
            put_oi_bucket_31_90=put_bucket_31_90,
        )

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
            if contract.option_type != OPTION_TYPE.CALL:
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

    def _sum_open_interest_bucket_components(
        self,
        expirations: Dict[str, List[OptionContract]],
        snapshot_map: Dict[str, Dict],
        today: Any,
    ) -> Dict[str, Dict[str, Optional[int]]]:
        bucket_keys = ("0-7", "8-30", "31-90")
        buckets: Dict[str, Dict[str, int]] = {
            bucket: {"total": 0, "call": 0, "put": 0} for bucket in bucket_keys
        }
        has_value: Dict[str, Dict[str, bool]] = {
            bucket: {"total": False, "call": False, "put": False} for bucket in bucket_keys
        }

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
                buckets[bucket]["total"] += oi_value
                has_value[bucket]["total"] = True

                option_side = self._resolve_option_side(contract.option_type, contract.code)
                if option_side in {"call", "put"}:
                    buckets[bucket][option_side] += oi_value
                    has_value[bucket][option_side] = True

        result: Dict[str, Dict[str, Optional[int]]] = {}
        for bucket in bucket_keys:
            result[bucket] = {
                side: buckets[bucket][side] if has_value[bucket][side] else None
                for side in ("total", "call", "put")
            }
        return result

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

    def _load_oi_cache(self) -> Dict[str, Dict[str, int]]:
        with self.CACHE_LOCK:
            if not os.path.exists(self.oi_cache_file):
                return {}
            try:
                with open(self.oi_cache_file, "r") as f:
                    raw = json.load(f)
                return raw if isinstance(raw, dict) else {}
            except Exception:
                return {}

    def _save_oi_cache(self, cache: Dict[str, Dict[str, int]]) -> None:
        with self.CACHE_LOCK:
            try:
                with open(self.oi_cache_file, "w") as f:
                    json.dump(cache, f, indent=2)
            except Exception as exc:
                logger.warning("futu_save_oi_cache_failed", error=str(exc))


def estimate_iv_fetch_time(
    symbol_count: int,
    windows_per_symbol: int = 4,
    option_type_count: int = 2,
) -> float:
    option_chain_calls = symbol_count * windows_per_symbol * option_type_count
    snapshot_calls = symbol_count

    chain_batches = (option_chain_calls + 9) // 10
    snapshot_batches = (snapshot_calls + 59) // 60
    return max(chain_batches, snapshot_batches) * 30.0
