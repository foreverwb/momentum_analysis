"""Phase 4 Task 4.5: drilldown 任务迁移到 Node-Centric 模型的测试。

覆盖：
- dry_run 不写库
- --commit 后 root_node / selected_nodes 正确填充
- 找不到 NodeProxy 的 ETF 落到 extra.selected_etfs_legacy
- 幂等：重复执行已迁移任务被 skipped
- 旧 API（不带 rootNode）仍能创建 drilldown 任务
- 新 API（带 rootNode）创建任务时不再强制 etfs 为 industry
- format_task_response 包含五个 camelCase 字段
"""

import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models import (
    Base,
    ETF,
    Task,
    AnalyticNode,
    NodeProxy,
    get_db,
)
from app.models.database import NodeType, NodeProxyRole
from app.services.migrations import migrate_drilldown_tasks_to_node_first


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
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_xlk_taxonomy(db) -> None:
    """种 XLK / semi / soft / soft-cloud 节点 + SOXX/IGV/SKYY proxy。"""
    nodes = [
        AnalyticNode(node_id="XLK", label="XLK", node_type=NodeType.GICS.value, level=0),
        AnalyticNode(node_id="semi", label="半导体", node_type=NodeType.GICS.value, level=1),
        AnalyticNode(node_id="soft", label="软件", node_type=NodeType.GICS.value, level=1),
        AnalyticNode(node_id="soft-cloud", label="云计算", node_type=NodeType.EVIDENCE.value, level=2),
    ]
    db.add_all(nodes)
    db.flush()

    proxies = [
        NodeProxy(node_id="XLK", etf_symbol="XLK", role=NodeProxyRole.PRIMARY.value, purity=1.0),
        NodeProxy(node_id="semi", etf_symbol="SOXX", role=NodeProxyRole.PRIMARY.value, purity=0.95),
        NodeProxy(node_id="soft", etf_symbol="IGV", role=NodeProxyRole.PRIMARY.value, purity=0.9),
        NodeProxy(node_id="soft-cloud", etf_symbol="SKYY", role=NodeProxyRole.PRIMARY.value, purity=0.75),
    ]
    db.add_all(proxies)
    db.commit()


def _seed_three_drilldown_tasks(db) -> list:
    tasks = [
        Task(title="Drill XLK 1", type="drilldown", base_index="SPY",
             sector="XLK", etfs=["SOXX", "IGV", "SKYY"]),
        Task(title="Drill XLK 2", type="drilldown", base_index="SPY",
             sector="XLK", etfs=["SOXX", "IGV", "SKYY"]),
        Task(title="Drill XLK 3", type="drilldown", base_index="SPY",
             sector="XLK", etfs=["SOXX", "IGV", "SKYY"]),
    ]
    db.add_all(tasks)
    db.commit()
    return tasks


def test_dry_run_does_not_mutate_db(db_session):
    _seed_xlk_taxonomy(db_session)
    _seed_three_drilldown_tasks(db_session)

    result = migrate_drilldown_tasks_to_node_first(db_session, dry_run=True)

    assert result["migrated"] == 3
    assert result["skipped"] == 0

    # DB 不应被修改
    for task in db_session.query(Task).all():
        assert task.root_node in (None, "")
        assert (task.selected_nodes or []) == []


def test_commit_migrates_to_node_first(db_session):
    _seed_xlk_taxonomy(db_session)
    tasks = _seed_three_drilldown_tasks(db_session)

    result = migrate_drilldown_tasks_to_node_first(db_session, dry_run=False)

    assert result["migrated"] == 3
    assert result["skipped"] == 0

    for task in tasks:
        db_session.refresh(task)
        assert task.root_node == "XLK"
        # selected_nodes 必须包含 root + 三个 ETF 反查到的 node_id（顺序按 ETF 出现顺序）
        assert task.selected_nodes == ["XLK", "semi", "soft", "soft-cloud"]
        assert task.view_mode == "gics"
        assert task.max_depth == 3


def test_migration_is_idempotent(db_session):
    _seed_xlk_taxonomy(db_session)
    _seed_three_drilldown_tasks(db_session)

    migrate_drilldown_tasks_to_node_first(db_session, dry_run=False)
    second = migrate_drilldown_tasks_to_node_first(db_session, dry_run=False)

    assert second["migrated"] == 0
    assert second["skipped"] == 3


def test_unmapped_etf_falls_into_legacy_extra(db_session):
    _seed_xlk_taxonomy(db_session)
    db_session.add(Task(
        title="Drill mixed", type="drilldown", base_index="SPY",
        sector="XLK", etfs=["SOXX", "MYSTERY"],
    ))
    db_session.commit()

    migrate_drilldown_tasks_to_node_first(db_session, dry_run=False)

    task = db_session.query(Task).filter(Task.title == "Drill mixed").one()
    assert task.root_node == "XLK"
    assert task.selected_nodes == ["XLK", "semi"]
    assert (task.extra or {}).get("selected_etfs_legacy") == ["MYSTERY"]


# ---------- API 兼容性 ----------

@pytest.fixture()
def api_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    db.add_all([
        ETF(symbol="XLK", name="Tech", type="sector", rank=1, score=80),
        ETF(symbol="SOXX", name="Semi", type="industry", parent_sector="XLK", rank=1, score=85),
        ETF(symbol="IGV", name="Soft", type="industry", parent_sector="XLK", rank=2, score=78),
        ETF(symbol="SKYY", name="Cloud", type="industry", parent_sector="XLK", rank=3, score=72),
    ])
    db.commit()

    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def override_api_db(api_db):
    def override_get_db():
        yield api_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_legacy_create_without_root_node_still_works(override_api_db):
    payload = {
        "title": "Old Drill",
        "type": "drilldown",
        "baseIndex": "SPY",
        "sector": "XLK",
        "etfs": ["SOXX"],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/tasks", json=payload)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sector"] == "XLK"
    assert body["etfs"] == ["SOXX"]
    assert body["rootNode"] is None
    assert body["viewMode"] == "gics"
    assert body["selectedNodes"] == []
    assert body["pinnedEvidenceNodes"] == []
    assert body["maxDepth"] == 3


@pytest.mark.asyncio
async def test_node_first_create_skips_industry_check(override_api_db, api_db):
    # 加一个 sector ETF 与 root_node 不匹配的场景: 选择 XLK (sector) 作为 etfs
    # 旧校验会拒绝（drilldown 必须为 industry），新校验 (rootNode 已设) 应放行
    payload = {
        "title": "Node-First Drill",
        "type": "drilldown",
        "baseIndex": "SPY",
        "sector": "XLK",
        "etfs": ["XLK", "SOXX"],
        "rootNode": "XLK",
        "viewMode": "gics",
        "selectedNodes": ["XLK", "semi"],
        "maxDepth": 4,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/tasks", json=payload)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rootNode"] == "XLK"
    assert body["selectedNodes"] == ["XLK", "semi"]
    assert body["maxDepth"] == 4
    assert body["etfs"] == ["XLK", "SOXX"]


@pytest.mark.asyncio
async def test_legacy_create_still_rejects_industry_mismatch(override_api_db):
    # rootNode 未设 -> 走旧校验, sector 不指定时 drilldown 必须报 400
    payload = {
        "title": "Bad",
        "type": "drilldown",
        "baseIndex": "SPY",
        "etfs": ["SOXX"],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/tasks", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_tasks_includes_new_fields(override_api_db, api_db):
    api_db.add(Task(
        title="LegacyOnDisk", type="drilldown", base_index="SPY",
        sector="XLK", etfs=["SOXX"],
    ))
    api_db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/tasks")

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    item = items[0]
    for key in ("rootNode", "viewMode", "selectedNodes", "pinnedEvidenceNodes", "maxDepth"):
        assert key in item
