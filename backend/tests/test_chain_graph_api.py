"""GET /api/tasks/{task_id}/chain-graph 端点验收测试（Task DD-10）。

覆盖：
- 200 正常路径：XLK 任务 → 12 nodes + 12 edges + signals/strategy 字段存在
- 404：task 不存在
- 404：任务对应 sector 没有加载 chain_topology
- 节点字段（坐标/proxy）正确透传
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
    NodeEdge,
    NodeEdgeType,
    NodeProxy,
    NodeProxyRole,
    NodeType,
    PriceHistory,
)
from app.services.chain_topology_loader import load_chain_topology


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


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
        _seed_world(db)
        # XLK 拓扑加载到内存数据库
        load_chain_topology("xlk", db=db)
        db.commit()
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


def _seed_prices(db, symbol: str, days: int = 80, daily_change: float = 0.001) -> None:
    bdays = pd.bdate_range(date(2026, 1, 5), periods=days)
    price = 100.0
    for d in bdays:
        db.add(PriceHistory(symbol=symbol, date=d.date(), close=price))
        price *= 1.0 + daily_change


def _seed_world(db) -> None:
    """灌入 ETF / 节点 taxonomy / 价格 / 任务（与 test_nodes_api 保持一致的最小集）。"""
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
                     node_type=NodeType.GICS.value, level=1),
        AnalyticNode(node_id="soft", label="软件",
                     node_type=NodeType.GICS.value, level=1),
        AnalyticNode(node_id="hw", label="硬件",
                     node_type=NodeType.GICS.value, level=1),
        AnalyticNode(node_id="semi-equip", label="设备",
                     node_type=NodeType.CHAIN.value, level=2),
        AnalyticNode(node_id="semi-compute", label="计算",
                     node_type=NodeType.CHAIN.value, level=2),
        AnalyticNode(node_id="semi-mem", label="存储",
                     node_type=NodeType.CHAIN.value, level=2),
        AnalyticNode(node_id="semi-conn", label="连接",
                     node_type=NodeType.CHAIN.value, level=2),
        AnalyticNode(node_id="conn-optical", label="光互联",
                     node_type=NodeType.LEAF.value, level=3),
        AnalyticNode(node_id="conn-copper", label="铜缆",
                     node_type=NodeType.LEAF.value, level=3),
        AnalyticNode(node_id="soft-cloud", label="云计算",
                     node_type=NodeType.EVIDENCE.value, level=2),
        AnalyticNode(node_id="soft-cyber", label="网络安全",
                     node_type=NodeType.EVIDENCE.value, level=2),
    ])
    db.add_all([
        NodeEdge(src_node_id="XLK", dst_node_id="semi",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value),
        NodeEdge(src_node_id="XLK", dst_node_id="soft",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value),
        NodeEdge(src_node_id="XLK", dst_node_id="hw",
                 edge_type=NodeEdgeType.CLASSIFICATION_PARENT.value),
        NodeEdge(src_node_id="semi", dst_node_id="semi-equip",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value),
        NodeEdge(src_node_id="semi", dst_node_id="semi-compute",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value),
        NodeEdge(src_node_id="semi", dst_node_id="semi-mem",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value),
        NodeEdge(src_node_id="semi", dst_node_id="semi-conn",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value),
        NodeEdge(src_node_id="semi-conn", dst_node_id="conn-optical",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value),
        NodeEdge(src_node_id="semi-conn", dst_node_id="conn-copper",
                 edge_type=NodeEdgeType.CHAIN_PARENT.value),
    ])
    db.add_all([
        NodeProxy(node_id="XLK", etf_symbol="XLK",
                  role=NodeProxyRole.PRIMARY.value, purity=1.0),
        NodeProxy(node_id="semi", etf_symbol="SOXX",
                  role=NodeProxyRole.PRIMARY.value, purity=0.95),
    ])

    _seed_prices(db, "SPY")
    _seed_prices(db, "XLK", daily_change=0.0015)
    _seed_prices(db, "SOXX", daily_change=0.003)

    # Task 1: XLK drilldown
    db.add(Task(
        title="XLK Drilldown",
        type="drilldown",
        base_index="SPY",
        sector="XLK",
        etfs=["SOXX"],
        root_node="XLK",
        view_mode="hybrid",
        max_depth=3,
    ))
    # Task 2: 板块 unknown，刻意未加载 chain_topology
    db.add(Task(
        title="Unknown Sector Drilldown",
        type="drilldown",
        base_index="SPY",
        sector="XYZ",
        etfs=[],
        root_node="XYZ",
        view_mode="hybrid",
        max_depth=3,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# 200 路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_graph_returns_12_nodes_and_12_edges(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/chain-graph")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["sector"] == "xlk"
    assert len(payload["nodes"]) == 12
    assert len(payload["edges"]) == 12


@pytest.mark.asyncio
async def test_chain_graph_node_payload_shape(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/chain-graph")

    payload = resp.json()
    xlk = next(n for n in payload["nodes"] if n["node_id"] == "XLK")
    # 关键字段都被 YAML 透传
    assert xlk["role"] == "root"
    assert xlk["tier"] == 0
    assert xlk["proxy"] == "XLK"
    assert xlk["proxy_type"] == "primary"
    assert xlk["proxy_label"] == "科技板块"
    assert isinstance(xlk["cx"], (int, float))
    assert isinstance(xlk["cy"], (int, float))


@pytest.mark.asyncio
async def test_chain_graph_edge_is_cross_flag_present(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/chain-graph")

    payload = resp.json()
    main_edges = [e for e in payload["edges"] if e["is_cross"] is False]
    cross_edges = [e for e in payload["edges"] if e["is_cross"] is True]
    assert len(main_edges) == 9   # 3 GICS + 6 chain
    assert len(cross_edges) == 3  # 2 corroborates + 1 drives


@pytest.mark.asyncio
async def test_chain_graph_includes_signals_and_strategy_keys(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/chain-graph")

    payload = resp.json()
    # 复用 DD-3 / DD-4 计算引擎，键必须存在
    assert "signals" in payload
    assert "strategy" in payload
    if payload["signals"] is not None:
        assert {"upstream", "broad", "downstream", "label", "color"} <= set(
            payload["signals"].keys()
        )
    if payload["strategy"] is not None:
        assert {"l1_ranking", "breadth", "confirmation", "best_drill"} <= set(
            payload["strategy"].keys()
        )


@pytest.mark.asyncio
async def test_chain_graph_explicit_sector_query_param(override_db):
    """sector 显式传入应优先于 task.root_node。"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/chain-graph?sector=xlk")

    assert resp.status_code == 200
    assert resp.json()["sector"] == "xlk"


# ---------------------------------------------------------------------------
# 4xx 路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_graph_404_when_task_missing(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/9999/chain-graph")

    assert resp.status_code == 404
    assert "Task not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chain_graph_404_when_sector_has_no_topology(override_db):
    """task 存在，但其 sector 没有加载 chain_topology → 404。"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/2/chain-graph")

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "chain_topology" in detail
    assert "xyz" in detail.lower()


@pytest.mark.asyncio
async def test_chain_graph_404_when_explicit_sector_unknown(override_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        resp = await client.get("/api/tasks/1/chain-graph?sector=ghost")

    assert resp.status_code == 404
