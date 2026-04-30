"""产业链共振信号计算器（Phase 4 — Task DD-8）。

职责：根据配置文件中的规则，对节点分数映射做三维信号评估：
  upstream（上游共振）/ broad（同层扩散）/ downstream（下游确认）。
  综合 label / color 由触发信号数量（0-3）决定。

禁止：
- 在本模块硬编码节点 ID 或阈值（全部从 YAML 配置读取）
- 直接抛 HTTPException（计算层只抛 ValueError / KeyError）
- 修改 node_score / etf_score / node_basket 任何函数
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

import yaml

# ─── 配置文件根目录 ───────────────────────────────────────────────────────────
# 路径相对于本文件往上 3 级，指向 backend/app/configs/chain_signals/
_CONFIGS_DIR = os.path.join(
    os.path.dirname(__file__),  # calculators/
    "..",                        # services/
    "..",                        # app/
    "configs",
    "chain_signals",
)

# ─── 信号数量 → 综合标签 / 颜色（需求文档 §business-rules） ─────────────────
# 来源: HTML L933-934，顺序严格对应 n=0,1,2,3
_SIGNAL_LABELS = ["链条断裂", "单点拉动", "主线扩散", "全链共振"]
_SIGNAL_COLORS = ["#dc2626", "#d97706", "#2563eb", "#059669"]


# ─── 数据类 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UpstreamRule:
    watched_nodes: List[str]
    threshold: float


@dataclass(frozen=True)
class BroadRule:
    watched_nodes: List[str]
    threshold: float
    min_count: int


@dataclass(frozen=True)
class DownstreamRule:
    watched_nodes: List[str]
    threshold: float


@dataclass(frozen=True)
class ChainSignalRules:
    upstream: UpstreamRule
    broad: BroadRule
    downstream: DownstreamRule


@dataclass(frozen=True)
class ChainSignalResult:
    upstream: bool          # 上游共振
    broad: bool             # 同层扩散
    downstream: bool        # 下游确认
    label: str              # 综合标签，如「全链共振」
    color: str              # 综合配色 hex，如 '#059669'


# ─── YAML 加载 ────────────────────────────────────────────────────────────────


def load_chain_signal_rules(sector: str) -> ChainSignalRules:
    """从 configs/chain_signals/<sector>.yaml 加载规则。

    Args:
        sector: 板块标识，小写，如 'xlk'。大小写不敏感，内部转为小写。

    Returns:
        ChainSignalRules 对象。

    Raises:
        FileNotFoundError: 配置文件不存在。
        KeyError: YAML 缺少必要字段。
        ValueError: 字段类型非法（如 threshold 非数字）。
    """
    cfg_path = os.path.join(_CONFIGS_DIR, f"{sector.lower()}.yaml")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(
            f"Chain signal config not found: {cfg_path}. "
            f"Create backend/app/configs/chain_signals/{sector.lower()}.yaml"
        )

    with open(cfg_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return _parse_rules(raw)


def _parse_rules(raw: dict) -> ChainSignalRules:
    up_raw = raw["upstream"]
    br_raw = raw["broad"]
    dn_raw = raw["downstream"]

    upstream = UpstreamRule(
        watched_nodes=[str(n) for n in up_raw["watched_nodes"]],
        threshold=float(up_raw["threshold"]),
    )
    broad = BroadRule(
        watched_nodes=[str(n) for n in br_raw["watched_nodes"]],
        threshold=float(br_raw["threshold"]),
        min_count=int(br_raw["min_count"]),
    )
    downstream = DownstreamRule(
        watched_nodes=[str(n) for n in dn_raw["watched_nodes"]],
        threshold=float(dn_raw["threshold"]),
    )
    return ChainSignalRules(upstream=upstream, broad=broad, downstream=downstream)


# ─── 核心计算 ─────────────────────────────────────────────────────────────────


def compute_chain_signals(
    node_scores: Dict[str, float],
    rules: ChainSignalRules,
) -> ChainSignalResult:
    """对节点分数映射评估三维链条共振信号。

    Args:
        node_scores: {node_id: score}，分数范围 0-100。
                     键缺失时视为 0（节点无数据不阻断评估）。
        rules: 从配置文件加载的 ChainSignalRules。

    Returns:
        ChainSignalResult，含三个布尔信号 + 综合 label/color。

    Raises:
        无。缺失节点 score 视为 0，不抛异常。
    """

    def s(node_id: str) -> float:
        return node_scores.get(node_id, 0.0)

    # 上游共振：所有 watched_nodes 均需满足阈值（AND 语义）
    upstream_ok = all(
        s(nid) > rules.upstream.threshold
        for nid in rules.upstream.watched_nodes
    ) if rules.upstream.watched_nodes else False

    # 同层扩散：watched_nodes 中超阈值的数量 >= min_count（COUNT 语义）
    broad_count = sum(
        1 for nid in rules.broad.watched_nodes if s(nid) > rules.broad.threshold
    )
    broad_ok = broad_count >= rules.broad.min_count

    # 下游确认：任一 watched_node 满足阈值即可（OR 语义）
    downstream_ok = any(
        s(nid) > rules.downstream.threshold
        for nid in rules.downstream.watched_nodes
    ) if rules.downstream.watched_nodes else False

    n = sum([upstream_ok, broad_ok, downstream_ok])
    return ChainSignalResult(
        upstream=upstream_ok,
        broad=broad_ok,
        downstream=downstream_ok,
        label=_SIGNAL_LABELS[n],
        color=_SIGNAL_COLORS[n],
    )


# ─── 便捷入口：按板块名加载规则后直接计算 ─────────────────────────────────────


def compute_chain_signals_for_sector(
    node_scores: Dict[str, float],
    sector: str,
) -> ChainSignalResult:
    """加载 <sector>.yaml 并计算链条信号（一步到位）。

    Args:
        node_scores: {node_id: score}
        sector: 板块标识，如 'xlk'。

    Returns:
        ChainSignalResult。

    Raises:
        FileNotFoundError: 配置不存在时透传。
    """
    rules = load_chain_signal_rules(sector)
    return compute_chain_signals(node_scores, rules)
