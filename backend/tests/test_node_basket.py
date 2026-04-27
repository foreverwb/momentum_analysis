"""node_basket.compute_basket_price_series / 查询接口单元测试。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import (
    AnalyticNode,
    Base,
    ETF,
    ETFHolding,
    ImportedData,
    NodeEdge,
    NodeEdgeType,
    NodePriceSeries,
    NodeProxy,
    NodeProxyRole,
    NodeType,
    PriceHistory,
    SyntheticBasketDefinition,
)
from app.services.calculators.node_basket import (
    compute_basket_price_series,
    get_node_holdings,
    get_node_proxy_etf,
    is_synthetic_node,
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


def _seed_nodes(db) -> None:
    """构造与 xlk.yaml 一致的最小拓扑用于测试。"""
    db.add_all([
        AnalyticNode(node_id="XLK", label="XLK", node_type=NodeType.GICS.value, level=0,
                     representation_confidence=1.0),
        AnalyticNode(node_id="semi", label="半导体", node_type=NodeType.GICS.value, level=1,
                     representation_confidence=1.0),
        AnalyticNode(node_id="hw", label="硬件", node_type=NodeType.GICS.value, level=1,
                     representation_confidence=0.7),
        AnalyticNode(node_id="semi-compute", label="计算", node_type=NodeType.CHAIN.value,
                     level=2, representation_confidence=0.8),
    ])
    db.add_all([
        NodeEdge(src_node_id="XLK", dst_node_id="semi",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value),
        NodeEdge(src_node_id="XLK", dst_node_id="hw",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value),
        NodeEdge(src_node_id="semi", dst_node_id="semi-compute",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value),
    ])
    # semi 有 SOXX primary proxy → 非 synthetic
    # XLK 自身有 XLK primary proxy（用于 parent_etf_weight 测试）
    db.add_all([
        NodeProxy(node_id="XLK", etf_symbol="XLK",
                  role=NodeProxyRole.PRIMARY.value, purity=1.0),
        NodeProxy(node_id="semi", etf_symbol="SOXX",
                  role=NodeProxyRole.PRIMARY.value, purity=0.95),
    ])
    # semi-compute (mcap, NVDA/AMD/AVGO) ; hw (parent_etf_weight)
    db.add_all([
        SyntheticBasketDefinition(node_id="semi-compute", ticker="NVDA",
                                  weighting_strategy="mcap"),
        SyntheticBasketDefinition(node_id="semi-compute", ticker="AMD",
                                  weighting_strategy="mcap"),
        SyntheticBasketDefinition(node_id="semi-compute", ticker="AVGO",
                                  weighting_strategy="mcap"),
        SyntheticBasketDefinition(node_id="hw", ticker="AAPL",
                                  weighting_strategy="parent_etf_weight"),
        SyntheticBasketDefinition(node_id="hw", ticker="HPQ",
                                  weighting_strategy="parent_etf_weight"),
    ])
    db.commit()


def _seed_prices(
    db,
    tickers: Iterable[str],
    days: int = 60,
    start: date = date(2026, 1, 5),
    base: float = 100.0,
    daily_change: float = 0.001,
) -> None:
    """给每个 ticker 灌 N 天工作日 close（单调上升, 微小日收益）。"""
    bdays = pd.bdate_range(start, periods=days)
    for t in tickers:
        price = base
        for d in bdays:
            db.add(PriceHistory(symbol=t, date=d.date(), close=price))
            price *= 1.0 + daily_change
    db.commit()


def _seed_finviz_mcap(db, mapping: dict, on_date: date = date(2026, 1, 1)) -> None:
    for ticker, mcap in mapping.items():
        db.add(ImportedData(
            symbol=ticker, date=on_date, source="finviz",
            data={"market_cap": mcap},
        ))
    db.commit()


# ---------- 1. mcap 60 天全覆盖 ----------

def test_compute_semi_compute_full_coverage(session):
    _seed_nodes(session)
    _seed_prices(session, ["NVDA", "AMD", "AVGO"], days=60)
    _seed_finviz_mcap(session, {"NVDA": 3.0e12, "AMD": 2.5e11, "AVGO": 7.0e11})

    result = compute_basket_price_series("semi-compute", session)

    assert result.error is None
    # 60 个 bdays, 第一天 pct_change 为 NaN → 跳过, 期望 59 行
    assert result.rows_written == 59
    assert result.coverage_avg >= 0.95
    # representation_confidence = node_conf(0.8) * coverage_avg
    assert result.representation_confidence == pytest.approx(0.8 * result.coverage_avg)
    rows = session.query(NodePriceSeries).filter_by(node_id="semi-compute").all()
    assert len(rows) == 59
    assert all(r.weighting_strategy == "mcap" for r in rows)
    assert all(r.coverage_ratio == pytest.approx(1.0) for r in rows)


# ---------- 2. AVGO 第 30 天缺失 → coverage<1 但仍输出 ----------

def test_partial_missing_keeps_row(session):
    _seed_nodes(session)
    _seed_prices(session, ["NVDA", "AMD", "AVGO"], days=60)
    _seed_finviz_mcap(session, {"NVDA": 3.0e12, "AMD": 2.5e11, "AVGO": 7.0e11})

    bdays = pd.bdate_range(date(2026, 1, 5), periods=60)
    target_day = bdays[29].date()
    session.query(PriceHistory).filter(
        PriceHistory.symbol == "AVGO",
        PriceHistory.date == target_day,
    ).delete()
    session.commit()

    compute_basket_price_series("semi-compute", session)
    row = session.query(NodePriceSeries).filter_by(
        node_id="semi-compute", date=target_day
    ).first()
    assert row is not None, "缺一只成分仍应写入该日"
    assert row.constituents_count == 2
    assert row.coverage_ratio == pytest.approx(2 / 3)


# ---------- 3. AMD + AVGO 第 30 天都缺 → 该日跳过 ----------

def test_below_min_constituents_skips_day(session):
    _seed_nodes(session)
    _seed_prices(session, ["NVDA", "AMD", "AVGO"], days=60)
    _seed_finviz_mcap(session, {"NVDA": 3.0e12, "AMD": 2.5e11, "AVGO": 7.0e11})

    bdays = pd.bdate_range(date(2026, 1, 5), periods=60)
    target_day = bdays[29].date()
    for sym in ("AMD", "AVGO"):
        session.query(PriceHistory).filter(
            PriceHistory.symbol == sym, PriceHistory.date == target_day,
        ).delete()
    session.commit()

    compute_basket_price_series("semi-compute", session, min_constituents=2)
    row = session.query(NodePriceSeries).filter_by(
        node_id="semi-compute", date=target_day
    ).first()
    assert row is None, "仅 1 只 < min=2 应跳过"


# ---------- 4. equal 策略 +1 / -1 / 0 → 节点收益 0 ----------

def test_equal_strategy_zero_sum(session):
    """三只 ticker 日收益 +100% / -100% / 0% → 节点日收益 = 0。"""
    session.add(AnalyticNode(node_id="trio", label="trio",
                             node_type=NodeType.CHAIN.value, level=2,
                             representation_confidence=1.0))
    session.add_all([
        SyntheticBasketDefinition(node_id="trio", ticker="UP", weighting_strategy="equal"),
        SyntheticBasketDefinition(node_id="trio", ticker="DN", weighting_strategy="equal"),
        SyntheticBasketDefinition(node_id="trio", ticker="FL", weighting_strategy="equal"),
    ])
    d1, d2 = date(2026, 1, 5), date(2026, 1, 6)
    session.add_all([
        PriceHistory(symbol="UP", date=d1, close=100.0),
        PriceHistory(symbol="UP", date=d2, close=200.0),  # +100%
        PriceHistory(symbol="DN", date=d1, close=100.0),
        PriceHistory(symbol="DN", date=d2, close=0.0001),  # ≈-100%
        PriceHistory(symbol="FL", date=d1, close=100.0),
        PriceHistory(symbol="FL", date=d2, close=100.0),  # 0%
    ])
    session.commit()

    result = compute_basket_price_series("trio", session, base_value=100.0)
    assert result.rows_written == 1
    row = session.query(NodePriceSeries).filter_by(node_id="trio", date=d2).first()
    # (1.0 + (-1.0) + 0.0)/3 ≈ 0 → 价格仍为 100
    assert row.close == pytest.approx(100.0, abs=0.01)


# ---------- 5. holdings 接口 ----------

def test_get_node_holdings_etf_proxy(session):
    """ETF proxy 节点 → 走 ETFHolding。"""
    session.add(ETF(symbol="XLK", name="Technology", type="sector"))
    session.commit()
    etf = session.query(ETF).filter_by(symbol="XLK").first()
    holding_date = date(2026, 4, 1)
    session.add_all([
        ETFHolding(etf_id=etf.id, etf_symbol="XLK", ticker="AAPL",
                   weight=12.0, data_date=holding_date),
        ETFHolding(etf_id=etf.id, etf_symbol="XLK", ticker="MSFT",
                   weight=10.0, data_date=holding_date),
        ETFHolding(etf_id=etf.id, etf_symbol="XLK", ticker="NVDA",
                   weight=8.0, data_date=holding_date),
    ])
    _seed_nodes(session)

    holdings = get_node_holdings("XLK", session)
    assert [h["ticker"] for h in holdings] == ["AAPL", "MSFT", "NVDA"]
    assert holdings[0]["weight"] == pytest.approx(12.0)
    assert holdings[0]["weighting_strategy"] == "etf_proxy"
    assert holdings[0]["is_chain_extension"] is False


def test_get_node_holdings_synthetic_basket(session):
    """Synthetic 节点 → 走 SyntheticBasketDefinition + 实时权重。"""
    _seed_nodes(session)
    _seed_finviz_mcap(session, {"NVDA": 3.0e12, "AMD": 2.5e11, "AVGO": 7.0e11})

    holdings = get_node_holdings("semi-compute", session)
    assert {h["ticker"] for h in holdings} == {"NVDA", "AMD", "AVGO"}
    # mcap 最大者权重最高
    assert holdings[0]["ticker"] == "NVDA"
    # 权重和 = 100
    total = sum(h["weight"] for h in holdings)
    assert total == pytest.approx(100.0)
    assert holdings[0]["weighting_strategy"] == "mcap"


# ---------- 6. is_synthetic_node / proxy 查询 ----------

def test_is_synthetic_node(session):
    _seed_nodes(session)
    # semi 有 SOXX primary proxy → 不是 synthetic
    assert is_synthetic_node("semi", session) is False
    # hw 没有 proxy 但有 basket → synthetic
    assert is_synthetic_node("hw", session) is True
    # 不存在的节点 → 无 proxy 无 basket → False
    assert is_synthetic_node("nonexistent", session) is False


def test_get_node_proxy_etf(session):
    _seed_nodes(session)
    assert get_node_proxy_etf("semi", session) == "SOXX"
    assert get_node_proxy_etf("hw", session) is None


# ---------- 7. parent_etf_weight 策略 ----------

def test_parent_etf_weight_strategy(session):
    """hw 节点应从父节点 XLK 的 ETFHolding 取权重。"""
    _seed_nodes(session)
    session.add(ETF(symbol="XLK", name="Technology", type="sector"))
    session.commit()
    etf = session.query(ETF).filter_by(symbol="XLK").first()
    session.add_all([
        ETFHolding(etf_id=etf.id, etf_symbol="XLK", ticker="AAPL",
                   weight=15.0, data_date=date(2026, 4, 1)),
        ETFHolding(etf_id=etf.id, etf_symbol="XLK", ticker="HPQ",
                   weight=5.0, data_date=date(2026, 4, 1)),
    ])
    session.commit()
    _seed_prices(session, ["AAPL", "HPQ"], days=10)

    result = compute_basket_price_series("hw", session)
    assert result.error is None
    assert result.rows_written > 0

    holdings = get_node_holdings("hw", session)
    weights = {h["ticker"]: h["weight"] for h in holdings}
    # AAPL/HPQ = 15/5 → 75% / 25%
    assert weights["AAPL"] == pytest.approx(75.0)
    assert weights["HPQ"] == pytest.approx(25.0)


# ---------- 8. 缓存 / force_recompute ----------

def test_idempotent_skip_existing(session):
    _seed_nodes(session)
    _seed_prices(session, ["NVDA", "AMD", "AVGO"], days=60)
    _seed_finviz_mcap(session, {"NVDA": 3.0e12, "AMD": 2.5e11, "AVGO": 7.0e11})

    r1 = compute_basket_price_series("semi-compute", session)
    r2 = compute_basket_price_series("semi-compute", session)
    assert r1.rows_written == 59
    assert r2.rows_written == 0  # 全部已存在, 跳过

    r3 = compute_basket_price_series("semi-compute", session, force_recompute=True)
    assert r3.rows_written == 59


# ---------- 9. mcap 缺失 → 退化 equal ----------

def test_mcap_missing_falls_back_to_equal(session):
    _seed_nodes(session)
    _seed_prices(session, ["NVDA", "AMD", "AVGO"], days=5)
    # 不灌 finviz mcap → 应退化 equal, 不应报错

    result = compute_basket_price_series("semi-compute", session)
    assert result.error is None
    assert result.rows_written > 0


# ---------- 10. 无 basket 定义 → 错误返回 ----------

def test_no_basket_returns_error(session):
    session.add(AnalyticNode(node_id="empty", label="empty",
                             node_type=NodeType.CHAIN.value, level=2))
    session.commit()
    result = compute_basket_price_series("empty", session)
    assert result.rows_written == 0
    assert result.error is not None
    assert "basket" in result.error.lower()
