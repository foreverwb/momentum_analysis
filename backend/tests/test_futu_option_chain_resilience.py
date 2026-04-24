from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.api import etfs as etfs_api
from app.core.time_utils import beijing_today
from app.services.broker.futu.iv_calculator import FutuIVCalculator, IVTermResult
from app.services.broker.futu import iv_calculator as iv_calculator_module
from app.services.broker.futu import options_data as options_data_module
from app.services.broker.futu.options_data import (
    FUTU_CONTRACT_CATALOG_TABLE,
    FutuOptionsDataFetcher,
    OptionChainFetchMeta,
    OptionContract,
)
from app.services.broker.futu.utils import OPTION_TYPE


class _DummyConnection:
    def __init__(self, client):
        self._client = client
        self.market = "US"

    def get_client(self):
        return self._client

    def is_connected(self):
        return True

    def connect(self):
        return True


class _WindowOnlyClient:
    def get_option_chain(self, code, *args, **kwargs):
        # Simulate SDK/OpenD incompatibility for full-chain call.
        if not args and all(k not in kwargs for k in ("begin_time", "start_time", "start_date", "start")):
            return -1, "full-chain call unsupported"

        expiry = (datetime.now().date() + timedelta(days=14)).strftime("%Y-%m-%d")
        return 0, [
            {"expiry_date": expiry, "code": "US.TEST240101C100"},
            {"expiry_date": expiry, "code": "US.TEST240101P100"},
        ]


def test_collect_expirations_fallback_to_windowed_when_full_chain_fails():
    connection = _DummyConnection(_WindowOnlyClient())
    fetcher = FutuOptionsDataFetcher(connection=connection)

    expirations, meta = fetcher.collect_expirations_with_meta(
        symbol="TEST",
        max_days=30,
        window_days=30,
        option_types=["CALL"],
    )

    assert expirations
    assert meta.failed_requests >= 1
    assert meta.success_requests >= 1
    assert meta.strategy in {"mixed", "windowed"}
    assert meta.total_contracts >= 1


class _CombinedOptionTypeClient:
    def get_option_chain(self, code, *args, **kwargs):
        assert kwargs.get("option_type") == OPTION_TYPE.ALL
        expiry = (datetime.now().date() + timedelta(days=14)).strftime("%Y-%m-%d")
        return 0, [
            {"expiry_date": expiry, "code": "US.TEST240101C100", "option_type": "CALL"},
            {"expiry_date": expiry, "code": "US.TEST240101P100", "option_type": "PUT"},
        ]


def test_collect_expirations_prefers_combined_option_type_when_available():
    connection = _DummyConnection(_CombinedOptionTypeClient())
    fetcher = FutuOptionsDataFetcher(connection=connection)

    expirations, meta = fetcher.collect_expirations_with_meta(symbol="TEST", max_days=30, window_days=30)

    contracts = next(iter(expirations.values()))
    assert len(contracts) == 2
    assert {str(contract.option_type).upper() for contract in contracts} == {"CALL", "PUT"}
    assert meta.total_requests == 1


class _FullNearTermClient:
    def get_option_chain(self, code, *args, **kwargs):
        today = datetime.now().date()
        near_expiry = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        far_expiry = (today + timedelta(days=75)).strftime("%Y-%m-%d")

        # Full-chain call returns only near-term contracts.
        if not args and all(k not in kwargs for k in ("begin_time", "start_time", "start_date", "start")):
            return 0, [{"expiry_date": near_expiry, "code": "US.TEST240101C100"}]

        # Windowed call supplements farther expirations.
        start = kwargs.get("begin_time") or kwargs.get("start_time") or kwargs.get("start_date") or kwargs.get("start")
        if args and not start:
            start = args[0]
        if start and start >= (today + timedelta(days=31)).strftime("%Y-%m-%d"):
            return 0, [{"expiry_date": far_expiry, "code": "US.TEST240301C100"}]
        return 0, []


def test_collect_expirations_supplements_far_term_when_full_chain_truncated():
    connection = _DummyConnection(_FullNearTermClient())
    fetcher = FutuOptionsDataFetcher(connection=connection)

    expirations, meta = fetcher.collect_expirations_with_meta(
        symbol="TEST",
        max_days=120,
        window_days=30,
        option_types=["CALL"],
    )

    assert expirations
    assert meta.strategy == "mixed"
    dtes = sorted(
        (
            datetime.strptime(expiry, "%Y-%m-%d").date() - datetime.now().date()
        ).days
        for expiry in expirations.keys()
    )
    assert any(dte >= 60 for dte in dtes)


class _FarTermOnlyFetcher:
    def collect_expirations_with_meta(self, symbol, max_days, window_days, option_types, log_fetch_summary=True):
        far_expiry = (datetime.now().date() + timedelta(days=150)).strftime("%Y-%m-%d")
        return (
            {
                far_expiry: [OptionContract(code="US.TEST240101C100", option_type="CALL")],
            },
            OptionChainFetchMeta(
                symbol=symbol,
                strategy="mixed",
                total_requests=4,
                success_requests=1,
                failed_requests=3,
            ),
        )

    def fetch_snapshot_map(self, expirations):
        return {
            "US.TEST240101C100": {
                "option_delta": 0.5,
                "option_implied_volatility": 0.45,
                "option_open_interest": 123456,
            }
        }

    @staticmethod
    def parse_date(value: str):
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def get_snapshot_value(snapshot, keys):
        for key in keys:
            if key in snapshot and snapshot[key] is not None:
                return float(snapshot[key])
        return None

    @staticmethod
    def normalize_iv(iv_value: float):
        return float(iv_value) * 100.0 if iv_value <= 1.5 else float(iv_value)


def test_iv_terms_return_empty_when_only_far_term_chain_available():
    connection = _DummyConnection(client=object())
    calculator = FutuIVCalculator(
        connection=connection,
        options_fetcher=_FarTermOnlyFetcher(),
        oi_cache_file="/tmp/futu_oi_cache_test.db",
    )

    result = calculator._fetch_symbol_iv_terms(symbol="TEST", max_days=120, window_days=30)

    assert result.iv7 is None
    assert result.iv30 is None
    assert result.iv60 is None
    assert result.iv90 is None
    assert result.total_oi is None


def test_interpolate_iv_rejects_large_one_sided_extrapolation():
    assert FutuIVCalculator._interpolate_iv([(120, 46.43)], 7) is None
    assert FutuIVCalculator._interpolate_iv([(120, 46.43)], 90) is None
    assert FutuIVCalculator._interpolate_iv([(35, 48.0)], 30) == 48.0


class _BucketSplitFetcher:
    def collect_expirations_with_meta(self, symbol, max_days, window_days, option_types, log_fetch_summary=True):
        today = datetime.now().date()
        expiry_0_7 = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        expiry_8_30 = (today + timedelta(days=20)).strftime("%Y-%m-%d")
        expiry_31_90 = (today + timedelta(days=60)).strftime("%Y-%m-%d")
        return (
            {
                expiry_0_7: [
                    OptionContract(code="US.TEST0C100", option_type="CALL"),
                    OptionContract(code="US.TEST0P100", option_type="PUT"),
                ],
                expiry_8_30: [
                    OptionContract(code="US.TEST1C100", option_type="CALL"),
                    OptionContract(code="US.TEST1P100", option_type="PUT"),
                ],
                expiry_31_90: [
                    OptionContract(code="US.TEST2C100", option_type="CALL"),
                    OptionContract(code="US.TEST2P100", option_type="PUT"),
                ],
            },
            OptionChainFetchMeta(symbol=symbol, strategy="full", total_requests=2, success_requests=2, failed_requests=0),
        )

    def fetch_snapshot_map(self, expirations):
        return {
            "US.TEST0C100": {"option_open_interest": 100, "option_delta": 0.5, "option_implied_volatility": 0.40},
            "US.TEST0P100": {"option_open_interest": 40},
            "US.TEST1C100": {"option_open_interest": 200, "option_delta": 0.52, "option_implied_volatility": 0.42},
            "US.TEST1P100": {"option_open_interest": 80},
            "US.TEST2C100": {"option_open_interest": 300, "option_delta": 0.49, "option_implied_volatility": 0.44},
            "US.TEST2P100": {"option_open_interest": 120},
        }

    @staticmethod
    def parse_date(value: str):
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def get_snapshot_value(snapshot, keys):
        for key in keys:
            if key in snapshot and snapshot[key] is not None:
                return float(snapshot[key])
        return None

    @staticmethod
    def normalize_iv(iv_value: float):
        return float(iv_value) * 100.0 if iv_value <= 1.5 else float(iv_value)


def test_fetch_iv_terms_exposes_call_put_bucket_split():
    connection = _DummyConnection(client=object())
    calculator = FutuIVCalculator(
        connection=connection,
        options_fetcher=_BucketSplitFetcher(),
        oi_cache_file="/tmp/futu_oi_cache_test.db",
    )

    result = calculator._fetch_symbol_iv_terms(symbol="TEST", max_days=120, window_days=30, log_fetch_summary=False)

    assert result.oi_bucket_0_7 == 140
    assert result.oi_bucket_8_30 == 280
    assert result.oi_bucket_31_90 == 420
    assert result.call_oi_bucket_0_7 == 100
    assert result.call_oi_bucket_8_30 == 200
    assert result.call_oi_bucket_31_90 == 300
    assert result.put_oi_bucket_0_7 == 40
    assert result.put_oi_bucket_8_30 == 80
    assert result.put_oi_bucket_31_90 == 120
    assert result.total_oi == 840


def test_resolve_option_side_falls_back_to_contract_code():
    assert FutuIVCalculator._resolve_option_side(option_type="UNKNOWN", option_code="US.AAPL260320C00190000") == "call"
    assert FutuIVCalculator._resolve_option_side(option_type="UNKNOWN", option_code="US.AAPL260320P00190000") == "put"


def test_pick_atm_iv_uses_call_side_from_combined_chain_records():
    connection = _DummyConnection(client=object())
    calculator = FutuIVCalculator(
        connection=connection,
        options_fetcher=FutuOptionsDataFetcher(connection=connection),
        oi_cache_file="/tmp/futu_oi_cache_test.db",
    )

    contracts = [
        OptionContract(code="US.TEST240101C100", option_type=OPTION_TYPE.ALL),
        OptionContract(code="US.TEST240101P100", option_type=OPTION_TYPE.ALL),
    ]
    snapshot_map = {
        "US.TEST240101C100": {"option_delta": 0.51, "option_implied_volatility": 0.40},
        "US.TEST240101P100": {"option_delta": -0.49, "option_implied_volatility": 0.60},
    }

    assert calculator._pick_atm_iv(contracts, snapshot_map) == 40.0


def test_compute_bucket_delta_payload_uses_delta_notional_change_formula():
    connection = _DummyConnection(client=object())
    calculator = FutuIVCalculator(
        connection=connection,
        options_fetcher=FutuOptionsDataFetcher(connection=connection),
        oi_cache_file="/tmp/futu_oi_cache_test.db",
    )
    today = datetime(2026, 1, 15).date()
    result = IVTermResult(total_oi=15, risk_total_oi=90000)
    result._snapshot_payload = {
        "total_oi": 15,
        "risk_total_oi": 90000,
        "buckets": {
            "0_7": {"net": None, "call": None, "put": None, "risk_net": None},
            "8_30": {"net": 15, "call": 15, "put": None, "risk_net": 90000},
            "31_90": {"net": None, "call": None, "put": None, "risk_net": None},
        },
        "contracts": {
            "US.TEST260215C00100000": {
                "oi": 15,
                "bucket": "8_30",
                "side": "call",
                "risk_weight": 6000.0,
            },
        },
    }
    cache = {
        "TEST": {
            "2026-01-14": {
                "total_oi": 10,
                "risk_total_oi": 50000,
                "buckets": {
                    "0_7": {"net": None, "call": None, "put": None, "risk_net": None},
                    "8_30": {"net": 10, "call": 10, "put": None, "risk_net": 50000},
                    "31_90": {"net": None, "call": None, "put": None, "risk_net": None},
                },
                "contracts": {
                    "US.TEST260215C00100000": {
                        "oi": 10,
                        "bucket": "8_30",
                        "side": "call",
                        "risk_weight": 5000.0,
                    },
                },
            },
        },
    }

    payload = calculator._compute_bucket_delta_payload(
        symbol="TEST",
        today=today,
        result=result,
        cache=cache,
    )

    assert payload["total_oi_1d"] == 30000
    assert payload["by_bucket"]["8_30"]["net_1d"] == 30000
    assert payload["by_bucket"]["8_30"]["call_1d"] == 30000
    assert payload["by_bucket"]["8_30"]["put_1d"] is None


class _CatalogSnapshotClient:
    def __init__(self):
        self.option_chain_calls = 0
        self.snapshot_calls = []

    def get_option_chain(self, code, *args, **kwargs):
        self.option_chain_calls += 1
        today = datetime.now().date()
        expiries = [
            (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            (today + timedelta(days=20)).strftime("%Y-%m-%d"),
            (today + timedelta(days=60)).strftime("%Y-%m-%d"),
        ]
        return 0, [
            {"expiry_date": expiries[0], "code": "US.TEST0C100", "option_type": "CALL", "strike_price": 100},
            {"expiry_date": expiries[0], "code": "US.TEST0P100", "option_type": "PUT", "strike_price": 100},
            {"expiry_date": expiries[1], "code": "US.TEST1C100", "option_type": "CALL", "strike_price": 100},
            {"expiry_date": expiries[1], "code": "US.TEST1P100", "option_type": "PUT", "strike_price": 100},
            {"expiry_date": expiries[2], "code": "US.TEST2C100", "option_type": "CALL", "strike_price": 100},
            {"expiry_date": expiries[2], "code": "US.TEST2P100", "option_type": "PUT", "strike_price": 100},
        ]

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(list(codes))
        payload = []
        snapshot_map = {
            "US.TEST0C100": {"option_open_interest": 100, "option_delta": 0.50, "option_implied_volatility": 0.40},
            "US.TEST0P100": {"option_open_interest": 40},
            "US.TEST1C100": {"option_open_interest": 200, "option_delta": 0.52, "option_implied_volatility": 0.42},
            "US.TEST1P100": {"option_open_interest": 80},
            "US.TEST2C100": {"option_open_interest": 300, "option_delta": 0.49, "option_implied_volatility": 0.44},
            "US.TEST2P100": {"option_open_interest": 120},
        }
        for code in codes:
            record = dict(snapshot_map.get(code, {}))
            if record:
                record["code"] = code
                payload.append(record)
        return 0, payload


def test_contract_catalog_cache_hit_reuses_same_day_chain(tmp_path: Path):
    cache_db = tmp_path / "futu_cache.db"
    client = _CatalogSnapshotClient()
    connection = _DummyConnection(client)
    fetcher = FutuOptionsDataFetcher(connection=connection, cache_db_file=str(cache_db))
    calculator = FutuIVCalculator(
        connection=connection,
        options_fetcher=fetcher,
        oi_cache_file=str(cache_db),
    )

    first = calculator.fetch_iv_terms(["TEST"], max_days=120, max_retries=0)
    first_chain_calls = client.option_chain_calls
    second = calculator.fetch_iv_terms(["TEST"], max_days=120, max_retries=0)

    assert first["TEST"].total_oi == 840
    assert second["TEST"].total_oi == 840
    assert first_chain_calls > 0
    assert client.option_chain_calls == first_chain_calls


def test_contract_catalog_cache_stale_triggers_refresh(tmp_path: Path):
    cache_db = tmp_path / "futu_cache.db"
    client = _CatalogSnapshotClient()
    connection = _DummyConnection(client)
    fetcher = FutuOptionsDataFetcher(connection=connection, cache_db_file=str(cache_db))
    calculator = FutuIVCalculator(
        connection=connection,
        options_fetcher=fetcher,
        oi_cache_file=str(cache_db),
    )

    calculator.fetch_iv_terms(["TEST"], max_days=120, max_retries=0)
    stale_date = (beijing_today() - timedelta(days=1)).strftime("%Y-%m-%d")
    today_str = beijing_today().strftime("%Y-%m-%d")
    with sqlite3.connect(str(cache_db)) as conn:
        conn.execute(
            f"UPDATE {FUTU_CONTRACT_CATALOG_TABLE} SET cache_date = ? WHERE symbol = ? AND cache_date = ?",
            (stale_date, "TEST", today_str),
        )

    first_chain_calls = client.option_chain_calls
    calculator.fetch_iv_terms(["TEST"], max_days=120, max_retries=0)

    assert client.option_chain_calls > first_chain_calls


class _BatchAggregationFetcher:
    def __init__(self):
        today = datetime.now().date()
        self.catalogs = {
            "AAA": {
                (today + timedelta(days=5)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.SHARED0C100", option_type="CALL"),
                    OptionContract(code="US.AAA0P100", option_type="PUT"),
                ],
                (today + timedelta(days=20)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.AAA1C100", option_type="CALL"),
                    OptionContract(code="US.AAA1P100", option_type="PUT"),
                ],
            },
            "BBB": {
                (today + timedelta(days=5)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.SHARED0C100", option_type="CALL"),
                    OptionContract(code="US.BBB0P100", option_type="PUT"),
                ],
                (today + timedelta(days=60)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.BBB1C100", option_type="CALL"),
                    OptionContract(code="US.BBB1P100", option_type="PUT"),
                ],
            },
        }
        self.snapshot_requests = []

    @staticmethod
    def default_option_types():
        return ["CALL"]

    def get_or_refresh_contract_catalog(self, symbol, **kwargs):
        return self.catalogs[symbol], OptionChainFetchMeta(symbol=symbol, strategy="cache", unique_expirations=2)

    def fetch_snapshot_map_from_codes_with_failures(self, codes, chunk_size=400):
        self.snapshot_requests.append(list(codes))
        snapshot_map = {
            "US.SHARED0C100": {"option_open_interest": 100, "option_delta": 0.50, "option_implied_volatility": 0.40},
            "US.AAA0P100": {"option_open_interest": 40},
            "US.AAA1C100": {"option_open_interest": 200, "option_delta": 0.52, "option_implied_volatility": 0.42},
            "US.AAA1P100": {"option_open_interest": 80},
            "US.BBB0P100": {"option_open_interest": 60},
            "US.BBB1C100": {"option_open_interest": 300, "option_delta": 0.49, "option_implied_volatility": 0.44},
            "US.BBB1P100": {"option_open_interest": 120},
        }
        return {code: snapshot_map[code] for code in codes if code in snapshot_map}, set()

    def fetch_snapshot_map(self, expirations):
        codes = [contract.code for contracts in expirations.values() for contract in contracts]
        snapshot_map, _failed = self.fetch_snapshot_map_from_codes_with_failures(codes)
        return snapshot_map

    @staticmethod
    def parse_date(value: str):
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def get_snapshot_value(snapshot, keys):
        for key in keys:
            if key in snapshot and snapshot[key] is not None:
                return float(snapshot[key])
        return None

    @staticmethod
    def normalize_iv(iv_value: float):
        return float(iv_value) * 100.0 if iv_value <= 1.5 else float(iv_value)


def test_fetch_iv_terms_aggregates_global_snapshot_and_dedupes_codes(tmp_path: Path):
    fetcher = _BatchAggregationFetcher()
    calculator = FutuIVCalculator(
        connection=_DummyConnection(client=object()),
        options_fetcher=fetcher,
        oi_cache_file=str(tmp_path / "futu_cache.db"),
    )

    results = calculator.fetch_iv_terms(["AAA", "BBB"], max_days=120, max_retries=0)

    assert set(results) == {"AAA", "BBB"}
    assert len(fetcher.snapshot_requests) == 1
    assert fetcher.snapshot_requests[0].count("US.SHARED0C100") == 1


class _ChunkFailureClient:
    def __init__(self):
        self.snapshot_calls = []

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(list(codes))
        if "US.FAIL0C100" in codes:
            raise RuntimeError("snapshot chunk failed")
        return 0, [{"code": code, "option_open_interest": 10} for code in codes]


def test_fetch_snapshot_map_from_codes_continues_after_chunk_failure(tmp_path: Path):
    client = _ChunkFailureClient()
    fetcher = FutuOptionsDataFetcher(
        connection=_DummyConnection(client),
        cache_db_file=str(tmp_path / "futu_cache.db"),
    )

    snapshot_map, failed_codes = fetcher.fetch_snapshot_map_from_codes_with_failures(
        ["US.FAIL0C100", "US.FAIL0P100", "US.OK1C100"],
        chunk_size=2,
    )

    assert "US.FAIL0C100" in failed_codes
    assert "US.FAIL0P100" in failed_codes
    assert snapshot_map["US.OK1C100"]["option_open_interest"] == 10
    assert len(client.snapshot_calls) == 2


class _RegressionFetcher(_BatchAggregationFetcher):
    def __init__(self):
        super().__init__()
        today = datetime.now().date()
        self.catalogs = {
            "TEST": {
                (today + timedelta(days=5)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.TEST0C100", option_type="CALL"),
                    OptionContract(code="US.TEST0P100", option_type="PUT"),
                ],
                (today + timedelta(days=20)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.TEST1C100", option_type="CALL"),
                    OptionContract(code="US.TEST1P100", option_type="PUT"),
                ],
                (today + timedelta(days=60)).strftime("%Y-%m-%d"): [
                    OptionContract(code="US.TEST2C100", option_type="CALL"),
                    OptionContract(code="US.TEST2P100", option_type="PUT"),
                ],
            },
        }

    def collect_expirations_with_meta(self, symbol, max_days, window_days, option_types, log_fetch_summary=True):
        return self.catalogs[symbol], OptionChainFetchMeta(symbol=symbol, strategy="full", total_requests=1, success_requests=1)

    def fetch_snapshot_map_from_codes_with_failures(self, codes, chunk_size=400):
        self.snapshot_requests.append(list(codes))
        snapshot_map = {
            "US.TEST0C100": {"option_open_interest": 100, "option_delta": 0.50, "option_implied_volatility": 0.40},
            "US.TEST0P100": {"option_open_interest": 40},
            "US.TEST1C100": {"option_open_interest": 200, "option_delta": 0.52, "option_implied_volatility": 0.42},
            "US.TEST1P100": {"option_open_interest": 80},
            "US.TEST2C100": {"option_open_interest": 300, "option_delta": 0.49, "option_implied_volatility": 0.44},
            "US.TEST2P100": {"option_open_interest": 120},
        }
        return {code: snapshot_map[code] for code in codes if code in snapshot_map}, set()


def test_batch_fetch_iv_terms_preserves_iv_and_oi_outputs(tmp_path: Path):
    fetcher = _RegressionFetcher()
    calculator = FutuIVCalculator(
        connection=_DummyConnection(client=object()),
        options_fetcher=fetcher,
        oi_cache_file=str(tmp_path / "futu_cache.db"),
    )

    single = calculator._fetch_symbol_iv_terms("TEST", max_days=120, window_days=30, log_fetch_summary=False)
    batch = calculator.fetch_iv_terms(
        ["TEST"],
        max_days=120,
        max_retries=0,
        log_progress=False,
        log_fetch_summary=False,
    )["TEST"]

    assert batch.iv7 == single.iv7
    assert batch.iv30 == single.iv30
    assert batch.iv60 == single.iv60
    assert batch.iv90 == single.iv90
    assert batch.total_oi == single.total_oi
    assert batch.oi_bucket_0_7 == single.oi_bucket_0_7
    assert batch.oi_bucket_8_30 == single.oi_bucket_8_30
    assert batch.oi_bucket_31_90 == single.oi_bucket_31_90


def test_futu_refactor_does_not_reference_banned_interfaces():
    source_bundle = "\n".join(
        (
            inspect.getsource(options_data_module),
            inspect.getsource(iv_calculator_module),
            inspect.getsource(etfs_api),
        )
    )

    assert "get_option_expiration_date" not in source_bundle
    assert "get_stock_quote" not in source_bundle
    assert "subscribe(" not in source_bundle
