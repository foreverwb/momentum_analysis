"""chain_strategy 计算引擎单元测试（Phase 4 DD-4）。

验收覆盖：
1. l1_ranking 按 score 降序
2. breadth: ≥3 → 全面 / ==2 → 主线 / 其它 → 单点
3. confirmation message：compute_leading=True → 算力领涨提示；False → 上下游联动提示
4. best_drill 选 delta5d 最大者；候选全为 None → 返回 None
5. 节点缺失（不在 nodes dict 中）按 score=0 / delta5d=None 处理，不抛异常
6. 通过 load_chain_strategy_config 端到端读 xlk.yaml
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from app.services.calculators.chain_strategy import (
    StrategyConfig,
    StrategyNodeBrief,
    compute_chain_strategy,
    load_chain_strategy_config,
)


# ─── 测试夹具 ────────────────────────────────────────────────────────────────

_CONFIG = StrategyConfig(
    l1_nodes=["semi", "soft", "hw"],
    equip_node="semi-equip",
    conn_node="semi-conn",
    compute_node="semi-compute",
    l2_drill_nodes=[
        "semi-equip", "semi-compute", "semi-mem",
        "semi-conn", "soft-cloud", "soft-cyber",
    ],
)


def _brief(node_id: str, score: float, delta5d: float | None = 0.0,
           label: str | None = None, sublabel: str | None = None) -> StrategyNodeBrief:
    return StrategyNodeBrief(
        id=node_id,
        label=label or node_id,
        sublabel=sublabel or node_id,
        score=score,
        delta5d=delta5d,
    )


def _build_nodes(score_map: Dict[str, float],
                 delta_map: Dict[str, float | None] | None = None
                 ) -> Dict[str, StrategyNodeBrief]:
    delta_map = delta_map or {}
    return {
        nid: _brief(nid, score, delta_map.get(nid, 0.0))
        for nid, score in score_map.items()
    }


_CHILDREN_MAP: Dict[str, List[str]] = {
    "semi": ["semi-equip", "semi-compute", "semi-mem", "semi-conn"],
    "soft": ["soft-cloud", "soft-cyber"],
    "hw":   [],
}


# ─── L1 排名 ────────────────────────────────────────────────────────────────

def test_l1_ranking_sorted_desc():
    nodes = _build_nodes({"semi": 80.0, "soft": 65.0, "hw": 72.0,
                          "semi-equip": 50.0, "semi-compute": 50.0,
                          "semi-mem": 50.0, "semi-conn": 50.0})
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert [b.id for b in res.l1_ranking] == ["semi", "hw", "soft"]


def test_l1_ranking_skips_missing_nodes():
    """L1 节点不在 nodes 中时跳过（不报错）。"""
    nodes = _build_nodes({"semi": 80.0})  # soft / hw 缺失
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert [b.id for b in res.l1_ranking] == ["semi"]


# ─── Q2 breadth ─────────────────────────────────────────────────────────────

def test_breadth_full_diffusion():
    """semi 子节点 ≥3 个 >75 → 全面扩散。"""
    nodes = _build_nodes({
        "semi": 80.0, "soft": 60.0, "hw": 60.0,
        "semi-equip": 80.0, "semi-compute": 78.0,
        "semi-mem": 76.0, "semi-conn": 70.0,
    })
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.breadth.label == "全面扩散"
    assert res.breadth.strong_count == 3
    assert res.breadth.total == 4


def test_breadth_main_drive():
    """正好 2 个 >75 → 主线驱动。"""
    nodes = _build_nodes({
        "semi": 80.0, "soft": 60.0, "hw": 60.0,
        "semi-equip": 80.0, "semi-compute": 78.0,
        "semi-mem": 60.0, "semi-conn": 60.0,
    })
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.breadth.label == "主线驱动"
    assert res.breadth.strong_count == 2


def test_breadth_single_pull():
    """1 个 >75 → 单点拉动。"""
    nodes = _build_nodes({
        "semi": 80.0, "soft": 60.0, "hw": 60.0,
        "semi-equip": 80.0, "semi-compute": 60.0,
        "semi-mem": 60.0, "semi-conn": 60.0,
    })
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.breadth.label == "单点拉动"
    assert res.breadth.strong_count == 1


def test_breadth_top_l1_no_children():
    """top L1 在 children_map 中不存在 → strong_count=0 / total=0 / 单点。"""
    nodes = _build_nodes({"semi": 80.0, "soft": 60.0, "hw": 60.0})
    res = compute_chain_strategy(nodes, {}, _CONFIG)
    assert res.breadth.total == 0
    assert res.breadth.strong_count == 0
    assert res.breadth.label == "单点拉动"


# ─── Q3 confirmation message switching（验收要求） ───────────────────────────

def test_confirmation_compute_leading_message():
    """compute > equip 且 compute > conn → 「算力领涨」提示。"""
    nodes = _build_nodes({
        "semi": 80.0, "soft": 60.0, "hw": 60.0,
        "semi-equip": 60.0, "semi-conn": 55.0, "semi-compute": 85.0,
    })
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.confirmation.compute_leading is True
    assert res.confirmation.equip_score == 60.0
    assert res.confirmation.conn_score == 55.0
    assert res.confirmation.compute_score == 85.0
    assert "算力领涨" in res.confirmation.message
    assert "主线扩散中段" in res.confirmation.message


def test_confirmation_broad_message_when_equip_leads():
    """compute 不双向最大 → 「上下游联动」提示。"""
    nodes = _build_nodes({
        "semi": 80.0,
        "semi-equip": 90.0, "semi-conn": 80.0, "semi-compute": 70.0,
    })
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.confirmation.compute_leading is False
    assert "上下游联动" in res.confirmation.message


def test_confirmation_broad_message_when_tied_with_conn():
    """compute == conn（非严格大于）→ 不算领涨 → 上下游联动提示。"""
    nodes = _build_nodes({
        "semi-equip": 50.0, "semi-conn": 80.0, "semi-compute": 80.0,
    })
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.confirmation.compute_leading is False
    assert "上下游联动" in res.confirmation.message


def test_confirmation_missing_nodes_default_zero():
    """三节点全缺 → 全部 0；compute 不大于 equip 也不大于 conn → 上下游联动提示。"""
    res = compute_chain_strategy({}, _CHILDREN_MAP, _CONFIG)
    assert res.confirmation.equip_score == 0.0
    assert res.confirmation.conn_score == 0.0
    assert res.confirmation.compute_score == 0.0
    assert res.confirmation.compute_leading is False


# ─── Q4 best_drill ──────────────────────────────────────────────────────────

def test_best_drill_picks_max_delta5d():
    nodes = _build_nodes(
        score_map={
            "semi-equip": 70.0, "semi-compute": 80.0, "semi-mem": 60.0,
            "semi-conn": 65.0, "soft-cloud": 75.0, "soft-cyber": 70.0,
        },
        delta_map={
            "semi-equip": 1.5, "semi-compute": 4.2, "semi-mem": -0.8,
            "semi-conn": 2.0, "soft-cloud": 3.1, "soft-cyber": 0.0,
        },
    )
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.best_drill is not None
    assert res.best_drill.id == "semi-compute"


def test_best_drill_none_when_all_missing():
    """L2 候选全部缺数据（delta5d=None）→ best_drill=None。"""
    nodes = {
        nid: _brief(nid, 70.0, delta5d=None)
        for nid in _CONFIG.l2_drill_nodes
    }
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.best_drill is None


# ─── 配置加载 ────────────────────────────────────────────────────────────────

def test_load_xlk_strategy_config():
    cfg = load_chain_strategy_config("xlk")
    assert cfg.l1_nodes == ["semi", "soft", "hw"]
    assert cfg.equip_node == "semi-equip"
    assert cfg.conn_node == "semi-conn"
    assert cfg.compute_node == "semi-compute"
    assert "semi-equip" in cfg.l2_drill_nodes
    assert "soft-cyber" in cfg.l2_drill_nodes


def test_load_strategy_config_case_insensitive():
    lo = load_chain_strategy_config("xlk")
    hi = load_chain_strategy_config("XLK")
    assert lo.l1_nodes == hi.l1_nodes


def test_load_missing_sector_raises():
    with pytest.raises(FileNotFoundError):
        load_chain_strategy_config("nonexistent_sector_xyz")


# ─── best_drill 边界：空集 / 全负 5D ─────────────────────────────────────────

def test_best_drill_all_absent_from_nodes_dict():
    """L2 候选节点完全不在 nodes dict 中（空集）→ best_drill=None。"""
    res = compute_chain_strategy({}, _CHILDREN_MAP, _CONFIG)
    assert res.best_drill is None


def test_best_drill_all_negative_delta5d():
    """所有 L2 候选 delta5d 均为负值 → 仍选出最大（绝对值最小的负数）。"""
    nodes = _build_nodes(
        score_map={
            "semi-equip": 70.0, "semi-compute": 70.0, "semi-mem": 70.0,
            "semi-conn": 70.0, "soft-cloud": 70.0, "soft-cyber": 70.0,
        },
        delta_map={
            "semi-equip": -5.0, "semi-compute": -1.2, "semi-mem": -3.8,
            "semi-conn": -2.0, "soft-cloud": -4.5, "soft-cyber": -6.0,
        },
    )
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.best_drill is not None
    assert res.best_drill.id == "semi-compute"   # -1.2 是最大值


# ─── breadth top_l1=None 分支（所有 L1 节点缺失） ────────────────────────────

def test_breadth_top_l1_none_when_all_l1_absent():
    """nodes dict 中无任何 L1 节点 → l1_ranking 为空 → top_l1=None → 单点/0/0。"""
    nodes = _build_nodes({"semi-equip": 80.0, "semi-compute": 78.0})  # 只有 L2
    res = compute_chain_strategy(nodes, _CHILDREN_MAP, _CONFIG)
    assert res.l1_ranking == []
    assert res.breadth.label == "单点拉动"
    assert res.breadth.strong_count == 0
    assert res.breadth.total == 0
