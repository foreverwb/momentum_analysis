from app.services.calculators.stock_score import StockScoreCalculator


class _DummyIBKR:
    pass


def test_finviz_sma50_deviation_positive_marks_price_above() -> None:
    calc = StockScoreCalculator(ibkr=_DummyIBKR())
    result = calc._calculate_technical_from_finviz(
        {
            "symbol": "TEST",
            "price": 100.0,
            "sma20": 0.08,
            "sma50": 0.05,   # +5%: price above SMA50
            "sma200": 0.02,
            "rsi": 55.0,
            "week52_high": 110.0,
        }
    )

    assert result["data"]["price_above_sma50"] is True
    assert result["data"]["sma50_dev"] == 0.05


def test_finviz_sma50_deviation_negative_marks_price_below() -> None:
    calc = StockScoreCalculator(ibkr=_DummyIBKR())
    result = calc._calculate_technical_from_finviz(
        {
            "symbol": "TEST",
            "price": 100.0,
            "sma20": -0.01,
            "sma50": -0.05,  # -5%: price below SMA50
            "sma200": 0.01,
            "rsi": 55.0,
            "week52_high": 110.0,
        }
    )

    assert result["data"]["price_above_sma50"] is False
    assert result["data"]["sma50_dev"] == -0.05

