from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.stocks import get_stock_options_overlay
from app.models.database import Base, IVData, Stock


@pytest.mark.asyncio
async def test_stock_options_overlay_computes_bucket_deltas_from_iv_history() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    try:
        db.add(
            Stock(
                symbol="AAPL",
                name="Apple Inc.",
                sector="XLK",
                industry="Technology",
                metrics={},
                scores={"options": 72},
                changes={"delta3d": None, "delta5d": None},
            )
        )

        current_date = date(2026, 3, 23)
        snapshots = [
            {
                "date": current_date - timedelta(days=5),
                "call_oi_bucket_0_7": 100,
                "put_oi_bucket_0_7": 130,
                "oi_bucket_0_7": 230,
            },
            {
                "date": current_date - timedelta(days=4),
                "call_oi_bucket_0_7": 110,
                "put_oi_bucket_0_7": 150,
                "oi_bucket_0_7": 260,
            },
            {
                "date": current_date - timedelta(days=3),
                "call_oi_bucket_0_7": 120,
                "put_oi_bucket_0_7": 170,
                "oi_bucket_0_7": 290,
            },
            {
                "date": current_date - timedelta(days=2),
                "call_oi_bucket_0_7": 130,
                "put_oi_bucket_0_7": 190,
                "oi_bucket_0_7": 320,
            },
            {
                "date": current_date - timedelta(days=1),
                "call_oi_bucket_0_7": 140,
                "put_oi_bucket_0_7": 210,
                "oi_bucket_0_7": 350,
            },
            {
                "date": current_date,
                "call_oi_bucket_0_7": 160,
                "put_oi_bucket_0_7": 240,
                "oi_bucket_0_7": 400,
            },
        ]

        for snapshot in snapshots:
            db.add(
                IVData(
                    symbol="AAPL",
                    date=snapshot["date"],
                    call_oi_bucket_0_7=snapshot["call_oi_bucket_0_7"],
                    put_oi_bucket_0_7=snapshot["put_oi_bucket_0_7"],
                    oi_bucket_0_7=snapshot["oi_bucket_0_7"],
                    source="futu",
                )
            )

        db.commit()

        payload = await get_stock_options_overlay("AAPL", db)
        positioning = {
            row["bucket"]: row
            for row in payload["positioning"]
        }

        assert "0-7" in positioning
        assert positioning["0-7"]["callOI"] == 20.0
        assert positioning["0-7"]["putOI"] == 30.0
        assert positioning["0-7"]["netOI"] == 50.0
        assert positioning["0-7"]["delta3d"] == 110.0
        assert positioning["0-7"]["delta5d"] == 170.0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_stock_options_overlay_prefers_latest_iv_totals_over_stale_stock_metrics() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    try:
        db.add(
            Stock(
                symbol="NVDA",
                name="NVIDIA",
                sector="XLK",
                industry="Technology",
                metrics={
                    "call_oi_0_7": 409256.0,
                    "put_oi_0_7": 401014.0,
                    "oi_bucket_0_7": 810270.0,
                },
                scores={"options": 72},
                changes={"delta3d": None, "delta5d": None},
            )
        )

        db.add(
            IVData(
                symbol="NVDA",
                date=date(2026, 3, 23),
                call_oi_bucket_0_7=409256,
                put_oi_bucket_0_7=401014,
                oi_bucket_0_7=810270,
                source="futu",
            )
        )
        db.add(
            IVData(
                symbol="NVDA",
                date=date(2026, 3, 24),
                call_oi_bucket_0_7=531040,
                put_oi_bucket_0_7=601694,
                oi_bucket_0_7=1132734,
                source="futu",
            )
        )
        db.commit()

        payload = await get_stock_options_overlay("NVDA", db)
        positioning = {
            row["bucket"]: row
            for row in payload["positioning"]
        }

        assert positioning["0-7"]["callOI"] == 121784.0
        assert positioning["0-7"]["putOI"] == 200680.0
        assert positioning["0-7"]["netOI"] == 322464.0
    finally:
        db.close()
