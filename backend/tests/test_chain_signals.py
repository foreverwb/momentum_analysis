"""chain_signals 计算引擎单元测试（Phase 4 DD-8）。

验收覆盖：
1. n=0（全不触发）→ label='链条断裂', color='#dc2626'
2. n=1（仅上游）→ label='单点拉动', color='#d97706'
3. n=2（上游 + 同层扩散）→ label='主线扩散', color='#2563eb'
4. n=3（全部触发）→ label='全链共振', color='#059669'
5. 节点缺失（score=0）→ 不抛异常，视为未触发
6. load_chain_signal_rules 读取 xlk.yaml 成功
7. compute_chain_signals_for_sector 端到端 xlk 场景
8. 配置文件不存在 → FileNotFoundError
"""

from __future__ import annotations

import os
import pytest

from app.services.calculators.chain_signals import (
    BroadRule,
    ChainSignalRules,
    DownstreamRule,
    UpstreamRule,
    compute_chain_signals,
    compute_chain_signals_for_sector,
    load_chain_signal_rules,
)

# ─── 共用测试规则（与 xlk.yaml 同构，但阈值明确写在这里方便断言） ──────────
_RULES = ChainSignalRules(
    upstream=UpstreamRule(
        watched_nodes=["semi-equip"],
        threshold=70.0,
    ),
    broad=BroadRule(
        watched_nodes=["semi-equip", "semi-compute", "semi-mem", "semi-conn"],
        threshold=75.0,
        min_count=3,
    ),
    downstream=DownstreamRule(
        watched_nodes=["conn-optical", "conn-copper"],
        threshold=75.0,
    ),
)


# ─── n=0: 全不触发 ────────────────────────────────────────────────────────────

def test_no_signals_link_broken():
    """所有节点分均低于阈值 → 链条断裂。"""
    scores = {
        "semi-equip": 60.0,
        "semi-compute": 60.0,
        "semi-mem": 60.0,
        "semi-conn": 60.0,
        "conn-optical": 50.0,
        "conn-copper": 50.0,
    }
    result = compute_chain_signals(scores, _RULES)
    assert result.upstream is False
    assert result.broad is False
    assert result.downstream is False
    assert result.label == "链条断裂"
    assert result.color == "#dc2626"


# ─── n=1: 仅上游共振 ─────────────────────────────────────────────────────────

def test_only_upstream_single_pull():
    """semi-equip > 70 但 broad 不满足（< 3 节点 > 75），downstream 也不满足。"""
    scores = {
        "semi-equip": 71.0,    # 上游触发
        "semi-compute": 74.0,  # 未超 75
        "semi-mem": 60.0,
        "semi-conn": 60.0,
        "conn-optical": 50.0,
        "conn-copper": 50.0,
    }
    result = compute_chain_signals(scores, _RULES)
    assert result.upstream is True
    assert result.broad is False
    assert result.downstream is False
    assert result.label == "单点拉动"
    assert result.color == "#d97706"


# ─── n=2: 上游 + 同层扩散 ────────────────────────────────────────────────────

def test_upstream_and_broad_main_diffusion():
    """semi-equip > 70 且 3 个节点 > 75（broad），但 downstream 不达标。"""
    scores = {
        "semi-equip": 80.0,    # upstream 触发 (> 70) + broad 计数 (> 75)
        "semi-compute": 76.0,  # broad 计数
        "semi-mem": 77.0,      # broad 计数 → total 3, broad 触发
        "semi-conn": 60.0,     # broad 未计数
        "conn-optical": 70.0,  # downstream 未触发 (= 70, 不 > 75)
        "conn-copper": 50.0,
    }
    result = compute_chain_signals(scores, _RULES)
    assert result.upstream is True
    assert result.broad is True
    assert result.downstream is False
    assert result.label == "主线扩散"
    assert result.color == "#2563eb"


# ─── n=3: 全链共振 ───────────────────────────────────────────────────────────

def test_all_signals_full_chain():
    """三维全部满足 → 全链共振。"""
    scores = {
        "semi-equip": 85.0,
        "semi-compute": 82.0,
        "semi-mem": 80.0,
        "semi-conn": 78.0,
        "conn-optical": 76.0,  # downstream 触发
        "conn-copper": 50.0,
    }
    result = compute_chain_signals(scores, _RULES)
    assert result.upstream is True
    assert result.broad is True
    assert result.downstream is True
    assert result.label == "全链共振"
    assert result.color == "#059669"


# ─── 边界：节点缺失（默认 0） ─────────────────────────────────────────────────

def test_missing_nodes_treated_as_zero():
    """node_scores 为空字典 → 全部视为 0，不抛异常，输出 链条断裂。"""
    result = compute_chain_signals({}, _RULES)
    assert result.upstream is False
    assert result.broad is False
    assert result.downstream is False
    assert result.label == "链条断裂"


def test_partial_missing_nodes():
    """部分节点缺失；缺失节点视为 0 不触发 broad。"""
    scores = {
        "semi-equip": 80.0,    # upstream 触发
        # semi-compute / semi-mem / semi-conn 缺失 → 全为 0
        "conn-optical": 76.0,  # downstream 触发
    }
    result = compute_chain_signals(scores, _RULES)
    assert result.upstream is True
    assert result.broad is False    # 仅 semi-equip 超阈值，count=1 < min_count=3
    assert result.downstream is True
    assert result.label == "主线扩散"  # n=2


# ─── 配置加载 ─────────────────────────────────────────────────────────────────

def test_load_xlk_rules_from_yaml():
    """load_chain_signal_rules('xlk') 应正确解析 xlk.yaml。"""
    rules = load_chain_signal_rules("xlk")
    assert "semi-equip" in rules.upstream.watched_nodes
    assert rules.upstream.threshold == 70.0
    assert rules.broad.min_count == 3
    assert rules.broad.threshold == 75.0
    assert "conn-optical" in rules.downstream.watched_nodes
    assert "conn-copper" in rules.downstream.watched_nodes
    assert rules.downstream.threshold == 75.0


def test_load_rules_case_insensitive():
    """sector 参数大小写不敏感（'XLK' 与 'xlk' 均可）。"""
    rules_lower = load_chain_signal_rules("xlk")
    rules_upper = load_chain_signal_rules("XLK")
    assert rules_lower.upstream.threshold == rules_upper.upstream.threshold


def test_load_missing_sector_raises():
    """不存在的 sector 配置 → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_chain_signal_rules("nonexistent_sector_xyz")


# ─── 端到端：compute_chain_signals_for_sector ─────────────────────────────────

def test_compute_chain_signals_for_sector_xlk_all_zero():
    """端到端：xlk 配置 + 全零分 → 链条断裂（不抛异常）。"""
    result = compute_chain_signals_for_sector({}, "xlk")
    assert result.label == "链条断裂"
    assert result.color == "#dc2626"


def test_compute_chain_signals_for_sector_xlk_full_resonance():
    """端到端：xlk 配置 + 全高分 → 全链共振。"""
    scores = {
        "semi-equip": 90.0,
        "semi-compute": 88.0,
        "semi-mem": 85.0,
        "semi-conn": 82.0,
        "conn-optical": 80.0,
        "conn-copper": 78.0,
    }
    result = compute_chain_signals_for_sector(scores, "xlk")
    assert result.label == "全链共振"
    assert result.upstream is True
    assert result.broad is True
    assert result.downstream is True


# ─── downstream OR 语义：任一满足即触发 ──────────────────────────────────────

def test_downstream_or_semantics_copper_only():
    """conn-copper 单独 > 75 即可触发 downstream（OR 语义）。"""
    scores = {
        "semi-equip": 85.0,
        "semi-compute": 80.0,
        "semi-mem": 78.0,
        "semi-conn": 76.0,
        "conn-optical": 50.0,  # 未触发
        "conn-copper": 80.0,   # 触发
    }
    result = compute_chain_signals(scores, _RULES)
    assert result.downstream is True
