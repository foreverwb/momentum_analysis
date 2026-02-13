"""
Futu options and snapshot data fetching.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .connection import FutuConnection
from .utils import OPTION_TYPE, RET_OK

logger = structlog.get_logger(__name__)


@dataclass
class OptionContract:
    code: str
    option_type: Any


@dataclass
class OptionChainFetchMeta:
    symbol: str
    strategy: str = "none"  # full | windowed | mixed | none
    total_requests: int = 0
    success_requests: int = 0
    failed_requests: int = 0
    total_contracts: int = 0
    unique_expirations: int = 0
    near_term_contracts: int = 0
    failed_details: List[Dict[str, str]] = field(default_factory=list)


class RateLimiter:
    """Simple fixed-window rate limiter."""

    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.calls: deque = deque()

    def acquire(self) -> None:
        now = time.time()

        while self.calls and now - self.calls[0] >= self.period_seconds:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            sleep_seconds = self.period_seconds - (now - self.calls[0]) + 0.01
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        self.calls.append(time.time())


class FutuOptionsDataFetcher:
    """Fetch option chain and market snapshot data from Futu."""

    def __init__(
        self,
        connection: FutuConnection,
        chain_limiter: Optional[RateLimiter] = None,
        snapshot_limiter: Optional[RateLimiter] = None,
    ):
        self.connection = connection
        self.chain_limiter = chain_limiter or RateLimiter(max_calls=10, period_seconds=30)
        self.snapshot_limiter = snapshot_limiter or RateLimiter(max_calls=60, period_seconds=30)

    @staticmethod
    def default_option_types() -> List[Any]:
        combined_type = getattr(OPTION_TYPE, "ALL", None)
        if combined_type is not None:
            return [combined_type]
        return [OPTION_TYPE.CALL, OPTION_TYPE.PUT]

    def get_current_price(self, symbol: str) -> Optional[float]:
        client = self.connection.get_client()
        if client is None:
            return None

        code = self.format_code(symbol, self.connection.market)
        try:
            ret, data = client.get_market_snapshot([code])
            if not self._is_ret_ok(ret):
                return None

            records = self.dataframe_to_records(data)
            if not records:
                return None

            price = self.get_snapshot_value(records[0], ["last_price", "close_price", "close", "cur_price"])
            if price is None or price <= 0:
                return None
            return float(price)
        except Exception as exc:
            logger.warning("futu_get_current_price_failed", symbol=symbol, error=str(exc))
            return None

    def collect_expirations(
        self,
        symbol: str,
        max_days: int = 120,
        window_days: int = 30,
        option_types: Optional[List[Any]] = None,
        log_fetch_summary: bool = True,
    ) -> Dict[str, List[OptionContract]]:
        expirations, _meta = self.collect_expirations_with_meta(
            symbol=symbol,
            max_days=max_days,
            window_days=window_days,
            option_types=option_types,
            log_fetch_summary=log_fetch_summary,
        )
        return expirations

    def collect_expirations_with_meta(
        self,
        symbol: str,
        max_days: int = 120,
        window_days: int = 30,
        option_types: Optional[List[Any]] = None,
        log_fetch_summary: bool = True,
    ) -> Tuple[Dict[str, List[OptionContract]], OptionChainFetchMeta]:
        client = self.connection.get_client()
        meta = OptionChainFetchMeta(symbol=symbol)
        if client is None:
            return {}, meta

        if option_types is None:
            option_types = self.default_option_types()

        code = self.format_code(symbol, self.connection.market)
        today = datetime.now().date()
        end_date = today + timedelta(days=max_days)
        expirations: Dict[str, List[OptionContract]] = defaultdict(list)
        seen_contracts: set[Tuple[str, str]] = set()
        full_success_option_types: set[str] = set()
        failed_option_types: List[Any] = []
        window_used = False

        # Prefer full-chain fetch first. Different Futu SDK/OpenD versions
        # may reject date-window arguments; full-chain call is the most stable.
        for option_type in option_types:
            meta.total_requests += 1
            ret, data = self.fetch_option_chain_with_retry(
                code=code,
                start_date=None,
                end_date=None,
                option_type=option_type,
            )
            if not self._is_ret_ok(ret):
                failed_option_types.append(option_type)
                meta.failed_requests += 1
                self._record_chain_fetch_failure(
                    meta=meta,
                    option_type=option_type,
                    start_date=None,
                    end_date=None,
                    error=data,
                )
                continue

            meta.success_requests += 1
            full_success_option_types.add(str(option_type))
            self._append_contracts(
                expirations=expirations,
                records=self.dataframe_to_records(data),
                option_type=option_type,
                seen_contracts=seen_contracts,
                start_date=today,
                end_date=end_date,
            )

        # Fallback: if full-chain failed for some option type, try windowed fetch.
        window_days = max(1, int(window_days))
        for option_type in failed_option_types:
            window_used = True
            window_start = today
            while window_start <= end_date:
                window_end = min(window_start + timedelta(days=window_days), end_date)
                start_str = window_start.strftime("%Y-%m-%d")
                end_str = window_end.strftime("%Y-%m-%d")
                meta.total_requests += 1

                ret, data = self.fetch_option_chain_with_retry(
                    code=code,
                    start_date=start_str,
                    end_date=end_str,
                    option_type=option_type,
                )
                if not self._is_ret_ok(ret):
                    meta.failed_requests += 1
                    self._record_chain_fetch_failure(
                        meta=meta,
                        option_type=option_type,
                        start_date=start_str,
                        end_date=end_str,
                        error=data,
                    )
                    window_start = window_end + timedelta(days=1)
                    continue

                meta.success_requests += 1
                self._append_contracts(
                    expirations=expirations,
                    records=self.dataframe_to_records(data),
                    option_type=option_type,
                    seen_contracts=seen_contracts,
                    start_date=today,
                    end_date=end_date,
                )
                window_start = window_end + timedelta(days=1)

        # Some OpenD versions only return near-term contracts for full-chain calls.
        # Supplement far-term ranges to improve IV60/IV90 and OI bucket coverage.
        max_dte_found = self._max_contract_dte(expirations, today=today)
        target_max_dte = min(max_days, 90)
        need_far_term_supplement = (
            target_max_dte >= 31
            and (max_dte_found is None or max_dte_found < target_max_dte)
        )
        if need_far_term_supplement:
            supplement_start = today if max_dte_found is None else today + timedelta(days=max_dte_found + 1)
            if supplement_start <= end_date:
                window_used = True
                for option_type in option_types:
                    window_start = supplement_start
                    while window_start <= end_date:
                        window_end = min(window_start + timedelta(days=window_days), end_date)
                        start_str = window_start.strftime("%Y-%m-%d")
                        end_str = window_end.strftime("%Y-%m-%d")
                        meta.total_requests += 1

                        ret, data = self.fetch_option_chain_with_retry(
                            code=code,
                            start_date=start_str,
                            end_date=end_str,
                            option_type=option_type,
                        )
                        if not self._is_ret_ok(ret):
                            meta.failed_requests += 1
                            self._record_chain_fetch_failure(
                                meta=meta,
                                option_type=option_type,
                                start_date=start_str,
                                end_date=end_str,
                                error=data,
                            )
                            window_start = window_end + timedelta(days=1)
                            continue

                        meta.success_requests += 1
                        self._append_contracts(
                            expirations=expirations,
                            records=self.dataframe_to_records(data),
                            option_type=option_type,
                            seen_contracts=seen_contracts,
                            start_date=today,
                            end_date=end_date,
                        )
                        window_start = window_end + timedelta(days=1)

        if full_success_option_types and window_used:
            meta.strategy = "mixed"
        elif window_used:
            meta.strategy = "windowed"
        elif full_success_option_types:
            meta.strategy = "full"

        meta.total_contracts = sum(len(contracts) for contracts in expirations.values())
        meta.unique_expirations = len(expirations)
        meta.near_term_contracts = self._count_near_term_contracts(expirations, today, max_day=90)

        if log_fetch_summary and (meta.failed_requests > 0 or window_used):
            logger.info(
                "futu_option_chain_fetch_summary",
                symbol=symbol,
                strategy=meta.strategy,
                total_requests=meta.total_requests,
                success_requests=meta.success_requests,
                failed_requests=meta.failed_requests,
                unique_expirations=meta.unique_expirations,
                total_contracts=meta.total_contracts,
                near_term_contracts=meta.near_term_contracts,
            )

        return dict(expirations), meta

    def fetch_snapshot_map(
        self,
        expirations: Dict[str, List[OptionContract]],
    ) -> Dict[str, Dict]:
        client = self.connection.get_client()
        if client is None:
            return {}

        codes: List[str] = []
        for contracts in expirations.values():
            codes.extend(contract.code for contract in contracts)

        if not codes:
            return {}

        codes = list(dict.fromkeys(codes))
        snapshot_map: Dict[str, Dict] = {}

        chunk_size = 400
        for idx in range(0, len(codes), chunk_size):
            batch = codes[idx : idx + chunk_size]
            self.snapshot_limiter.acquire()
            try:
                ret, data = client.get_market_snapshot(batch)
            except Exception as exc:
                logger.warning("futu_get_snapshot_failed", error=str(exc))
                continue

            if not self._is_ret_ok(ret):
                logger.warning("futu_get_snapshot_failed", error=str(data))
                continue

            records = self.dataframe_to_records(data)
            for rec in records:
                code = rec.get("code") or rec.get("option_code")
                if code:
                    snapshot_map[str(code)] = rec

        return snapshot_map

    def fetch_option_chain_with_retry(
        self,
        code: str,
        start_date: Optional[str],
        end_date: Optional[str],
        option_type: Any,
        max_retries: int = 2,
    ) -> Tuple[Any, Any]:
        client = self.connection.get_client()
        if client is None:
            return -1, "futu not connected"

        last_data: Any = None
        ret: Any = -1
        for attempt in range(max_retries + 1):
            self.chain_limiter.acquire()
            ret, data = self.get_option_chain_window(
                client=client,
                code=code,
                start_date=start_date,
                end_date=end_date,
                option_type=option_type,
            )
            last_data = data
            if self._is_ret_ok(ret):
                return ret, data

            text = str(data).lower()
            if ("频率太高" in str(data) or "too frequent" in text) and attempt < max_retries:
                time.sleep(30.0)
                continue
            return ret, data

        return ret, last_data

    @staticmethod
    def get_option_chain_window(
        client: Any,
        code: str,
        start_date: Optional[str],
        end_date: Optional[str],
        option_type: Any,
    ) -> Tuple[Any, Any]:
        variants: List[Dict[str, str]] = []
        positional_variants: List[Tuple[str, ...]] = []
        if start_date and end_date:
            variants = [
                {"begin_time": start_date, "end_time": end_date},
                {"start_time": start_date, "end_time": end_date},
                {"start_date": start_date, "end_date": end_date},
                {"start": start_date, "end": end_date},
            ]
            positional_variants.append((start_date, end_date))
        positional_variants.append(())
        last_error: Optional[Exception] = None

        for variant in variants:
            try:
                kwargs = {"option_type": option_type, **variant}
                return client.get_option_chain(code, **kwargs)
            except TypeError as exc:
                last_error = exc
                continue

        for args in positional_variants:
            try:
                kwargs = {"option_type": option_type}
                return client.get_option_chain(code, *args, **kwargs)
            except TypeError as exc:
                last_error = exc
                continue

        raise TypeError(f"get_option_chain argument mismatch: {last_error}")

    def _append_contracts(
        self,
        expirations: Dict[str, List[OptionContract]],
        records: List[Dict],
        option_type: Any,
        seen_contracts: set[Tuple[str, str]],
        start_date: Any,
        end_date: Any,
    ) -> None:
        for record in records:
            expiry = self.get_expiry_date(record)
            option_code = self.get_option_code(record)
            if not expiry or not option_code:
                continue

            expiry_date = self.parse_date(expiry)
            if expiry_date is None:
                continue
            if expiry_date < start_date or expiry_date > end_date:
                continue

            key = (expiry, option_code)
            if key in seen_contracts:
                continue
            seen_contracts.add(key)
            expirations[expiry].append(
                OptionContract(
                    code=option_code,
                    option_type=self.get_record_option_type(record, fallback=option_type),
                )
            )

    def _record_chain_fetch_failure(
        self,
        meta: OptionChainFetchMeta,
        option_type: Any,
        start_date: Optional[str],
        end_date: Optional[str],
        error: Any,
    ) -> None:
        detail = {
            "option_type": str(option_type),
            "start_date": start_date or "",
            "end_date": end_date or "",
            "error": str(error),
        }
        if len(meta.failed_details) < 12:
            meta.failed_details.append(detail)

        logger.warning(
            "futu_get_option_chain_failed",
            symbol=meta.symbol,
            option_type=str(option_type),
            start_date=start_date,
            end_date=end_date,
            error=str(error),
        )

    def _count_near_term_contracts(
        self,
        expirations: Dict[str, List[OptionContract]],
        today: Any,
        max_day: int = 90,
    ) -> int:
        total = 0
        for expiry_str, contracts in expirations.items():
            expiry_date = self.parse_date(expiry_str)
            if not expiry_date:
                continue
            dte = (expiry_date - today).days
            if dte <= 0 or dte > max_day:
                continue
            total += len(contracts)
        return total

    def _max_contract_dte(
        self,
        expirations: Dict[str, List[OptionContract]],
        today: Any,
    ) -> Optional[int]:
        max_dte: Optional[int] = None
        for expiry_str in expirations.keys():
            expiry_date = self.parse_date(expiry_str)
            if not expiry_date:
                continue
            dte = (expiry_date - today).days
            if dte <= 0:
                continue
            if max_dte is None or dte > max_dte:
                max_dte = dte
        return max_dte

    @staticmethod
    def format_code(symbol: str, market: str) -> str:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_market = str(market or "").strip().upper()
        if not normalized_symbol:
            return normalized_symbol
        if normalized_market and normalized_symbol.startswith(f"{normalized_market}."):
            return normalized_symbol
        if "." in normalized_symbol and normalized_symbol.split(".", 1)[0] in {"US", "HK", "SH", "SZ"}:
            return normalized_symbol
        market_prefix = normalized_market or "US"
        return f"{market_prefix}.{normalized_symbol}"

    @staticmethod
    def dataframe_to_records(data: Any) -> List[Dict]:
        if hasattr(data, "to_dict"):
            return data.to_dict("records")
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def get_expiry_date(record: Dict) -> Optional[str]:
        for key in ("expiry_date", "expire_date", "expiration_date", "expiry", "strike_time", "strike_date"):
            value = record.get(key)
            if value:
                return str(value).split(" ")[0]
        return None

    @staticmethod
    def get_option_code(record: Dict) -> Optional[str]:
        for key in ("code", "option_code", "contract_code", "security_code"):
            value = record.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def get_record_option_type(record: Dict, fallback: Any = None) -> Any:
        for key in ("option_type", "type", "contract_type"):
            value = record.get(key)
            if value is not None:
                return value
        return fallback

    @staticmethod
    def get_snapshot_value(snapshot: Dict, keys: List[str]) -> Optional[float]:
        for key in keys:
            if key in snapshot and snapshot[key] is not None:
                try:
                    return float(snapshot[key])
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def normalize_iv(iv_value: float) -> float:
        iv = float(iv_value)
        if iv <= 1.5:
            return iv * 100.0
        return iv

    @staticmethod
    def parse_date(value: str) -> Optional[Any]:
        text = str(value).strip()
        if not text:
            return None

        # Normalize common datetime-like strings.
        if " " in text:
            text = text.split(" ")[0]
        if "T" in text:
            text = text.split("T")[0]

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except Exception:
                continue
        return None

    @staticmethod
    def fmt_iv(value: Optional[float]) -> str:
        if value is None:
            return "N/A"
        return f"{value:.2f}"

    @staticmethod
    def _is_ret_ok(ret: Any) -> bool:
        if RET_OK is None:
            return ret == 0
        return ret == RET_OK
