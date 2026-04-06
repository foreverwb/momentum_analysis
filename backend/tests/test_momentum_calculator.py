"""
Offline unit tests for MomentumCalculator.

These tests load the module directly from file path to avoid unrelated
runtime side-effects from package-level imports.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/calculators/momentum.py"
SPEC = importlib.util.spec_from_file_location("momentum_module", MODULE_PATH)
MOMENTUM_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MOMENTUM_MODULE)
MomentumCalculator = MOMENTUM_MODULE.MomentumCalculator


def _make_price_df(symbol: str, prices: np.ndarray) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"date": dates, symbol: prices})


def test_calculate_relative_strength_columns_and_values() -> None:
    sector_prices = np.linspace(100.0, 200.0, 90)
    benchmark_prices = np.linspace(50.0, 100.0, 90)

    sector_df = _make_price_df("XLK", sector_prices)
    benchmark_df = _make_price_df("SPY", benchmark_prices)

    rs_df = MomentumCalculator.calculate_relative_strength(sector_df, benchmark_df)

    assert rs_df is not None
    assert "RS" in rs_df.columns
    assert "RS_5D_change" in rs_df.columns
    assert "RS_20D_change" in rs_df.columns
    assert "RS_63D_change" in rs_df.columns
    assert rs_df["RS"].iloc[-1] == pytest.approx(2.0)
    # 5D 不跳过，线性等比增长 → pct_change(5) ≈ 0
    assert rs_df["RS_5D_change"].iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_skip_week_rs_20d_ignores_recent_crash() -> None:
    """最近5天RS暴跌，但跳过后20D变化仍为正。"""
    n = 80
    # 前75天 RS 稳步上升 (1.0→1.5)，最后5天暴跌到 1.0
    sector_prices = np.concatenate([np.linspace(100, 150, n - 5), np.linspace(100, 100, 5)])
    benchmark_prices = np.full(n, 100.0)

    sector_df = _make_price_df("XLK", sector_prices)
    benchmark_df = _make_price_df("SPY", benchmark_prices)

    rs_df = MomentumCalculator.calculate_relative_strength(sector_df, benchmark_df)
    assert rs_df is not None

    last = rs_df.iloc[-1]
    # RS_5D_change 反映近期暴跌 → 负值
    assert last["RS_5D_change"] < 0
    # RS_20D_change 跳过最近5天 → 仍为正（之前20天在上升）
    assert last["RS_20D_change"] > 0


def test_calculate_rel_mom_weighted_formula() -> None:
    rs_df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "RS_5D_change": [0.10, 0.00, -0.05],
            "RS_20D_change": [0.20, 0.10, -0.10],
            "RS_63D_change": [0.30, 0.20, -0.20],
        }
    )

    out = MomentumCalculator.calculate_rel_mom(rs_df)

    assert out is not None
    assert "RelMom" in out.columns
    expected_last = 0.20 * (-0.05) + 0.45 * (-0.10) + 0.35 * (-0.20)
    assert out["RelMom"].iloc[-1] == pytest.approx(expected_last)


def test_calculate_relative_momentum_handles_nan_data() -> None:
    sector_prices = np.array([100, 101, np.nan, 103, 104, 106, np.nan, 108, 109, 110], dtype=float)
    benchmark_prices = np.array([50, 0, 51, np.nan, 52, 53, 54, 55, np.nan, 56], dtype=float)

    sector_df = _make_price_df("XLK", sector_prices)
    benchmark_df = _make_price_df("SPY", benchmark_prices)

    result = MomentumCalculator.calculate_relative_momentum(sector_df, benchmark_df)

    assert result is not None
    for key in ["date", "RS", "RS_5D", "RS_20D", "RS_63D", "RelMom"]:
        assert key in result
    assert isinstance(result["RelMom"], float)

