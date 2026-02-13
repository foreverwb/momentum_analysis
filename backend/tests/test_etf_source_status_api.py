from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.etfs import format_etf_response
from app.models.database import Base, ETF, IVData, ImportedData, PriceHistory


def test_format_etf_response_includes_fresh_etf_level_source_updated_at() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    try:
        now = datetime.utcnow()
        today = date.today()

        etf = ETF(symbol="XLK", name="Technology", type="sector")
        db.add(etf)
        db.flush()

        db.add(
            ImportedData(
                symbol="XLK",
                date=today,
                source="finviz",
                data={"symbol": "XLK"},
                created_at=now,
            )
        )
        db.add(
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
        db.add(
            IVData(
                symbol="XLK",
                date=today,
                iv30=20.0,
                total_oi=10000,
                source="futu",
                created_at=now - timedelta(minutes=4),
            )
        )
        db.commit()

        payload = format_etf_response(etf, include_holdings=False, db=db)

        assert payload["sourceUpdatedAt"]["finviz"] is not None
        assert payload["sourceUpdatedAt"]["marketchameleon"] is None
        assert payload["sourceUpdatedAt"]["ibkr"] is not None
        assert payload["sourceUpdatedAt"]["futu"] is not None
    finally:
        db.close()
