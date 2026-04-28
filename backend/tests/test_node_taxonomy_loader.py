"""node_taxonomy_loader 单元测试

覆盖:
- 完整加载 xlk.yaml — 节点/边/proxy/basket 数量正确
- 幂等：重复加载不增加行数
- 更新：修改节点 label 后重新加载，DB 中已更新
- 非法引用：edge 引用不存在 node_id → ValueError
- 非法引用：basket 引用不存在 node_id → ValueError
- 空段：YAML 中缺少 edges/baskets 段不报错
"""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import (
    AnalyticNode,
    Base,
    NodeEdge,
    NodeProxy,
    SyntheticBasketDefinition,
)
from app.services.node_taxonomy_loader import load_taxonomy

# xlk.yaml 真实路径: backend/data/node_taxonomy/xlk.yaml
# __file__ = backend/tests/test_*.py → parents[1] = backend/
_YAML_PATH = Path(__file__).parents[1] / "data" / "node_taxonomy" / "xlk.yaml"

# 按需求文档 §4 固定期望计数
_EXPECTED_NODES = 12
_EXPECTED_EDGES = 15
_EXPECTED_PROXIES = 9  # +3 (semi-equip/SMH, semi-mem/DRAM, semi-conn/SIXG) Task 4.12
_EXPECTED_BASKETS_MIN = 26


@pytest.fixture()
def session():
    """每个测试一个独立的内存 SQLite 数据库"""
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
    """返回一个可写临时 YAML 路径和写入函数"""
    yaml_file = tmp_path / "test.yaml"

    def _write(data: dict) -> Path:
        with yaml_file.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True)
        return yaml_file

    return _write


# ---------------------------------------------------------------------------
# 1. 完整加载 xlk.yaml
# ---------------------------------------------------------------------------

def test_load_xlk_yaml_node_count(session):
    counts = load_taxonomy(_YAML_PATH, db=session)
    assert counts["nodes"] == _EXPECTED_NODES


def test_load_xlk_yaml_edge_count(session):
    counts = load_taxonomy(_YAML_PATH, db=session)
    assert counts["edges"] == _EXPECTED_EDGES


def test_load_xlk_yaml_proxy_count(session):
    counts = load_taxonomy(_YAML_PATH, db=session)
    assert counts["proxies"] == _EXPECTED_PROXIES


def test_load_xlk_yaml_basket_min(session):
    counts = load_taxonomy(_YAML_PATH, db=session)
    assert counts["baskets"] >= _EXPECTED_BASKETS_MIN


def test_semi_has_two_proxies(session):
    """node_id='semi' 应有 SOXX(primary) + SMH(secondary) 两条 proxy"""
    session.commit()
    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    rows = session.query(NodeProxy).filter_by(node_id="semi").all()
    assert len(rows) == 2
    roles = {r.role for r in rows}
    assert roles == {"primary", "secondary"}


# ---------------------------------------------------------------------------
# 2. 幂等：重复加载，行数不变
# ---------------------------------------------------------------------------

def test_idempotent_nodes(session):
    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    first = session.query(AnalyticNode).count()

    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    second = session.query(AnalyticNode).count()

    assert first == second


def test_idempotent_edges(session):
    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    first = session.query(NodeEdge).count()

    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    second = session.query(NodeEdge).count()

    assert first == second


def test_idempotent_proxies(session):
    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    first = session.query(NodeProxy).count()

    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    second = session.query(NodeProxy).count()

    assert first == second


def test_idempotent_baskets(session):
    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    first = session.query(SyntheticBasketDefinition).count()

    load_taxonomy(_YAML_PATH, db=session)
    session.commit()
    second = session.query(SyntheticBasketDefinition).count()

    assert first == second


# ---------------------------------------------------------------------------
# 3. 更新：修改 label 后重新加载，DB 中已更新
# ---------------------------------------------------------------------------

def test_update_node_label(tmp_yaml, session):
    data = {
        "nodes": [
            {"node_id": "n1", "label": "原始标签", "node_type": "gics", "level": 0}
        ],
        "edges": [],
        "proxies": [],
        "baskets": [],
    }
    yaml_path = tmp_yaml(data)
    load_taxonomy(yaml_path, db=session)
    session.commit()

    data["nodes"][0]["label"] = "更新标签"
    tmp_yaml(data)  # 覆写同一路径
    load_taxonomy(yaml_path, db=session)
    session.commit()

    row = session.query(AnalyticNode).filter_by(node_id="n1").one()
    assert row.label == "更新标签"


# ---------------------------------------------------------------------------
# 4. 非法引用：edge 引用不存在 node_id
# ---------------------------------------------------------------------------

def test_edge_references_missing_node_raises(tmp_yaml, session):
    data = {
        "nodes": [
            {"node_id": "n1", "label": "A", "node_type": "gics", "level": 0}
        ],
        "edges": [
            {"src": "n1", "dst": "ghost", "type": "chain_parent"}
        ],
        "proxies": [],
        "baskets": [],
    }
    yaml_path = tmp_yaml(data)
    with pytest.raises(ValueError, match="ghost"):
        load_taxonomy(yaml_path, db=session)


def test_edge_src_missing_node_raises(tmp_yaml, session):
    data = {
        "nodes": [
            {"node_id": "n1", "label": "A", "node_type": "gics", "level": 0}
        ],
        "edges": [
            {"src": "ghost", "dst": "n1", "type": "chain_parent"}
        ],
        "proxies": [],
        "baskets": [],
    }
    yaml_path = tmp_yaml(data)
    with pytest.raises(ValueError, match="ghost"):
        load_taxonomy(yaml_path, db=session)


# ---------------------------------------------------------------------------
# 5. 非法引用：basket 引用不存在 node_id
# ---------------------------------------------------------------------------

def test_basket_references_missing_node_raises(tmp_yaml, session):
    data = {
        "nodes": [
            {"node_id": "n1", "label": "A", "node_type": "gics", "level": 0}
        ],
        "edges": [],
        "proxies": [],
        "baskets": [
            {"node_id": "ghost", "ticker": "NVDA", "weighting_strategy": "equal"}
        ],
    }
    yaml_path = tmp_yaml(data)
    with pytest.raises(ValueError, match="ghost"):
        load_taxonomy(yaml_path, db=session)


# ---------------------------------------------------------------------------
# 6. 空 edges / baskets 段
# ---------------------------------------------------------------------------

def test_missing_edges_and_baskets_section(tmp_yaml, session):
    """YAML 只有 nodes，缺少 edges/baskets 段不应报错"""
    data = {
        "nodes": [
            {"node_id": "n1", "label": "A", "node_type": "gics", "level": 0}
        ],
    }
    yaml_path = tmp_yaml(data)
    counts = load_taxonomy(yaml_path, db=session)
    assert counts["nodes"] == 1
    assert counts["edges"] == 0
    assert counts["baskets"] == 0


# ---------------------------------------------------------------------------
# 7. 文件不存在
# ---------------------------------------------------------------------------

def test_file_not_found_raises(tmp_path, session):
    with pytest.raises(FileNotFoundError):
        load_taxonomy(tmp_path / "nonexistent.yaml", db=session)
