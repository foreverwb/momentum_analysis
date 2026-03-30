from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.etfs import (
    ETF_REFRESH_COOLDOWN_MINUTES,
    HOLDINGS_REFRESH_COOLDOWN_MINUTES,
    HoldingsCoverageRequest,
    format_etf_response,
    refresh_etf_data,
    refresh_holdings_by_coverage,
)
from app.models.database import Base, ETF, ETFHolding, IVData, ImportedData, PriceHistory, ScoreSnapshot, Stock
from app.services.broker.futu.iv_calculator import IVTermResult


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _persist_price_frame(
    db_session,
    symbol: str,
    frame: pd.DataFrame,
    *,
    source: str = "ibkr",
    created_at: datetime | None = None,
):
    persisted_at = created_at or datetime.utcnow()
    for _, row in frame.iterrows():
        row_date = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        db_session.add(
            PriceHistory(
                symbol=symbol,
                date=row_date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                source=source,
                created_at=persisted_at,
            )
        )


@pytest.mark.asyncio
async def test_refresh_etf_data_skips_when_ibkr_and_futu_recent(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=71.2,
        rank=1,
        completeness=80.0,
    )
    db_session.add(etf)
    db_session.flush()

    db_session.add(
        PriceHistory(
            symbol="XLK",
            date=today,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source="ibkr",
            created_at=now - timedelta(minutes=5),
        )
    )
    db_session.add(
        IVData(
            symbol="XLK",
            date=today,
            iv7=18.0,
            iv30=20.0,
            iv60=21.0,
            iv90=22.0,
            total_oi=10000,
            source="futu",
            created_at=now - timedelta(minutes=4),
        )
    )
    db_session.add(
        ScoreSnapshot(
            symbol="XLK",
            symbol_type="etf",
            date=today,
            total_score=71.2,
            score_breakdown={
                "rel_mom": {"score": 65, "data": {"RS_20D": 0.01}},
                "trend_quality": {"score": 75, "data": {"price_above_sma50": True}},
                "breadth": {"score": 50, "data": None},
                "options_confirm": {"score": 60, "data": {"iv30": 20.0}},
            },
            thresholds_pass=True,
        )
    )
    db_session.commit()

    result = await refresh_etf_data("XLK", db=db_session)

    assert result["status"] == "snapshot"
    assert "下次可刷新时间" in result.get("message", "")
    assert result.get("next_refresh_at")
    refresh_gate = result.get("refresh_gate") or {}
    assert refresh_gate.get("cooldown_minutes") == ETF_REFRESH_COOLDOWN_MINUTES
    assert (refresh_gate.get("ibkr") or {}).get("is_recent") is True
    assert (refresh_gate.get("futu") or {}).get("is_recent") is True


@pytest.mark.asyncio
async def test_refresh_etf_data_snapshot_recalculates_breadth_score(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=64.0,
        rank=1,
        completeness=70.0,
    )
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )

    bullish_finviz = {
        "symbol": "AAPL",
        "price": 100.0,
        "sma20": 0.05,
        "sma50": 0.06,
        "sma200": 0.08,
        "week52_high": 102.0,
        "week52_low": 80.0,
        "rsi": 62.0,
    }
    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={**bullish_finviz, "symbol": ticker},
                created_at=now,
            )
        )

    db_session.add(
        PriceHistory(
            symbol="XLK",
            date=today,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source="ibkr",
            created_at=now - timedelta(minutes=5),
        )
    )
    db_session.add(
        IVData(
            symbol="XLK",
            date=today,
            iv7=18.0,
            iv30=20.0,
            iv60=21.0,
            iv90=22.0,
            total_oi=10000,
            source="futu",
            created_at=now - timedelta(minutes=4),
        )
    )
    db_session.add(
        ScoreSnapshot(
            symbol="XLK",
            symbol_type="etf",
            date=today,
            total_score=64.0,
            score_breakdown={
                "rel_mom": {"score": 65, "data": {"RS_20D": 0.01}},
                "trend_quality": {"score": 75, "data": {"price_above_sma50": True}},
                "breadth": {"score": 50, "data": None},
                "options_confirm": {"score": 60, "data": {"iv30": 20.0}},
            },
            thresholds_pass=True,
        )
    )
    db_session.commit()

    result = await refresh_etf_data("XLK", db=db_session)

    refreshed_etf = db_session.query(ETF).filter(ETF.symbol == "XLK").first()
    refreshed_snapshot = db_session.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == "XLK",
        ScoreSnapshot.symbol_type == "etf",
        ScoreSnapshot.date == today,
    ).first()

    assert result["status"] == "snapshot"
    assert result["score"] == pytest.approx(74.0)
    assert result["breakdown"]["breadth"]["score"] == pytest.approx(100.0)
    assert refreshed_etf is not None
    assert refreshed_etf.score == pytest.approx(74.0)
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.total_score == pytest.approx(74.0)


@pytest.mark.asyncio
async def test_refresh_etf_data_ibkr_source_skips_when_ibkr_recent_only(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=71.2,
        rank=1,
        completeness=80.0,
    )
    db_session.add(etf)
    db_session.flush()

    db_session.add(
        PriceHistory(
            symbol="XLK",
            date=today,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source="ibkr",
            created_at=now - timedelta(minutes=5),
        )
    )
    db_session.add(
        ScoreSnapshot(
            symbol="XLK",
            symbol_type="etf",
            date=today,
            total_score=71.2,
            score_breakdown={
                "rel_mom": {"score": 65, "data": {"RS_20D": 0.01}},
                "trend_quality": {"score": 75, "data": {"price_above_sma50": True}},
                "breadth": {"score": 50, "data": None},
                "options_confirm": {"score": 50, "data": None},
            },
            thresholds_pass=True,
        )
    )
    db_session.commit()

    result = await refresh_etf_data("XLK", refresh_source="ibkr", db=db_session)

    assert result["status"] == "snapshot"
    assert result["refresh_source"] == "ibkr"
    assert "IBKR 数据在" in result.get("message", "")
    assert result.get("next_refresh_at")
    refresh_gate = result.get("refresh_gate") or {}
    assert (refresh_gate.get("ibkr") or {}).get("is_recent") is True
    assert (refresh_gate.get("futu") or {}).get("is_recent") is False


@pytest.mark.asyncio
async def test_refresh_etf_data_ibkr_source_does_not_recalculate_score(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=64.0,
        rank=1,
        completeness=70.0,
    )
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )
    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={
                    "symbol": ticker,
                    "price": 100.0,
                    "sma20": 0.05,
                    "sma50": 0.06,
                    "sma200": 0.08,
                    "week52_high": 102.0,
                    "week52_low": 80.0,
                    "rsi": 62.0,
                },
                created_at=now,
            )
        )

    db_session.add(
        PriceHistory(
            symbol="XLK",
            date=today,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source="ibkr",
            created_at=now - timedelta(minutes=5),
        )
    )
    db_session.add(
        ScoreSnapshot(
            symbol="XLK",
            symbol_type="etf",
            date=today,
            total_score=64.0,
            score_breakdown={
                "rel_mom": {"score": 65, "data": {"RS_20D": 0.01}},
                "trend_quality": {"score": 75, "data": {"price_above_sma50": True}},
                "breadth": {"score": 50, "data": None},
                "options_confirm": {"score": 50, "data": None},
            },
            thresholds_pass=True,
        )
    )
    db_session.commit()

    result = await refresh_etf_data("XLK", refresh_source="ibkr", db=db_session)

    refreshed_etf = db_session.query(ETF).filter(ETF.symbol == "XLK").first()
    refreshed_snapshot = db_session.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == "XLK",
        ScoreSnapshot.symbol_type == "etf",
        ScoreSnapshot.date == today,
    ).first()

    assert result["status"] == "snapshot"
    assert result["score"] == pytest.approx(64.0)
    assert refreshed_etf is not None
    assert refreshed_etf.score == pytest.approx(64.0)
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.total_score == pytest.approx(64.0)
    assert refreshed_snapshot.score_breakdown["breadth"]["data"] is None


@pytest.mark.asyncio
async def test_refresh_etf_data_ibkr_source_persists_price_dimensions(monkeypatch, db_session):
    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=0.0,
        rank=1,
        completeness=0.0,
    )
    db_session.add(etf)
    db_session.commit()

    orchestrator = _ETFRefreshOrchestrator(
        relmom_result={
            "RS": 1.15,
            "RS_5D": 0.02,
            "RS_20D": 0.04,
            "RS_63D": 0.10,
            "RelMom": 0.08,
        },
        price_frame=_price_frame_with_step("XLK", periods=100, base=120.0, step=1.5),
    )
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_etf_data("XLK", refresh_source="ibkr", db=db_session)

    refreshed_snapshot = db_session.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == "XLK",
        ScoreSnapshot.symbol_type == "etf",
    ).order_by(ScoreSnapshot.date.desc(), ScoreSnapshot.id.desc()).first()

    assert result["status"] == "success"
    assert "完成评分计算" in result["message"]
    assert result["data_sources"]["ibkr_price"] is True
    assert result["data_sources"]["ibkr_relmom"] is True
    assert result["data_sources"]["ibkr_trend"] is True
    assert result["breakdown"]["rel_mom"]["data"]["RelMom"] == pytest.approx(0.08)
    assert result["breakdown"]["trend_quality"]["data"] is not None
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.score_breakdown["rel_mom"]["data"]["RelMom"] == pytest.approx(0.08)
    assert refreshed_snapshot.score_breakdown["trend_quality"]["data"] is not None


@pytest.mark.asyncio
async def test_refresh_etf_data_ibkr_source_refreshes_latest_bar_timestamp(monkeypatch, db_session):
    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=0.0,
        rank=1,
        completeness=0.0,
    )
    db_session.add(etf)
    db_session.commit()

    price_frame = _price_frame_with_step("XLK", periods=100, base=120.0, step=1.5)
    stale_created_at = datetime.utcnow() - timedelta(days=2)
    _persist_price_frame(
        db_session,
        "XLK",
        price_frame,
        created_at=stale_created_at,
    )
    db_session.commit()

    orchestrator = _ETFRefreshOrchestrator(
        relmom_result={
            "RS": 1.15,
            "RS_5D": 0.02,
            "RS_20D": 0.04,
            "RS_63D": 0.10,
            "RelMom": 0.08,
        },
        price_frame=price_frame,
    )
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_etf_data("XLK", refresh_source="ibkr", db=db_session)

    latest_created_at = db_session.query(func.max(PriceHistory.created_at)).filter(
        PriceHistory.symbol == "XLK",
        PriceHistory.source == "ibkr",
    ).scalar()
    payload = format_etf_response(etf, include_holdings=False, db=db_session)

    assert result["status"] == "success"
    assert latest_created_at is not None
    assert latest_created_at > stale_created_at
    assert payload["sourceUpdatedAt"]["ibkr"] is not None


@pytest.mark.asyncio
async def test_refresh_etf_data_futu_snapshot_backfills_missing_ibkr_dimensions(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=0.0,
        rank=1,
        completeness=0.0,
    )
    db_session.add(etf)
    db_session.flush()

    _persist_price_frame(
        db_session,
        "XLK",
        _price_frame_with_step("XLK", periods=100, base=120.0, step=1.8),
        created_at=now - timedelta(minutes=30),
    )
    _persist_price_frame(
        db_session,
        "SPY",
        _price_frame_with_step("SPY", periods=100, base=400.0, step=0.6),
        created_at=now - timedelta(minutes=30),
    )
    db_session.add(
        IVData(
            symbol="XLK",
            date=today,
            iv7=18.0,
            iv30=20.0,
            iv60=21.0,
            iv90=22.0,
            total_oi=10000,
            source="futu",
            created_at=now - timedelta(minutes=5),
        )
    )
    db_session.add(
        ScoreSnapshot(
            symbol="XLK",
            symbol_type="etf",
            date=today,
            total_score=0.0,
            score_breakdown={
                "rel_mom": {"score": 0.0, "data": None},
                "trend_quality": {"score": 0.0, "data": None},
                "breadth": {"score": 50.0, "data": None},
                "options_confirm": {"score": 50.0, "data": None},
            },
            thresholds_pass=False,
        )
    )
    db_session.commit()

    result = await refresh_etf_data("XLK", refresh_source="futu", db=db_session)

    refreshed_snapshot = db_session.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == "XLK",
        ScoreSnapshot.symbol_type == "etf",
        ScoreSnapshot.date == today,
    ).first()

    assert result["status"] == "snapshot"
    assert result["breakdown"]["rel_mom"]["data"] is not None
    assert result["breakdown"]["trend_quality"]["data"] is not None
    assert result["data_sources"]["ibkr_relmom"] is True
    assert result["data_sources"]["ibkr_trend"] is True
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.score_breakdown["rel_mom"]["data"] is not None
    assert refreshed_snapshot.score_breakdown["trend_quality"]["data"] is not None


@pytest.mark.asyncio
async def test_refresh_holdings_by_coverage_skips_when_ibkr_and_futu_recent(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )

    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            PriceHistory(
                symbol=ticker,
                date=today,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
                source="ibkr",
                created_at=now - timedelta(minutes=20),
            )
        )
        db_session.add(
            IVData(
                symbol=ticker,
                date=today,
                iv7=18.0,
                iv30=20.0,
                iv60=21.0,
                iv90=22.0,
                total_oi=10000,
                source="futu",
                created_at=now - timedelta(minutes=20),
            )
        )
    db_session.commit()

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2),
        db=db_session,
    )

    assert result["status"] == "snapshot"
    assert result["stocks_count"] == 2
    assert "下次可刷新时间" in result.get("message", "")
    assert result.get("next_refresh_at")
    refresh_gate = result.get("refresh_gate") or {}
    assert refresh_gate.get("cooldown_minutes") == HOLDINGS_REFRESH_COOLDOWN_MINUTES


@pytest.mark.asyncio
async def test_refresh_holdings_by_coverage_ibkr_source_skips_when_ibkr_recent_only(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )

    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            PriceHistory(
                symbol=ticker,
                date=today,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
                source="ibkr",
                created_at=now - timedelta(minutes=20),
            )
        )
    db_session.commit()

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(
            coverage_type="top",
            coverage_value=2,
            refresh_source="ibkr",
        ),
        db=db_session,
    )

    assert result["status"] == "snapshot"
    assert result["refresh_source"] == "ibkr"
    assert result["stocks_count"] == 2
    assert "IBKR 数据在" in result.get("message", "")
    refresh_gate = result.get("refresh_gate") or {}
    assert (refresh_gate.get("ibkr") or {}).get("all_recent") is True
    assert (refresh_gate.get("futu") or {}).get("all_recent") is False


@pytest.mark.asyncio
async def test_refresh_holdings_snapshot_recalculates_etf_score(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(
        symbol="XLK",
        name="Technology",
        type="sector",
        score=64.0,
        rank=1,
        completeness=70.0,
    )
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )

    bullish_finviz = {
        "price": 100.0,
        "sma20": 0.05,
        "sma50": 0.06,
        "sma200": 0.08,
        "week52_high": 102.0,
        "week52_low": 80.0,
        "rsi": 62.0,
    }
    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={**bullish_finviz, "symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            PriceHistory(
                symbol=ticker,
                date=today,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
                source="ibkr",
                created_at=now - timedelta(minutes=20),
            )
        )
        db_session.add(
            IVData(
                symbol=ticker,
                date=today,
                iv7=18.0,
                iv30=20.0,
                iv60=21.0,
                iv90=22.0,
                total_oi=10000,
                source="futu",
                created_at=now - timedelta(minutes=20),
            )
        )

    db_session.add(
        ScoreSnapshot(
            symbol="XLK",
            symbol_type="etf",
            date=today,
            total_score=64.0,
            score_breakdown={
                "rel_mom": {"score": 65, "data": {"RS_20D": 0.01}},
                "trend_quality": {"score": 75, "data": {"price_above_sma50": True}},
                "breadth": {"score": 50, "data": None},
                "options_confirm": {"score": 60, "data": {"iv30": 20.0}},
            },
            thresholds_pass=True,
        )
    )
    db_session.commit()

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2),
        db=db_session,
    )

    refreshed_etf = db_session.query(ETF).filter(ETF.symbol == "XLK").first()
    refreshed_snapshot = db_session.query(ScoreSnapshot).filter(
        ScoreSnapshot.symbol == "XLK",
        ScoreSnapshot.symbol_type == "etf",
        ScoreSnapshot.date == today,
    ).first()

    assert result["status"] == "snapshot"
    assert refreshed_etf is not None
    assert refreshed_etf.score == pytest.approx(74.0)
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.total_score == pytest.approx(74.0)


@pytest.mark.asyncio
async def test_refresh_holdings_by_coverage_supports_all_scope(db_session):
    now = datetime.utcnow()
    today = date.today()

    etf = ETF(symbol="XLF", name="Financials", type="sector")
    db_session.add(etf)
    db_session.flush()

    holdings = [
        ETFHolding(etf_id=etf.id, etf_symbol="XLF", ticker="JPM", weight=8.0, data_date=today),
        ETFHolding(etf_id=etf.id, etf_symbol="XLF", ticker="BRK.B", weight=7.0, data_date=today),
        ETFHolding(etf_id=etf.id, etf_symbol="XLF", ticker="GS", weight=3.5, data_date=today),
    ]
    db_session.add_all(holdings)

    for ticker in ("JPM", "BRK.B", "GS"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            PriceHistory(
                symbol=ticker,
                date=today,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
                source="ibkr",
                created_at=now - timedelta(minutes=20),
            )
        )
        db_session.add(
            IVData(
                symbol=ticker,
                date=today,
                iv7=18.0,
                iv30=20.0,
                iv60=21.0,
                iv90=22.0,
                total_oi=10000,
                source="futu",
                created_at=now - timedelta(minutes=20),
            )
        )
    db_session.commit()

    result = await refresh_holdings_by_coverage(
        "XLF",
        HoldingsCoverageRequest(coverage_type="all", coverage_value=0),
        db=db_session,
    )

    assert result["status"] == "snapshot"
    assert result["coverage"] == "all"
    assert result["stocks_count"] == 3


class _DummyOrchestrator:
    _futu = None

    def get_broker_status(self):
        return {
            "ibkr": {"is_connected": False},
            "futu": {"is_connected": False},
        }

    async def connect_ibkr(self):
        return False

    async def connect_futu(self):
        return False

    async def get_ohlcv_data(self, symbol, duration):  # pragma: no cover - safety fallback
        return None

    async def calculate_momentum_pool_score(self, **kwargs):  # pragma: no cover - safety fallback
        return None


class _BatchFutuStub:
    def __init__(self, payload_by_symbol):
        self.payload_by_symbol = payload_by_symbol
        self.calls = []

    def is_connected(self):
        return True

    def fetch_iv_terms(self, symbols, **kwargs):
        normalized = [str(symbol).upper() for symbol in symbols]
        self.calls.append({"symbols": normalized, "kwargs": dict(kwargs)})
        return {
            symbol: self.payload_by_symbol.get(symbol, IVTermResult())
            for symbol in normalized
        }


class _BatchOrchestrator(_DummyOrchestrator):
    def __init__(self, futu):
        self._futu = futu

    def get_broker_status(self):
        return {
            "ibkr": {"is_connected": False},
            "futu": {"is_connected": True},
        }

    async def connect_futu(self):
        return True


class _FutuScoreOrchestrator(_DummyOrchestrator):
    def __init__(self, futu):
        self._futu = futu
        self.pool_calls = []

    def get_broker_status(self):
        return {
            "ibkr": {"is_connected": False, "last_error": "not connected"},
            "futu": {"is_connected": True},
        }

    async def connect_futu(self):
        return True

    async def calculate_momentum_pool_score(self, **kwargs):
        self.pool_calls.append(kwargs)
        return {
            "symbol": kwargs.get("symbol"),
            "sector_etf": kwargs.get("sector_etf"),
            "total_score": 68.0,
            "scores": {"momentum": 55.0, "trend": 58.0},
            "metrics": {},
        }


def _price_frame(symbol: str, periods: int = 80) -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=periods, freq="B")
    base = float(sum(ord(ch) for ch in symbol[:4])) / 10.0
    closes = [base + idx * 0.5 for idx in range(periods)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1_000_000 + idx * 1000 for idx in range(periods)],
        }
    )


def _price_frame_with_step(
    symbol: str,
    *,
    periods: int = 80,
    base: float = 100.0,
    step: float = 1.0,
) -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=periods, freq="B")
    closes = [base + idx * step for idx in range(periods)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1_000_000 + idx * 1000 for idx in range(periods)],
        }
    )


class _IBKRReuseOrchestrator(_DummyOrchestrator):
    def __init__(self):
        self._futu = None
        self.ohlcv_calls = []
        self.pool_calls = []

    def get_broker_status(self):
        return {
            "ibkr": {"is_connected": True},
            "futu": {"is_connected": False, "last_error": "not connected"},
        }

    async def connect_ibkr(self):
        return True

    async def connect_futu(self):
        return False

    async def get_ohlcv_data(self, symbol, duration):
        self.ohlcv_calls.append((str(symbol).upper(), duration))
        return _price_frame(str(symbol).upper())

    async def calculate_momentum_pool_score(self, **kwargs):
        self.pool_calls.append(kwargs)
        return {
            "symbol": kwargs.get("symbol"),
            "sector_etf": kwargs.get("sector_etf"),
            "total_score": 72.0,
            "scores": {"momentum": 60.0, "trend": 60.0},
            "metrics": {},
        }


class _ETFRefreshOrchestrator(_DummyOrchestrator):
    def __init__(self, *, relmom_result=None, price_frame=None):
        self.relmom_result = relmom_result or {
            "RS": 1.15,
            "RS_5D": 0.02,
            "RS_20D": 0.04,
            "RS_63D": 0.10,
            "RelMom": 0.08,
        }
        self.price_frame = price_frame if price_frame is not None else _price_frame("XLK", periods=100)
        self.ohlcv_calls = []
        self.relmom_calls = []

    def get_broker_status(self):
        return {
            "ibkr": {"is_connected": True},
            "futu": {"is_connected": False},
        }

    async def connect_ibkr(self):
        return True

    async def get_ohlcv_data(self, symbol, duration):
        self.ohlcv_calls.append((str(symbol).upper(), duration))
        return self.price_frame.copy()

    async def calculate_relative_momentum(self, symbol, benchmark="SPY", duration="80 D"):
        self.relmom_calls.append((str(symbol).upper(), str(benchmark).upper(), duration))
        return dict(self.relmom_result)


@pytest.mark.asyncio
async def test_refresh_holdings_related_scope_uses_same_coverage(monkeypatch, db_session):
    now = datetime.utcnow()
    today = date.today()

    sector = ETF(symbol="XLK", name="Technology", type="sector")
    industry = ETF(symbol="SOXX", name="Semiconductor", type="industry", parent_sector="XLK")
    db_session.add_all([sector, industry])
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=industry.id,
                etf_symbol="SOXX",
                ticker="AAA",
                weight=60.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=industry.id,
                etf_symbol="SOXX",
                ticker="BBB",
                weight=40.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=sector.id,
                etf_symbol="XLK",
                ticker="BBB",
                weight=90.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=sector.id,
                etf_symbol="XLK",
                ticker="AAA",
                weight=10.0,
                data_date=today,
            ),
        ]
    )

    db_session.add(
        ImportedData(
            symbol="AAA",
            date=today,
            source="finviz",
            data={"symbol": "AAA"},
            created_at=now,
        )
    )
    db_session.add(
        ImportedData(
            symbol="AAA",
            date=today,
            source="marketchameleon",
            data={"symbol": "AAA"},
            created_at=now,
        )
    )
    db_session.add(
        PriceHistory(
            symbol="AAA",
            date=today,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
            source="ibkr",
            created_at=now - timedelta(minutes=10),
        )
    )
    db_session.add(
        IVData(
            symbol="AAA",
            date=today,
            iv7=18.0,
            iv30=20.0,
            iv60=21.0,
            iv90=22.0,
            total_oi=10000,
            source="futu",
            created_at=now - timedelta(minutes=10),
        )
    )
    db_session.commit()

    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: _DummyOrchestrator())

    result = await refresh_holdings_by_coverage(
        "SOXX",
        HoldingsCoverageRequest(
            coverage_type="top",
            coverage_value=1,
            related_etf_symbols=["XLK"],
        ),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["stocks_count"] == 1
    assert result["duplicate_scope_count"] == 0
    assert result["skipped_recent_count"] == 0
    assert result["refreshed_stocks_count"] == 1


@pytest.mark.asyncio
async def test_refresh_holdings_batches_futu_iv_fetch(monkeypatch, db_session):
    today = date.today()
    now = datetime.utcnow()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )
    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
    db_session.commit()

    futu = _BatchFutuStub(
        {
            "AAPL": IVTermResult(iv7=18.0, iv30=20.0, iv60=21.0, iv90=22.0, total_oi=1000),
            "MSFT": IVTermResult(iv7=17.0, iv30=19.0, iv60=20.0, iv90=21.0, total_oi=2000),
        }
    )
    orchestrator = _BatchOrchestrator(futu=futu)
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["stocks_count"] == 2
    assert result["refreshed_stocks_count"] == 2
    assert result["futu_failed_count"] == 0
    assert len(futu.calls) == 1
    assert set(futu.calls[0]["symbols"]) == {"AAPL", "MSFT"}
    assert futu.calls[0]["kwargs"]["max_retries"] == 0
    assert futu.calls[0]["kwargs"]["log_progress"] is True
    assert futu.calls[0]["kwargs"]["log_fetch_summary"] is False

    rows = db_session.query(IVData).filter(IVData.symbol.in_(["AAPL", "MSFT"])).all()
    row_map = {row.symbol: row for row in rows}
    assert set(row_map) == {"AAPL", "MSFT"}
    assert row_map["AAPL"].iv30 == 20.0
    assert row_map["MSFT"].iv30 == 19.0


@pytest.mark.asyncio
async def test_refresh_holdings_reuses_prefetched_ibkr_frames(monkeypatch, db_session):
    today = date.today()
    now = datetime.utcnow()

    etf = ETF(symbol="XLF", name="Financials", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLF",
                ticker="JPM",
                weight=8.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLF",
                ticker="BAC",
                weight=6.0,
                data_date=today,
            ),
        ]
    )
    for ticker in ("JPM", "BAC"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
    db_session.commit()

    orchestrator = _IBKRReuseOrchestrator()
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLF",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["futu_failed_count"] == 2
    assert orchestrator.ohlcv_calls.count(("XLF", "1 Y")) == 1
    assert orchestrator.ohlcv_calls.count(("JPM", "1 Y")) == 1
    assert orchestrator.ohlcv_calls.count(("BAC", "1 Y")) == 1
    assert len(orchestrator.ohlcv_calls) == 3
    assert len(orchestrator.pool_calls) == 2
    assert all(call.get("price_df") is not None for call in orchestrator.pool_calls)
    assert all(call.get("sector_df") is not None for call in orchestrator.pool_calls)


@pytest.mark.asyncio
async def test_refresh_holdings_ibkr_source_skips_import_guard(monkeypatch, db_session):
    today = date.today()

    etf = ETF(symbol="XLF", name="Financials", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLF",
                ticker="JPM",
                weight=8.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLF",
                ticker="BAC",
                weight=6.0,
                data_date=today,
            ),
        ]
    )
    db_session.commit()

    orchestrator = _IBKRReuseOrchestrator()
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLF",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2, refresh_source="ibkr"),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["refresh_source"] == "ibkr"
    assert "未触发评分计算" in result["message"]
    assert orchestrator.pool_calls == []
    assert db_session.query(PriceHistory).filter(PriceHistory.symbol.in_(["JPM", "BAC"])).count() > 0


@pytest.mark.asyncio
async def test_refresh_holdings_futu_source_still_requires_fresh_imports(db_session):
    today = date.today()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await refresh_holdings_by_coverage(
            "XLK",
            HoldingsCoverageRequest(coverage_type="top", coverage_value=2, refresh_source="futu"),
            db=db_session,
        )

    assert exc_info.value.status_code == 400
    assert "Finviz 与 MarketChameleon 最新数据" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_refresh_holdings_futu_source_allows_excluded_missing_imports(monkeypatch, db_session):
    today = date.today()
    now = datetime.utcnow()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )
    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
    db_session.add(
        ImportedData(
            symbol="MSFT",
            date=today,
            source="marketchameleon",
            data={"symbol": "MSFT"},
            created_at=now,
        )
    )

    for symbol in ("XLK", "AAPL", "MSFT"):
        frame = _price_frame(symbol)
        for _, row in frame.iterrows():
            row_date = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            db_session.add(
                PriceHistory(
                    symbol=symbol,
                    date=row_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                    source="ibkr",
                    created_at=now - timedelta(days=1),
                )
            )
    db_session.commit()

    futu = _BatchFutuStub(
        {
            "AAPL": IVTermResult(iv7=18.0, iv30=20.0, iv60=21.0, iv90=22.0, total_oi=1000),
            "MSFT": IVTermResult(iv7=17.0, iv30=19.0, iv60=20.0, iv90=21.0, total_oi=2000),
        }
    )
    orchestrator = _FutuScoreOrchestrator(futu=futu)
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(
            coverage_type="top",
            coverage_value=2,
            refresh_source="futu",
            exclude_symbols=["AAPL"],
        ),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["refresh_source"] == "futu"
    assert len(orchestrator.pool_calls) == 2
    assert db_session.query(Stock).filter(Stock.symbol.in_(["AAPL", "MSFT"])).count() == 2


@pytest.mark.asyncio
async def test_refresh_holdings_ibkr_source_refreshes_data_without_scoring(monkeypatch, db_session):
    today = date.today()
    now = datetime.utcnow()

    etf = ETF(symbol="XLF", name="Financials", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLF",
                ticker="JPM",
                weight=8.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLF",
                ticker="BAC",
                weight=6.0,
                data_date=today,
            ),
        ]
    )
    for ticker in ("JPM", "BAC"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
    db_session.commit()

    orchestrator = _IBKRReuseOrchestrator()
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLF",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2, refresh_source="ibkr"),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["refresh_source"] == "ibkr"
    assert "未触发评分计算" in result["message"]
    assert orchestrator.ohlcv_calls.count(("XLF", "1 Y")) == 1
    assert orchestrator.ohlcv_calls.count(("JPM", "1 Y")) == 1
    assert orchestrator.ohlcv_calls.count(("BAC", "1 Y")) == 1
    assert orchestrator.pool_calls == []
    assert db_session.query(Stock).count() == 0
    assert db_session.query(PriceHistory).filter(PriceHistory.symbol.in_(["JPM", "BAC"])).count() > 0


@pytest.mark.asyncio
async def test_refresh_holdings_futu_source_uses_cached_prices_to_score(monkeypatch, db_session):
    today = date.today()
    now = datetime.utcnow()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="AAPL",
                weight=6.0,
                data_date=today,
            ),
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker="MSFT",
                weight=5.0,
                data_date=today,
            ),
        ]
    )
    for ticker in ("AAPL", "MSFT"):
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )

    for symbol in ("XLK", "AAPL", "MSFT"):
        frame = _price_frame(symbol)
        for _, row in frame.iterrows():
            row_date = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            db_session.add(
                PriceHistory(
                    symbol=symbol,
                    date=row_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                    source="ibkr",
                    created_at=now - timedelta(days=1),
                )
            )
    db_session.commit()

    futu = _BatchFutuStub(
        {
            "AAPL": IVTermResult(iv7=18.0, iv30=20.0, iv60=21.0, iv90=22.0, total_oi=1000),
            "MSFT": IVTermResult(iv7=17.0, iv30=19.0, iv60=20.0, iv90=21.0, total_oi=2000),
        }
    )
    orchestrator = _FutuScoreOrchestrator(futu=futu)
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=2, refresh_source="futu"),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["refresh_source"] == "futu"
    assert len(orchestrator.pool_calls) == 2
    assert db_session.query(Stock).filter(Stock.symbol.in_(["AAPL", "MSFT"])).count() == 2
    assert any(stock.get("score") is not None for stock in result["updated_stocks"])


@pytest.mark.asyncio
async def test_refresh_holdings_splits_futu_requests_into_small_batches(monkeypatch, db_session):
    today = date.today()
    now = datetime.utcnow()

    etf = ETF(symbol="XLK", name="Technology", type="sector")
    db_session.add(etf)
    db_session.flush()

    tickers = ["AAPL", "MSFT", "NVDA", "AVGO", "AMD"]
    db_session.add_all(
        [
            ETFHolding(
                etf_id=etf.id,
                etf_symbol="XLK",
                ticker=ticker,
                weight=10.0 - idx,
                data_date=today,
            )
            for idx, ticker in enumerate(tickers)
        ]
    )
    for ticker in tickers:
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="finviz",
                data={"symbol": ticker},
                created_at=now,
            )
        )
        db_session.add(
            ImportedData(
                symbol=ticker,
                date=today,
                source="marketchameleon",
                data={"symbol": ticker},
                created_at=now,
            )
        )
    db_session.commit()

    futu = _BatchFutuStub({ticker: IVTermResult(iv30=20.0, total_oi=1000) for ticker in tickers})
    orchestrator = _BatchOrchestrator(futu=futu)
    monkeypatch.setattr("app.services.orchestrator.get_orchestrator", lambda: orchestrator)

    result = await refresh_holdings_by_coverage(
        "XLK",
        HoldingsCoverageRequest(coverage_type="top", coverage_value=5),
        db=db_session,
    )

    assert result["status"] == "success"
    assert result["stocks_count"] == 5
    assert len(futu.calls) == 2
    assert len(futu.calls[0]["symbols"]) == 4
    assert len(futu.calls[1]["symbols"]) == 1
