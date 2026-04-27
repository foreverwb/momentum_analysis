"""节点层模型 (analytic_nodes / node_edges / node_proxies /
synthetic_basket_definitions / node_price_series) 单元测试"""

from datetime import date

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.database import (
    AnalyticNode,
    Base,
    NodeEdge,
    NodeEdgeType,
    NodePriceSeries,
    NodeProxy,
    NodeProxyRole,
    NodeType,
    SyntheticBasketDefinition,
)


@pytest.fixture()
def session():
    """每个测试一个独立的内存 SQLite 数据库"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _make_node(node_id: str, node_type: NodeType = NodeType.GICS, **kwargs) -> AnalyticNode:
    return AnalyticNode(
        node_id=node_id,
        label=kwargs.pop("label", node_id),
        node_type=node_type.value,
        level=kwargs.pop("level", 0),
        **kwargs,
    )


# ---------- 1. 建表 ----------

def test_all_five_node_tables_created(session):
    inspector = inspect(session.bind)
    tables = set(inspector.get_table_names())
    assert {
        "analytic_nodes",
        "node_edges",
        "node_proxies",
        "synthetic_basket_definitions",
        "node_price_series",
    }.issubset(tables)


# ---------- 2. AnalyticNode.node_id 唯一 ----------

def test_analytic_node_id_unique(session):
    session.add(_make_node("semi", label="半导体"))
    session.commit()

    session.add(_make_node("semi", label="dup"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------- 3. NodeEdge (src, dst, type) 唯一 ----------

def test_node_edge_triple_unique(session):
    session.add_all([
        _make_node("XLK"),
        _make_node("semi", node_type=NodeType.GICS, level=1),
    ])
    session.commit()

    session.add(NodeEdge(
        src_node_id="XLK",
        dst_node_id="semi",
        edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value,
    ))
    session.commit()

    # 同一 (src, dst, type) 三元组重复 -> 失败
    session.add(NodeEdge(
        src_node_id="XLK",
        dst_node_id="semi",
        edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # 同 src/dst 但不同 edge_type -> 允许
    session.add(NodeEdge(
        src_node_id="XLK",
        dst_node_id="semi",
        edge_type=NodeEdgeType.OVERLAPS_WITH.value,
        weight=0.6,
    ))
    session.commit()
    edges = session.query(NodeEdge).filter_by(src_node_id="XLK", dst_node_id="semi").all()
    assert len(edges) == 2


# ---------- 4. 一个节点可以有 primary + secondary 两个 proxy ----------

def test_node_proxy_primary_and_secondary(session):
    session.add(_make_node("semi", label="半导体", level=1))
    session.commit()

    session.add_all([
        NodeProxy(
            node_id="semi",
            etf_symbol="SOXX",
            role=NodeProxyRole.PRIMARY.value,
            purity=0.95,
        ),
        NodeProxy(
            node_id="semi",
            etf_symbol="SMH",
            role=NodeProxyRole.SECONDARY.value,
            purity=0.90,
        ),
    ])
    session.commit()

    proxies = session.query(NodeProxy).filter_by(node_id="semi").all()
    roles = {p.role for p in proxies}
    assert roles == {"primary", "secondary"}
    assert {p.etf_symbol for p in proxies} == {"SOXX", "SMH"}

    # (node, etf, role) 三元组重复 -> 失败
    session.add(NodeProxy(
        node_id="semi",
        etf_symbol="SOXX",
        role=NodeProxyRole.PRIMARY.value,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------- 5. SyntheticBasketDefinition.chain_extension=True 可插入 ----------

def test_synthetic_basket_chain_extension(session):
    session.add(_make_node("conn-optical", node_type=NodeType.LEAF, level=3,
                           label="光通信", representation_confidence=0.7))
    session.commit()

    session.add_all([
        SyntheticBasketDefinition(
            node_id="conn-optical",
            ticker="COHR",
            target_weight=0.25,
            weighting_strategy="fixed",
            chain_extension=False,
        ),
        SyntheticBasketDefinition(
            node_id="conn-optical",
            ticker="LITE",
            target_weight=0.25,
            weighting_strategy="fixed",
            chain_extension=True,  # 跨出父 ETF 成分
        ),
    ])
    session.commit()

    rows = session.query(SyntheticBasketDefinition).filter_by(node_id="conn-optical").all()
    assert len(rows) == 2
    extensions = {r.ticker: r.chain_extension for r in rows}
    assert extensions == {"COHR": False, "LITE": True}

    # (node_id, ticker) 唯一
    session.add(SyntheticBasketDefinition(node_id="conn-optical", ticker="COHR"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------- 6. NodePriceSeries (node_id, date) 唯一 ----------

def test_node_price_series_unique_per_date(session):
    session.add(_make_node("conn-optical", node_type=NodeType.LEAF, level=3,
                           label="光通信"))
    session.commit()

    d = date(2026, 4, 22)
    session.add(NodePriceSeries(
        node_id="conn-optical",
        date=d,
        close=101.5,
        constituents_count=5,
        coverage_ratio=1.0,
        weighting_strategy="equal",
    ))
    session.commit()

    session.add(NodePriceSeries(
        node_id="conn-optical",
        date=d,
        close=102.0,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # 不同日期允许
    session.add(NodePriceSeries(
        node_id="conn-optical",
        date=date(2026, 4, 23),
        close=103.0,
    ))
    session.commit()
    rows = session.query(NodePriceSeries).filter_by(node_id="conn-optical").all()
    assert len(rows) == 2
