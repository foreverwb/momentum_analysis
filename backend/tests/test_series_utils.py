import os
import sys
from datetime import date, datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.series_utils import build_metric_series, resolve_latest_trade_date
from app.models import Base, ETF, PriceHistory, ScoreSnapshot, Stock


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session_local()


def test_resolve_latest_trade_date_reads_dataframe_date_column() -> None:
    frame = pd.DataFrame(
        {
            "date": [
                date(2026, 3, 10),
                datetime(2026, 3, 11, 16, 0, 0),
            ],
            "close": [100.0, 101.0],
        }
    )

    assert resolve_latest_trade_date(frame) == date(2026, 3, 11)


def test_build_metric_series_score_uses_trading_calendar_and_forward_fills_values() -> None:
    db = _make_session()
    try:
        db.add_all(
            [
                Stock(symbol="AAA"),
                ETF(symbol="BBB", name="Benchmark", type="industry"),
            ]
        )
        db.add_all(
            [
                PriceHistory(symbol="AAA", date=date(2026, 3, 10), close=10.0, source="ibkr"),
                PriceHistory(symbol="AAA", date=date(2026, 3, 11), close=11.0, source="ibkr"),
                PriceHistory(symbol="AAA", date=date(2026, 3, 12), close=12.0, source="ibkr"),
                PriceHistory(symbol="AAA", date=date(2026, 3, 13), close=13.0, source="ibkr"),
                PriceHistory(symbol="BBB", date=date(2026, 3, 10), close=20.0, source="ibkr"),
                PriceHistory(symbol="BBB", date=date(2026, 3, 11), close=21.0, source="ibkr"),
                PriceHistory(symbol="BBB", date=date(2026, 3, 12), close=22.0, source="ibkr"),
                PriceHistory(symbol="BBB", date=date(2026, 3, 13), close=23.0, source="ibkr"),
                ScoreSnapshot(symbol="AAA", symbol_type="stock", date=date(2026, 3, 7), total_score=41.0),
                ScoreSnapshot(symbol="AAA", symbol_type="stock", date=date(2026, 3, 12), total_score=59.0),
                ScoreSnapshot(symbol="BBB", symbol_type="etf", date=date(2026, 3, 11), total_score=70.0),
            ]
        )
        db.commit()

        dates, series = build_metric_series(db, ["AAA", "BBB"], 4, metric="score", label_tz="market")

        assert dates == ["3/10", "3/11", "3/12", "3/13"]
        assert series[0] == {"symbol": "AAA", "values": [41.0, 41.0, 59.0, 59.0]}
        assert series[1] == {"symbol": "BBB", "values": [None, 70.0, 70.0, 70.0]}
    finally:
        db.close()


def test_build_metric_series_score_clamps_snapshot_date_to_latest_trade_date() -> None:
    db = _make_session()
    try:
        db.add(Stock(symbol="AAA"))
        db.add(ETF(symbol="BBB", name="Benchmark", type="industry"))
        db.add_all(
            [
                PriceHistory(symbol="AAA", date=date(2026, 3, 10), close=10.0, source="ibkr"),
                PriceHistory(symbol="BBB", date=date(2026, 3, 10), close=20.0, source="ibkr"),
                PriceHistory(symbol="BBB", date=date(2026, 3, 11), close=21.0, source="ibkr"),
                ScoreSnapshot(symbol="AAA", symbol_type="stock", date=date(2026, 3, 11), total_score=80.0),
            ]
        )
        db.commit()

        dates, series = build_metric_series(db, ["AAA", "BBB"], 2, metric="score", label_tz="market")

        assert dates == ["3/10", "3/11"]
        assert series[0] == {"symbol": "AAA", "values": [80.0, 80.0]}
        assert series[1] == {"symbol": "BBB", "values": [None, None]}
    finally:
        db.close()


def test_build_metric_series_defaults_to_beijing_labels() -> None:
    db = _make_session()
    try:
        db.add(Stock(symbol="AAA"))
        db.add_all(
            [
                PriceHistory(symbol="AAA", date=date(2026, 3, 10), close=10.0, source="ibkr"),
                PriceHistory(symbol="AAA", date=date(2026, 3, 11), close=11.0, source="ibkr"),
            ]
        )
        db.commit()

        dates, series = build_metric_series(db, ["AAA"], 2, metric="relative")

        assert dates == ["3/11", "3/12"]
        assert series[0] == {"symbol": "AAA", "values": [0.0, 10.0]}
    finally:
        db.close()
