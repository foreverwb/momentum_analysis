"""chain_topology_loader 单元测试（Task DD-10）

覆盖：
- dry_run：仅解析、不写库
- commit：从 xlk.yaml 写入 12 节点 + 12 边
- 重复执行：幂等（行数不增、字段更新）
- 回滚：引用未声明 node_id 的边 → ValueError，且不残留任何行
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import Base, ChainEdge, ChainNode
from app.services.chain_topology_loader import (
    configs_dir,
    load_all_chain_topologies,
    load_chain_topology,
)

# 真实拓扑文件路径
_XLK_YAML = configs_dir() / "xlk.yaml"
_EXPECTED_NODES = 12
_EXPECTED_EDGES = 12


@pytest.fixture()
def session():
    """每个测试一个独立的内存 SQLite 数据库。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    DB = sessionmaker(bind=engine)
    db = DB()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def tmp_yaml(tmp_path):
    """返回一个写临时 YAML 的工厂。"""
    file_idx = {"i": 0}

    def _write(data: dict, name: str | None = None) -> Path:
        if name is None:
            file_idx["i"] += 1
            name = f"sector{file_idx['i']}.yaml"
        path = tmp_path / name
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True)
        return path

    return _write


# ---------------------------------------------------------------------------
# 1. dry_run：YAML 行数返回，但不写库
# ---------------------------------------------------------------------------


def test_dry_run_returns_yaml_counts(session):
    counts = load_chain_topology("xlk", db=session, dry_run=True)
    assert counts == {"nodes": _EXPECTED_NODES, "edges": _EXPECTED_EDGES}


def test_dry_run_does_not_write_db(session):
    load_chain_topology("xlk", db=session, dry_run=True)
    assert session.query(ChainNode).count() == 0
    assert session.query(ChainEdge).count() == 0


# ---------------------------------------------------------------------------
# 2. commit：xlk.yaml → 12 节点 + 12 边
# ---------------------------------------------------------------------------


def test_commit_writes_xlk_topology(session):
    counts = load_chain_topology("xlk", db=session)
    session.commit()
    assert counts == {"nodes": _EXPECTED_NODES, "edges": _EXPECTED_EDGES}
    assert session.query(ChainNode).count() == _EXPECTED_NODES
    assert session.query(ChainEdge).count() == _EXPECTED_EDGES


def test_commit_xlk_node_fields_populated(session):
    load_chain_topology("xlk", db=session)
    session.commit()

    xlk = session.query(ChainNode).filter_by(node_id="XLK", sector="xlk").one()
    assert xlk.role == "root"
    assert xlk.tier == 0
    assert xlk.cx is not None and xlk.cy is not None
    assert xlk.proxy == "XLK"
    assert xlk.proxy_type == "primary"
    # task_id 必须为 NULL（板块模板）
    assert xlk.task_id is None


def test_commit_xlk_edge_is_cross_flag(session):
    """soft -> soft-cloud 是 corroborates，应被标为 cross；XLK -> semi 不是。"""
    load_chain_topology("xlk", db=session)
    session.commit()

    main = (
        session.query(ChainEdge)
        .filter_by(src_node_id="XLK", dst_node_id="semi")
        .one()
    )
    assert main.is_cross is False

    cross = (
        session.query(ChainEdge)
        .filter_by(src_node_id="soft", dst_node_id="soft-cloud")
        .one()
    )
    assert cross.is_cross is True


# ---------------------------------------------------------------------------
# 3. 幂等：重复执行行数不变，字段更新生效
# ---------------------------------------------------------------------------


def test_idempotent_repeat_load(session):
    load_chain_topology("xlk", db=session)
    session.commit()
    nodes_first = session.query(ChainNode).count()
    edges_first = session.query(ChainEdge).count()

    load_chain_topology("xlk", db=session)
    session.commit()
    assert session.query(ChainNode).count() == nodes_first
    assert session.query(ChainEdge).count() == edges_first


def test_idempotent_updates_changed_fields(tmp_yaml, session):
    """重复加载时，YAML 里的字段变更应反映到 DB。"""
    data = {
        "sector": "tst",
        "nodes": [
            {"node_id": "n1", "role": "root", "tier": 0, "cx": 10, "cy": 10,
             "proxy": "X", "proxy_type": "primary", "proxy_label": "原始"},
        ],
        "edges": [],
    }
    path = tmp_yaml(data, name="tst.yaml")
    load_chain_topology("tst", db=session, yaml_path=path)
    session.commit()

    data["nodes"][0]["proxy_label"] = "更新"
    data["nodes"][0]["cx"] = 99
    tmp_yaml(data, name="tst.yaml")  # 覆写
    load_chain_topology("tst", db=session, yaml_path=path)
    session.commit()

    row = session.query(ChainNode).filter_by(node_id="n1", sector="tst").one()
    assert row.proxy_label == "更新"
    assert row.cx == 99
    assert session.query(ChainNode).count() == 1


# ---------------------------------------------------------------------------
# 4. 回滚：引用未声明 node_id → ValueError，且 DB 中不残留
# ---------------------------------------------------------------------------


def test_invalid_edge_reference_raises(tmp_yaml, session):
    data = {
        "sector": "bad",
        "nodes": [
            {"node_id": "n1", "role": "root", "tier": 0},
        ],
        "edges": [
            {"src": "n1", "dst": "ghost", "is_cross": False},
        ],
    }
    path = tmp_yaml(data, name="bad.yaml")
    with pytest.raises(ValueError, match="ghost"):
        load_chain_topology("bad", db=session, yaml_path=path)


def test_invalid_edge_rolls_back_when_loader_owns_session(tmp_path):
    """loader 自管 session 时，校验失败不应写入任何行。"""
    data = {
        "sector": "bad",
        "nodes": [
            {"node_id": "n1", "role": "root", "tier": 0},
        ],
        "edges": [
            {"src": "ghost", "dst": "n1"},
        ],
    }
    path = tmp_path / "bad.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True)

    # 用全局 SessionLocal 让 loader 自管 commit/rollback
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import database as db_mod

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    original_session_local = db_mod.SessionLocal
    db_mod.SessionLocal = TestingSession  # type: ignore[assignment]
    # 同时 patch loader 内部捕获的引用
    import app.services.chain_topology_loader as loader_mod
    original_loader_session_local = loader_mod.SessionLocal
    loader_mod.SessionLocal = TestingSession  # type: ignore[attr-defined]

    try:
        with pytest.raises(ValueError):
            load_chain_topology("bad", yaml_path=path)
        # 校验在写库前完成 → 不应有任何行
        verify = TestingSession()
        try:
            assert verify.query(ChainNode).count() == 0
            assert verify.query(ChainEdge).count() == 0
        finally:
            verify.close()
    finally:
        db_mod.SessionLocal = original_session_local  # type: ignore[assignment]
        loader_mod.SessionLocal = original_loader_session_local  # type: ignore[attr-defined]
        engine.dispose()


def test_duplicate_node_id_raises(tmp_yaml, session):
    data = {
        "sector": "dup",
        "nodes": [
            {"node_id": "n1", "role": "root"},
            {"node_id": "n1", "role": "root"},
        ],
        "edges": [],
    }
    path = tmp_yaml(data, name="dup.yaml")
    with pytest.raises(ValueError, match="重复"):
        load_chain_topology("dup", db=session, yaml_path=path)


# ---------------------------------------------------------------------------
# 5. 文件不存在 / 板块名容错
# ---------------------------------------------------------------------------


def test_missing_sector_file_raises(session):
    with pytest.raises(FileNotFoundError):
        load_chain_topology("nope-sector-xyz", db=session)


def test_sector_lookup_is_case_insensitive(session):
    counts = load_chain_topology("XLK", db=session)
    session.commit()
    assert counts["nodes"] == _EXPECTED_NODES


# ---------------------------------------------------------------------------
# 6. load_all_chain_topologies：扫描目录
# ---------------------------------------------------------------------------


def test_load_all_includes_xlk(session):
    summary = load_all_chain_topologies(db=session)
    session.commit()
    assert "xlk" in summary
    assert summary["xlk"]["nodes"] == _EXPECTED_NODES
    assert summary["xlk"]["edges"] == _EXPECTED_EDGES
