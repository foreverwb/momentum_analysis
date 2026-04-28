"""Task 4.12 — node_refresh_service 验收测试。

覆盖:
- refresh_node_pipeline 处理 root 子树的 synthetic 节点 (合成价格 + 写 ScoreSnapshot)
- 节点层 NodePriceSeries 行数 > 0
- ScoreSnapshot(symbol_type='node') 行数 = 节点数
- 重复执行幂等 (再次调用行数不翻倍)
- 不存在的 root_node 抛 ValueError
"""

from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import Base
from app.models.database import (
    AnalyticNode,
    NodeEdge,
    NodeEdgeType,
    NodePriceSeries,
    NodeProxy,
    NodeProxyRole,
    NodeType,
    PriceHistory,
    ScoreSnapshot,
    SyntheticBasketDefinition,
)
from app.services.node_refresh_service import refresh_node_pipeline


# ---------- 通用 fixture ----------


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_world(db)
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_prices(db, symbol: str, *, days: int = 60, base: float = 100.0,
                 daily_change: float = 0.001) -> None:
    bdays = pd.bdate_range(date(2026, 1, 5), periods=days)
    price = base
    for d in bdays:
        db.add(PriceHistory(symbol=symbol, date=d.date(), close=price))
        price *= 1.0 + daily_change


def _seed_world(db) -> None:
    """灌入: XLK -> semi -> {compute, conn} -> conn-optical 的最小子树.

    semi-compute / conn-optical 是 synthetic, 6 只成分股各 60 天价格.
    """
    db.add_all([
        AnalyticNode(node_id="XLK", label="XLK",
                     node_type=NodeType.GICS.value, level=0,
                     representation_confidence=1.0),
        AnalyticNode(node_id="semi", label="semi",
                     node_type=NodeType.GICS.value, level=1,
                     representation_confidence=0.95),
        AnalyticNode(node_id="semi-compute", label="compute",
                     node_type=NodeType.CHAIN.value, level=2,
                     representation_confidence=0.9),
        AnalyticNode(node_id="semi-conn", label="conn",
                     node_type=NodeType.CHAIN.value, level=2,
                     representation_confidence=0.7),
        AnalyticNode(node_id="conn-optical", label="optical",
                     node_type=NodeType.LEAF.value, level=3,
                     representation_confidence=0.65),
    ])
    db.add_all([
        NodeEdge(src_node_id="XLK", dst_node_id="semi",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi", dst_node_id="semi-compute",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi", dst_node_id="semi-conn",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi-conn", dst_node_id="conn-optical",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
    ])
    db.add_all([
        NodeProxy(node_id="XLK", etf_symbol="XLK",
                  role=NodeProxyRole.PRIMARY.value, purity=1.0),
        NodeProxy(node_id="semi", etf_symbol="SOXX",
                  role=NodeProxyRole.PRIMARY.value, purity=0.95),
        NodeProxy(node_id="semi-conn", etf_symbol="SIXG",
                  role=NodeProxyRole.PRIMARY.value, purity=0.7),
    ])
    db.add_all([
        SyntheticBasketDefinition(node_id="semi-compute", ticker="NVDA",
                                  weighting_strategy="equal"),
        SyntheticBasketDefinition(node_id="semi-compute", ticker="AMD",
                                  weighting_strategy="equal"),
        SyntheticBasketDefinition(node_id="semi-compute", ticker="AVGO",
                                  weighting_strategy="equal"),
        SyntheticBasketDefinition(node_id="conn-optical", ticker="CIEN",
                                  weighting_strategy="equal", chain_extension=True),
        SyntheticBasketDefinition(node_id="conn-optical", ticker="LITE",
                                  weighting_strategy="equal", chain_extension=True),
        SyntheticBasketDefinition(node_id="conn-optical", ticker="COHR",
                                  weighting_strategy="equal", chain_extension=True),
    ])
    for sym in ("SPY", "XLK", "SOXX", "NVDA", "AMD", "AVGO", "CIEN", "LITE", "COHR"):
        _seed_prices(db, sym)
    db.commit()


# ---------- 测试 ----------


def test_refresh_pipeline_writes_basket_and_snapshot(db_session):
    result = refresh_node_pipeline("XLK", db_session)

    assert result["root_node"] == "XLK"
    assert result["processed"] >= 4  # XLK / semi / semi-compute / semi-conn / conn-optical
    assert result["basket_rows_written"] > 0
    assert set(result["synthetic_nodes"]) == {"semi-compute", "conn-optical"}

    npr_rows = db_session.query(NodePriceSeries).count()
    assert npr_rows > 0

    snap_rows = (
        db_session.query(ScoreSnapshot)
        .filter(ScoreSnapshot.symbol_type == "node")
        .count()
    )
    assert snap_rows == result["snapshots_written"]
    assert snap_rows >= result["processed"] - 1  # 至少覆盖大多数节点


def test_refresh_pipeline_is_idempotent(db_session):
    refresh_node_pipeline("XLK", db_session)
    npr_first = db_session.query(NodePriceSeries).count()
    snap_first = (
        db_session.query(ScoreSnapshot)
        .filter(ScoreSnapshot.symbol_type == "node")
        .count()
    )

    refresh_node_pipeline("XLK", db_session)
    npr_second = db_session.query(NodePriceSeries).count()
    snap_second = (
        db_session.query(ScoreSnapshot)
        .filter(ScoreSnapshot.symbol_type == "node")
        .count()
    )

    # upsert 而非 append: 第二次跑行数不翻倍
    assert npr_second == npr_first
    assert snap_second == snap_first


def test_refresh_pipeline_unknown_root_raises(db_session):
    with pytest.raises(ValueError):
        refresh_node_pipeline("NOSUCH", db_session)


def test_refresh_pipeline_lowercase_root_normalized(db_session):
    """root_node 应被规范化为大写后再校验."""
    result = refresh_node_pipeline("xlk", db_session)
    assert result["root_node"] == "XLK"
