from __future__ import annotations

from typing import Dict, List

import pandas as pd

from app.services.calculators.etf_score import ETFScoreCalculator, rank_percentile_normalize


class _DummyIBKR:
    def __init__(self, relmom_map: Dict[str, float]):
        self._relmom_map = relmom_map

    def analyze_sector_vs_spy(self, symbol: str, benchmark: str = "SPY") -> Dict[str, float]:
        rel_mom = self._relmom_map[symbol]
        return {
            "RelMom": rel_mom,
            "RS_20D": 0.05,
            "RS": 1.02,
            "RS_5D": 0.01,
            "RS_63D": 0.10,
        }

    def get_price_data(self, symbol: str, duration: str = "100 D") -> pd.DataFrame:
        # 平滑上升序列，确保 trend_quality 各 ETF 一致
        values = [100 + i * 0.6 for i in range(80)]
        return pd.DataFrame({symbol: values})


def _make_holdings(positive_sma50_count: int, total: int = 10) -> List[Dict]:
    rows: List[Dict] = []
    for idx in range(total):
        rows.append(
            {
                "symbol": f"S{idx}",
                "price": 100.0,
                "sma20": 0.01 if idx < positive_sma50_count else -0.01,
                "sma50": 0.02 if idx < positive_sma50_count else -0.02,
                "sma200": 0.01,
                "week52_high": 105.0 if idx < positive_sma50_count else 130.0,
            }
        )
    return rows


def test_rank_percentile_normalize_is_monotonic() -> None:
    raw = {"A": -0.03, "B": 0.01, "C": 0.08, "D": 0.15}
    normalized = rank_percentile_normalize(raw)
    assert normalized["A"] <= normalized["B"] <= normalized["C"] <= normalized["D"]


def test_batch_rel_mom_percentile_monotonic() -> None:
    symbols = ["ETF_A", "ETF_B", "ETF_C"]
    ibkr = _DummyIBKR({"ETF_A": -0.02, "ETF_B": 0.03, "ETF_C": 0.09})
    calc = ETFScoreCalculator(ibkr=ibkr)

    holdings_map = {symbol: _make_holdings(positive_sma50_count=7) for symbol in symbols}
    results = calc.batch_calculate_scores(symbols=symbols, holdings_map=holdings_map)
    by_symbol = {item["symbol"]: item for item in results}

    ordered = sorted(
        symbols,
        key=lambda s: by_symbol[s]["breakdown"]["raw_features"]["rel_mom_raw"],
    )
    normalized_scores = [
        by_symbol[s]["breakdown"]["normalized_features"]["rel_mom_normalized"]
        for s in ordered
    ]

    assert normalized_scores[0] <= normalized_scores[1] <= normalized_scores[2]


def test_missing_module_weight_is_redistributed() -> None:
    symbols = ["ETF_X", "ETF_Y"]
    ibkr = _DummyIBKR({"ETF_X": 0.01, "ETF_Y": 0.02})
    calc = ETFScoreCalculator(ibkr=ibkr)

    results = calc.batch_calculate_scores(
        symbols=symbols,
        holdings_map={
            "ETF_X": _make_holdings(positive_sma50_count=8),
            # ETF_Y 不给 breadth 数据，验证自动重分配
        },
    )
    by_symbol = {item["symbol"]: item for item in results}
    y_payload = by_symbol["ETF_Y"]

    normalized_features = y_payload["breakdown"]["normalized_features"]
    assert normalized_features["breadth_normalized"] is None

    allocation = y_payload["breakdown"]["weight_allocation"]
    assert "breadth" not in allocation
    assert abs(sum(allocation.values()) - 1.0) < 1e-6


def test_breadth_raw_is_monotonic_when_pct_above_50_increases() -> None:
    ibkr = _DummyIBKR({"ETF_BREADTH": 0.02})
    calc = ETFScoreCalculator(ibkr=ibkr)

    low = calc.calculate_breadth_score("ETF_BREADTH", _make_holdings(positive_sma50_count=3))
    high = calc.calculate_breadth_score("ETF_BREADTH", _make_holdings(positive_sma50_count=8))

    assert low["raw_score"] is not None
    assert high["raw_score"] is not None
    assert high["raw_score"] >= low["raw_score"]
