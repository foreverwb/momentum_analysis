"""Task 4.6 节点中心化下钻 API 端点验收测试。

覆盖:
- GET /api/tasks/{id}/nodes 返回根节点 + 至少 1 层子节点
- GET /api/tasks/{id}/nodes/{node_id}/holdings 返回 ≥ 3 只成分股
- synthetic 节点 holdings 返回 NVDA/AMD/AVGO
- GET /api/tasks/{id}/nodes/{node_id}/trend-comparison?period=20 返回 3 条 series
- 不存在的 node_id → 404; 非法 lens / period → 400
"""

from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models import Base, ETF, Task, get_db
from app.models.database import (
    AnalyticNode,
    ETFHolding,
    NodeEdge,
    NodeEdgeType,
    NodeProxy,
    NodeProxyRole,
    NodeType,
    PriceHistory,
    Stock,
    SyntheticBasketDefinition,
)


# ---------- fixtures ----------


@pytest.fixture()
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_xlk_world(db)
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def override_db(test_db):
    def _override():
        yield test_db

    app.dependency_overrides[get_db] = _override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed_prices(
    db,
    symbol: str,
    *,
    days: int = 80,
    daily_change: float = 0.001,
    base: float = 100.0,
) -> None:
    bdays = pd.bdate_range(date(2026, 1, 5), periods=days)
    price = base
    for d in bdays:
        db.add(PriceHistory(symbol=symbol, date=d.date(), close=price))
        price *= 1.0 + daily_change


def _seed_xlk_world(db) -> None:
    """灌入测试任务 + XLK 节点拓扑 + ETF/synthetic basket + 60+ 天价格。

    Task 4.12: 拓扑与 production xlk.yaml 对齐 ——
        XLK --classification--> semi --chain--> {equip,compute,mem,conn}
                                    semi-conn --chain--> {optical,copper}
    使 default lens=hybrid 时 semi.children = 4, gics 时 semi.children = 0.
    """
    xlk = ETF(symbol="XLK", name="Technology", type="sector", rank=1, score=80)
    soxx = ETF(symbol="SOXX", name="Semiconductors", type="industry",
               parent_sector="XLK", rank=1, score=85)
    db.add_all([xlk, soxx])
    db.flush()

    db.add_all([
        AnalyticNode(node_id="XLK", label="科技板块",
                     node_type=NodeType.GICS.value, level=0,
                     representation_confidence=1.0),
        AnalyticNode(node_id="semi", label="半导体",
                     node_type=NodeType.GICS.value, level=1,
                     representation_confidence=0.95),
        AnalyticNode(node_id="semi-equip", label="设备",
                     node_type=NodeType.CHAIN.value, level=2,
                     representation_confidence=0.85),
        AnalyticNode(node_id="semi-compute", label="计算",
                     node_type=NodeType.CHAIN.value, level=2,
                     representation_confidence=0.9),
        AnalyticNode(node_id="semi-mem", label="存储",
                     node_type=NodeType.CHAIN.value, level=2,
                     representation_confidence=0.85),
        AnalyticNode(node_id="semi-conn", label="连接",
                     node_type=NodeType.CHAIN.value, level=2,
                     representation_confidence=0.7),
        AnalyticNode(node_id="conn-optical", label="光互联",
                     node_type=NodeType.LEAF.value, level=3,
                     representation_confidence=0.65),
        AnalyticNode(node_id="conn-copper", label="铜缆",
                     node_type=NodeType.LEAF.value, level=3,
                     representation_confidence=0.65),
    ])
    db.add_all([
        NodeEdge(src_node_id="XLK", dst_node_id="semi",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi", dst_node_id="semi-equip",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi", dst_node_id="semi-compute",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi", dst_node_id="semi-mem",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi", dst_node_id="semi-conn",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi-conn", dst_node_id="conn-optical",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
        NodeEdge(src_node_id="semi-conn", dst_node_id="conn-copper",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value, weight=1.0),
    ])
    db.add_all([
        NodeProxy(node_id="XLK", etf_symbol="XLK",
                  role=NodeProxyRole.PRIMARY.value, purity=1.0),
        NodeProxy(node_id="semi", etf_symbol="SOXX",
                  role=NodeProxyRole.PRIMARY.value, purity=0.95),
        # SMH 同时作为 semi 的 secondary 与 semi-equip 的 primary 共存
        NodeProxy(node_id="semi", etf_symbol="SMH",
                  role=NodeProxyRole.SECONDARY.value, purity=0.85),
        NodeProxy(node_id="semi-equip", etf_symbol="SMH",
                  role=NodeProxyRole.PRIMARY.value, purity=0.85),
        NodeProxy(node_id="semi-mem", etf_symbol="DRAM",
                  role=NodeProxyRole.PRIMARY.value, purity=0.80),
        NodeProxy(node_id="semi-conn", etf_symbol="SIXG",
                  role=NodeProxyRole.PRIMARY.value, purity=0.70),
    ])

    # synthetic basket: semi-compute / conn-optical / conn-copper
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
        SyntheticBasketDefinition(node_id="conn-optical", ticker="AAOI",
                                  weighting_strategy="equal", chain_extension=True),
    ])

    # ETFHolding 用于 GICS 节点 holdings (semi -> SOXX 成分)
    db.add_all([
        ETFHolding(etf_id=soxx.id, etf_symbol="SOXX", ticker="NVDA",
                   weight=20.0, data_date=date(2026, 4, 1)),
        ETFHolding(etf_id=soxx.id, etf_symbol="SOXX", ticker="AVGO",
                   weight=18.0, data_date=date(2026, 4, 1)),
        ETFHolding(etf_id=soxx.id, etf_symbol="SOXX", ticker="AMD",
                   weight=12.0, data_date=date(2026, 4, 1)),
    ])

    # 价格序列
    _seed_prices(db, "SPY", days=80, daily_change=0.001)
    _seed_prices(db, "XLK", days=80, daily_change=0.0015)
    _seed_prices(db, "SOXX", days=80, daily_change=0.003)
    _seed_prices(db, "NVDA", days=80, daily_change=0.004)
    _seed_prices(db, "AMD", days=80, daily_change=0.0025)
    _seed_prices(db, "AVGO", days=80, daily_change=0.0028)
    _seed_prices(db, "CIEN", days=80, daily_change=0.002)
    _seed_prices(db, "LITE", days=80, daily_change=0.002)
    _seed_prices(db, "COHR", days=80, daily_change=0.002)
    _seed_prices(db, "AAOI", days=80, daily_change=0.002)

    # Stock 表 (持仓接口需读 score)
    db.add_all([
        Stock(symbol="NVDA", name="NVIDIA Corp.", score_total=92.0,
              changes={"delta3d": 4.1, "delta5d": 7.8}),
        Stock(symbol="AMD", name="AMD Inc.", score_total=78.0,
              changes={"delta3d": 1.0, "delta5d": 2.0}),
        Stock(symbol="AVGO", name="Broadcom", score_total=85.0,
              changes={"delta3d": 2.5, "delta5d": 4.0}),
    ])

    # 任务 (id=1: Node-Centric drilldown; root_node = XLK; default hybrid)
    db.add(Task(
        title="XLK Drilldown",
        type="drilldown",
        base_index="SPY",
        sector="XLK",
        etfs=["SOXX"],
        root_node="XLK",
        view_mode="hybrid",
        selected_nodes=["XLK", "semi", "semi-compute"],
        max_depth=3,
    ))

    db.commit()


# ---------- 1. GET /api/tasks/{id}/nodes ----------


@pytest.mark.asyncio
async def test_node_tree_returns_root_with_descendants(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes")

    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    assert len(payload) == 1

    root = payload[0]
    assert root["id"] == "XLK"
    assert root["level"] == 0
    assert root["proxyType"] in ("etf", "synthetic")
    assert isinstance(root["children"], list)
    assert len(root["children"]) >= 1

    semi = next(c for c in root["children"] if c["id"] == "semi")
    assert semi["level"] == 1
    # max_depth=3, semi-compute should be reachable as grandchild
    assert any(c["id"] == "semi-compute" for c in semi["children"])

    # Cache header
    assert "max-age=300" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_node_tree_invalid_lens_returns_400(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes?lens=banana")

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_node_tree_unknown_task_returns_404(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/9999/nodes")

    assert resp.status_code == 404


# ---------- 2. GET /api/tasks/{id}/nodes/{node_id}/holdings ----------


@pytest.mark.asyncio
async def test_node_holdings_returns_three_constituents(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes/semi/holdings")

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) >= 3

    tickers = {h["ticker"] for h in payload}
    assert {"NVDA", "AMD", "AVGO"}.issubset(tickers)

    nvda = next(h for h in payload if h["ticker"] == "NVDA")
    assert nvda["score"] == 92.0
    assert nvda["name"] == "NVIDIA Corp."
    assert nvda["dataStatus"] in ("complete", "pending", "missing")
    assert "return20d" in nvda
    assert "rs20d" in nvda


@pytest.mark.asyncio
async def test_synthetic_node_holdings_match_basket(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes/semi-compute/holdings")

    assert resp.status_code == 200
    payload = resp.json()
    tickers = {h["ticker"] for h in payload}
    assert tickers == {"NVDA", "AMD", "AVGO"}


@pytest.mark.asyncio
async def test_node_holdings_unknown_node_returns_404(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes/no-such-node/holdings")

    assert resp.status_code == 404


# ---------- 3. GET /api/tasks/{id}/nodes/{node_id}/trend-comparison ----------


@pytest.mark.asyncio
async def test_node_trend_comparison_returns_three_series(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get(
            "/api/tasks/1/nodes/semi/trend-comparison?period=20"
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["task_id"] == 1
    assert payload["node_id"] == "semi"
    assert payload["period"] == 20
    assert payload["metric"] == "relative"

    symbols = payload["symbols"]
    assert symbols[0] == "semi"
    assert symbols[-1] == "SPY"
    assert "XLK" in symbols  # parent

    series = payload["series"]
    assert len(series) == 3
    colors = {s["symbol"]: s["color"] for s in series}
    assert colors["semi"] == "#3b82f6"
    assert colors["XLK"] == "#8b5cf6"
    assert colors["SPY"] == "#94a3b8"

    # 至少有数据点
    assert len(payload["dates"]) > 0
    for s in series:
        assert len(s["values"]) == len(payload["dates"])


@pytest.mark.asyncio
async def test_node_trend_invalid_period_returns_400(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get(
            "/api/tasks/1/nodes/semi/trend-comparison?period=99"
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_node_trend_unknown_node_returns_404(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get(
            "/api/tasks/1/nodes/no-such/trend-comparison?period=20"
        )

    assert resp.status_code == 404


# ---------- 4. Task 4.12: hybrid 默认 lens / chain proxy / chain-extension holdings ----------


def _find_node(payload, target_id):
    """递归找节点 payload (BFS)."""
    stack = list(payload)
    while stack:
        n = stack.pop(0)
        if n["id"] == target_id:
            return n
        stack.extend(n.get("children", []) or [])
    return None


@pytest.mark.asyncio
async def test_default_lens_is_hybrid(override_db):
    """不传 lens 时 task.view_mode='hybrid' 兜底, semi 下渲染 4 chain, semi-conn 下 2 leaf."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes")

    assert resp.status_code == 200
    payload = resp.json()
    root = payload[0]
    assert root["id"] == "XLK"
    assert "semi" in {c["id"] for c in root["children"]}

    semi = _find_node(payload, "semi")
    assert semi is not None
    chain_children = {c["id"] for c in semi.get("children", [])}
    assert {"semi-equip", "semi-compute", "semi-mem", "semi-conn"}.issubset(chain_children)

    semi_conn = _find_node(payload, "semi-conn")
    assert semi_conn is not None
    leaf_children = {c["id"] for c in semi_conn.get("children", [])}
    assert leaf_children == {"conn-optical", "conn-copper"}


@pytest.mark.asyncio
async def test_lens_gics_still_filters(override_db):
    """显式 lens=gics 仍只走 classification_parent: semi 在该视图下无 chain 子节点."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes?lens=gics")

    assert resp.status_code == 200
    payload = resp.json()
    semi = _find_node(payload, "semi")
    assert semi is not None
    assert (semi.get("children") or []) == []


@pytest.mark.asyncio
async def test_chain_node_proxy_resolved(override_db):
    """catalog 接口暴露 chain 节点的 primary proxy ETF (SMH/DRAM/SIXG)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/nodes/catalog?root_node=XLK")

    assert resp.status_code == 200
    by_id = {n["id"]: n for n in resp.json()}
    assert by_id["semi-equip"]["proxy_etf"] == "SMH"
    assert by_id["semi-mem"]["proxy_etf"] == "DRAM"
    assert by_id["semi-conn"]["proxy_etf"] == "SIXG"


@pytest.mark.asyncio
async def test_holdings_for_chain_synthetic_node(override_db):
    """conn-optical 的 chain-extension 成分股应出现在 holdings 接口."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/nodes/conn-optical/holdings")

    assert resp.status_code == 200
    payload = resp.json()
    tickers = {h["ticker"] for h in payload}
    # CIEN/LITE/COHR/AAOI 全部 seed
    assert {"CIEN", "LITE", "COHR", "AAOI"}.issubset(tickers)
    assert len(payload) >= 3
