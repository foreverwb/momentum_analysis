from __future__ import annotations

from datetime import datetime, timedelta

from app.services.broker.futu.iv_calculator import FutuIVCalculator
from app.services.broker.futu.options_data import (
    FutuOptionsDataFetcher,
    OptionChainFetchMeta,
    OptionContract,
)


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
        oi_cache_file="/tmp/futu_oi_cache_test.json",
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
        oi_cache_file="/tmp/futu_oi_cache_test.json",
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
