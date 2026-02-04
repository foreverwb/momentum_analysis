"""
Regime gate error propagation tests.
"""

from __future__ import annotations

from app.services.calculators.regime_gate import RegimeGateCalculator


class _IBKRErrorProvider:
    def get_price_data(self, symbol: str, duration: str = "120 D"):
        return None

    def get_last_error(self, max_age_seconds: float = 15.0):
        return {
            "code": 162,
            "message": "Trading TWS session is connected from a different IP address",
            "req_id": 4,
        }


def test_regime_gate_includes_upstream_ibkr_error_when_spy_fetch_fails() -> None:
    calc = RegimeGateCalculator(_IBKRErrorProvider())

    result = calc.calculate_regime()

    assert result["status"] == "UNKNOWN"
    assert result["data"] is None
    assert "Failed to get SPY data" in str(result.get("error"))
    assert "IBKR[162]" in str(result.get("error"))
    assert "different IP address" in str(result.get("error"))

