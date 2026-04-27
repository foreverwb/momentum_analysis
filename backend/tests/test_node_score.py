"""node_score.batch_calculate_node_scores / compute_chain_confirmation 单元测试。

Task 4.4 验收覆盖:
1. XLK + semi + soft + hw 4 节点 60 天价格 → 返回 4 条结果按 total_score 降序
2. representation_confidence=0.95 → total_score 近似 base × 0.95
3. drives 边对端均 ≥ 60 → confirmation = 1.0
4. recommended_drill 阈值规则 (≥ 父节点 + 5 推荐, 否则 None)
5. NodePriceSeries < 30 天 → notes 含 "数据不足", 不抛异常
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import (
    AnalyticNode,
    Base,
    ETF,
    ETFHolding,
    NodeEdge,
    NodeEdgeType,
    NodePriceSeries,
    NodeProxy,
    NodeProxyRole,
    NodeType,
    PriceHistory,
    SyntheticBasketDefinition,
)
from app.services.calculators.node_score import (
    _pick_recommended_drill,
    batch_calculate_node_scores,
    compute_chain_confirmation,
)


# ---------- fixtures ----------


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_prices(
    db,
    symbol: str,
    *,
    start: date = date(2026, 1, 5),
    days: int = 60,
    base: float = 100.0,
    daily_change: float = 0.001,
) -> None:
    bdays = pd.bdate_range(start, periods=days)
    price = base
    for d in bdays:
        db.add(PriceHistory(symbol=symbol, date=d.date(), close=price))
        price *= 1.0 + daily_change
    db.commit()


def _seed_xlk_topology(
    db,
    *,
    semi_rep_conf: float = 1.0,
    hw_rep_conf: float = 1.0,
) -> None:
    """灌入 XLK + 3 个 GICS 子节点 (semi / soft / hw) + edges + proxies."""
    db.add_all([
        AnalyticNode(
            node_id="XLK", label="科技板块", node_type=NodeType.GICS.value,
            level=0, representation_confidence=1.0,
        ),
        AnalyticNode(
            node_id="semi", label="半导体", node_type=NodeType.GICS.value,
            level=1, representation_confidence=semi_rep_conf,
        ),
        AnalyticNode(
            node_id="soft", label="软件", node_type=NodeType.GICS.value,
            level=1, representation_confidence=1.0,
        ),
        AnalyticNode(
            node_id="hw", label="硬件", node_type=NodeType.GICS.value,
            level=1, representation_confidence=hw_rep_conf,
        ),
    ])
    db.add_all([
        NodeEdge(
            src_node_id="XLK", dst_node_id="semi",
            edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value, weight=1.0,
        ),
        NodeEdge(
            src_node_id="XLK", dst_node_id="soft",
            edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value, weight=1.0,
        ),
        NodeEdge(
            src_node_id="XLK", dst_node_id="hw",
            edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value, weight=1.0,
        ),
    ])
    db.add_all([
        NodeProxy(
            node_id="XLK", etf_symbol="XLK",
            role=NodeProxyRole.PRIMARY.value, purity=1.0,
        ),
        NodeProxy(
            node_id="semi", etf_symbol="SOXX",
            role=NodeProxyRole.PRIMARY.value, purity=0.95,
        ),
        NodeProxy(
            node_id="soft", etf_symbol="IGV",
            role=NodeProxyRole.PRIMARY.value, purity=0.9,
        ),
    ])
    # hw 没有干净 ETF, 用 synthetic basket
    db.add_all([
        SyntheticBasketDefinition(
            node_id="hw", ticker="AAPL", weighting_strategy="equal",
        ),
        SyntheticBasketDefinition(
            node_id="hw", ticker="HPQ", weighting_strategy="equal",
        ),
    ])
    db.commit()


def _seed_full_xlk_prices(db) -> None:
    """给 SPY/XLK/SOXX/IGV/AAPL/HPQ 都灌 60 天价格 (不同收益率)."""
    # 不同 daily_change 制造区分度
    _seed_prices(db, "SPY", daily_change=0.001)   # 基准
    _seed_prices(db, "XLK", daily_change=0.0015)  # 微强于 SPY
    _seed_prices(db, "SOXX", daily_change=0.003)  # 半导体最强
    _seed_prices(db, "IGV", daily_change=0.0012)  # 软件略强
    _seed_prices(db, "AAPL", daily_change=0.0008)  # 硬件偏弱
    _seed_prices(db, "HPQ", daily_change=0.0006)


# ---------- 1. XLK 四节点按总分降序 ----------


def test_batch_returns_four_results_sorted_desc(session):
    _seed_xlk_topology(session)
    _seed_full_xlk_prices(session)

    results = batch_calculate_node_scores(["XLK", "semi", "soft", "hw"], session)

    assert len(results) == 4
    node_ids = {r.node_id for r in results}
    assert node_ids == {"XLK", "semi", "soft", "hw"}
    # 严格降序
    scores = [r.total_score for r in results]
    assert scores == sorted(scores, reverse=True)
    # SOXX (semi) 收益最强 → semi 应排第一
    assert results[0].node_id == "semi"


# ---------- 2. representation_confidence=0.95 → total ≈ base × 0.95 ----------


def test_representation_confidence_scales_total_score(session):
    """semi 节点 rep_conf=0.95, 没有 drives/depends_on 边 → chain_conf=1.0,
    total = base × 0.95 × (0.7 + 0.3 × 1.0) = base × 0.95
    """
    _seed_xlk_topology(session, semi_rep_conf=0.95)
    _seed_full_xlk_prices(session)

    results = batch_calculate_node_scores(["XLK", "semi", "soft", "hw"], session)
    semi_result = next(r for r in results if r.node_id == "semi")

    assert semi_result.representation_confidence == pytest.approx(0.95)
    assert semi_result.chain_confirmation == pytest.approx(1.0)
    # base 必须 < 100 (横截面 rank percentile, n=4 时第一名 = 100, 但仍 ≤ 100)
    # 这里只验证比例公式
    expected = semi_result.base_score * 0.95 * 1.0
    assert semi_result.total_score == pytest.approx(round(expected, 2), abs=0.01)
    # 略低于 base
    if semi_result.base_score > 0:
        assert semi_result.total_score < semi_result.base_score


# ---------- 3. compute_chain_confirmation: drives 全部合格 → 1.0 ----------


def test_chain_confirmation_all_drives_qualified(session):
    """semi-compute 有 2 条 drives 边到 semi-equip / semi-conn,
    两端 score ≥ 60 → confirmation = 1.0
    """
    session.add_all([
        AnalyticNode(
            node_id="semi-compute", label="计算",
            node_type=NodeType.CHAIN.value, level=2,
        ),
        AnalyticNode(
            node_id="semi-equip", label="设备",
            node_type=NodeType.CHAIN.value, level=2,
        ),
        AnalyticNode(
            node_id="semi-conn", label="连接",
            node_type=NodeType.CHAIN.value, level=2,
        ),
    ])
    session.add_all([
        NodeEdge(
            src_node_id="semi-compute", dst_node_id="semi-equip",
            edge_type=NodeEdgeType.DRIVES.value, weight=1.0,
        ),
        NodeEdge(
            src_node_id="semi-compute", dst_node_id="semi-conn",
            edge_type=NodeEdgeType.DRIVES.value, weight=1.0,
        ),
    ])
    session.commit()

    conf_full = compute_chain_confirmation(
        "semi-compute", {"semi-equip": 75.0, "semi-conn": 80.0}, session,
    )
    assert conf_full == pytest.approx(1.0)

    # 一端不合格 → 应小于 1
    conf_partial = compute_chain_confirmation(
        "semi-compute", {"semi-equip": 75.0, "semi-conn": 50.0}, session,
    )
    assert conf_partial == pytest.approx(0.5)

    # 两端都不合格 → 0
    conf_none = compute_chain_confirmation(
        "semi-compute", {"semi-equip": 30.0, "semi-conn": 40.0}, session,
    )
    assert conf_none == pytest.approx(0.0)


def test_chain_confirmation_no_edges_returns_neutral(session):
    """没有任何上下游边的节点 → 中性 1.0 (不引入下行修正)."""
    session.add(AnalyticNode(
        node_id="lonely", label="孤立",
        node_type=NodeType.GICS.value, level=1,
    ))
    session.commit()

    assert compute_chain_confirmation("lonely", {}, session) == pytest.approx(1.0)


def test_chain_confirmation_corroborates_half_weight(session):
    """corroborates 入边按 0.5 倍权重计算."""
    session.add_all([
        AnalyticNode(
            node_id="main", label="主",
            node_type=NodeType.GICS.value, level=1,
        ),
        AnalyticNode(
            node_id="theme", label="主题",
            node_type=NodeType.EVIDENCE.value, level=2,
        ),
    ])
    session.add(NodeEdge(
        src_node_id="theme", dst_node_id="main",
        edge_type=NodeEdgeType.CORROBORATES.value, weight=1.0,
    ))
    session.commit()

    # 入边唯一; 对端合格 → matched = 0.5, total = 0.5, ratio = 1.0
    conf = compute_chain_confirmation("main", {"theme": 70.0}, session)
    assert conf == pytest.approx(1.0)

    conf_low = compute_chain_confirmation("main", {"theme": 50.0}, session)
    assert conf_low == pytest.approx(0.0)


# ---------- 4. recommended_drill 阈值规则 ----------


def test_recommended_drill_picks_top_when_above_threshold():
    parent = "p"
    children = ["c1", "c2", "c3"]
    score_map = {"p": 70.0, "c1": 85.0, "c2": 60.0, "c3": 55.0}
    assert _pick_recommended_drill(
        node_id=parent, children=children, total_score_map=score_map,
    ) == "c1"


def test_recommended_drill_returns_none_when_gap_below_threshold():
    parent = "p"
    children = ["c1", "c2", "c3"]
    # 最高 72 - 父 70 = 2 < 5 → None
    score_map = {"p": 70.0, "c1": 72.0, "c2": 60.0, "c3": 55.0}
    assert _pick_recommended_drill(
        node_id=parent, children=children, total_score_map=score_map,
    ) is None


def test_recommended_drill_no_children_returns_none():
    assert _pick_recommended_drill(
        node_id="p", children=[], total_score_map={"p": 70.0},
    ) is None


# ---------- 5. 数据不足: NodePriceSeries < 30 天 → notes ----------


def test_data_insufficient_marks_notes_no_exception(session):
    """hw 节点为 synthetic, 但成分股 AAPL/HPQ 仅 10 天 → 合成序列 < 30 天."""
    session.add(AnalyticNode(
        node_id="hw", label="硬件",
        node_type=NodeType.GICS.value, level=1,
        representation_confidence=1.0,
    ))
    session.add_all([
        SyntheticBasketDefinition(
            node_id="hw", ticker="AAPL", weighting_strategy="equal",
        ),
        SyntheticBasketDefinition(
            node_id="hw", ticker="HPQ", weighting_strategy="equal",
        ),
    ])
    session.commit()
    _seed_prices(session, "AAPL", days=10)
    _seed_prices(session, "HPQ", days=10)
    _seed_prices(session, "SPY", days=10)

    results = batch_calculate_node_scores(["hw"], session)
    assert len(results) == 1
    hw_result = results[0]
    assert "数据不足" in hw_result.notes
    # 不应抛异常, 子分数全 None
    assert all(v is None for v in hw_result.raw_subscores.values())
    # base / total 退化为 0 (无可用维度)
    assert hw_result.base_score == 0.0
    assert hw_result.total_score == 0.0
