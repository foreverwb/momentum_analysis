"""产业链下钻策略面板计算器（Phase 4 — Task DD-4）。

职责：基于节点分数 / delta5d / 父子关系，输出右侧 StrategicPanel 4 张卡片所需数据：
  Q1 l1_ranking   — L1 节点按 score 降序
  Q2 breadth      — top L1 内部强弱（>75 子节点计数 → 全面/主线/单点）
  Q3 confirmation — 上游设备 / 高速互联 / 算力 三者得分 + 算力领涨判定 + 提示语
  Q4 best_drill   — L2 集合中 delta5d 最大者

禁止：
- 在本模块硬编码节点 ID（全部从 <sector>.yaml 的 strategy 段读取）
- 直接抛 HTTPException（计算层只抛 ValueError / KeyError）
- 修改 chain_signals / node_score / node_basket 任何函数
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

# ─── 配置文件根目录（与 chain_signals 同源，复用 sector YAML 里的 strategy 段） ─
_CONFIGS_DIR = os.path.join(
    os.path.dirname(__file__),  # calculators/
    "..",                        # services/
    "..",                        # app/
    "configs",
    "chain_signals",
)

# ─── 广度阈值与文案 — 来源 HTML L770-772（drilldown-upgrade.html） ────────────
_BREADTH_STRONG_THRESHOLD = 75.0
_BREADTH_FULL_MIN = 3   # ≥3 个子节点 >75 → 全面扩散
_BREADTH_MAIN_MIN = 2   # ==2 → 主线驱动；其它 → 单点拉动
_BREADTH_LABEL_FULL = "全面扩散"
_BREADTH_LABEL_MAIN = "主线驱动"
_BREADTH_LABEL_SINGLE = "单点拉动"

# ─── Q3 提示语 — 来源 HTML L870-872 ─────────────────────────────────────────
_MSG_COMPUTE_LEADING = "⚡ 算力领涨，设备/连接尚在跟进中，属主线扩散中段"
_MSG_BROAD_CONFIRMED = "✔️ 上下游联动信号已出现，全链景气提升中"


# ─── 数据类 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyNodeBrief:
    """策略面板中一个节点的最小展示信息。"""
    id: str
    label: str
    sublabel: str
    score: float
    delta5d: Optional[float]


@dataclass(frozen=True)
class BreadthResult:
    label: str          # 全面扩散 / 主线驱动 / 单点拉动
    strong_count: int   # top L1 子节点中 score>75 的数量
    total: int          # top L1 子节点总数


@dataclass(frozen=True)
class ConfirmationResult:
    equip_score: float
    conn_score: float
    compute_score: float
    compute_leading: bool   # compute > equip AND compute > conn
    message: str            # 取决于 compute_leading


@dataclass(frozen=True)
class ChainStrategyResult:
    l1_ranking: List[StrategyNodeBrief]
    breadth: BreadthResult
    confirmation: ConfirmationResult
    best_drill: Optional[StrategyNodeBrief]


@dataclass(frozen=True)
class StrategyConfig:
    """从 <sector>.yaml 的 strategy 段加载。

    - l1_nodes:        L1 排名节点列表，如 ['semi','soft','hw']
    - equip_node / conn_node / compute_node: Q3 三个引用节点 ID
    - l2_drill_nodes:  Q4 best_drill 候选节点 ID 列表
    """
    l1_nodes: List[str]
    equip_node: str
    conn_node: str
    compute_node: str
    l2_drill_nodes: List[str]


# ─── YAML 加载 ────────────────────────────────────────────────────────────


def load_chain_strategy_config(sector: str) -> StrategyConfig:
    """加载 configs/chain_signals/<sector>.yaml 的 strategy 段。

    Args:
        sector: 板块标识（大小写不敏感）。

    Returns:
        StrategyConfig。

    Raises:
        FileNotFoundError: 配置文件不存在。
        KeyError: YAML 缺 strategy 段或必需子键。
    """
    cfg_path = os.path.join(_CONFIGS_DIR, f"{sector.lower()}.yaml")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(
            f"Chain strategy config not found: {cfg_path}. "
            f"Add a `strategy:` section to {sector.lower()}.yaml"
        )

    with open(cfg_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if "strategy" not in raw:
        raise KeyError(
            f"Section 'strategy' missing in {cfg_path}. "
            f"Required keys: l1_nodes, equip_node, conn_node, compute_node, l2_drill_nodes"
        )

    s = raw["strategy"]
    return StrategyConfig(
        l1_nodes=[str(n) for n in s["l1_nodes"]],
        equip_node=str(s["equip_node"]),
        conn_node=str(s["conn_node"]),
        compute_node=str(s["compute_node"]),
        l2_drill_nodes=[str(n) for n in s["l2_drill_nodes"]],
    )


# ─── 子计算 ────────────────────────────────────────────────────────────────


def _rank_l1(
    nodes: Dict[str, StrategyNodeBrief],
    l1_ids: List[str],
) -> List[StrategyNodeBrief]:
    """L1 节点按 score 降序；缺数据节点跳过（不抛异常）。"""
    briefs = [nodes[nid] for nid in l1_ids if nid in nodes]
    return sorted(briefs, key=lambda b: b.score, reverse=True)


def _breadth_label(strong_count: int) -> str:
    if strong_count >= _BREADTH_FULL_MIN:
        return _BREADTH_LABEL_FULL
    if strong_count == _BREADTH_MAIN_MIN:
        return _BREADTH_LABEL_MAIN
    return _BREADTH_LABEL_SINGLE


def _calc_breadth(
    top_l1: Optional[StrategyNodeBrief],
    children_map: Dict[str, List[str]],
    nodes: Dict[str, StrategyNodeBrief],
) -> BreadthResult:
    """统计 top L1 子节点中 score > 75 的数量并映射文案。"""
    if top_l1 is None:
        return BreadthResult(label=_BREADTH_LABEL_SINGLE, strong_count=0, total=0)
    child_ids = children_map.get(top_l1.id, [])
    children = [nodes[cid] for cid in child_ids if cid in nodes]
    strong = sum(1 for c in children if c.score > _BREADTH_STRONG_THRESHOLD)
    return BreadthResult(
        label=_breadth_label(strong),
        strong_count=strong,
        total=len(children),
    )


def _calc_confirmation(
    nodes: Dict[str, StrategyNodeBrief],
    config: StrategyConfig,
) -> ConfirmationResult:
    """三节点取分；缺失视为 0；compute 双向严格大于 equip 与 conn 时领涨。"""
    equip = nodes[config.equip_node].score if config.equip_node in nodes else 0.0
    conn = nodes[config.conn_node].score if config.conn_node in nodes else 0.0
    compute = nodes[config.compute_node].score if config.compute_node in nodes else 0.0
    leading = compute > equip and compute > conn
    return ConfirmationResult(
        equip_score=equip,
        conn_score=conn,
        compute_score=compute,
        compute_leading=leading,
        message=_MSG_COMPUTE_LEADING if leading else _MSG_BROAD_CONFIRMED,
    )


def _pick_best_drill(
    nodes: Dict[str, StrategyNodeBrief],
    l2_ids: List[str],
) -> Optional[StrategyNodeBrief]:
    """L2 集合中 delta5d 最大者；全部缺失（None）→ 返回 None。"""
    candidates = [nodes[nid] for nid in l2_ids if nid in nodes and nodes[nid].delta5d is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.delta5d)  # type: ignore[arg-type,return-value]


# ─── 顶层入口 ──────────────────────────────────────────────────────────────


def compute_chain_strategy(
    nodes: Dict[str, StrategyNodeBrief],
    children_map: Dict[str, List[str]],
    config: StrategyConfig,
) -> ChainStrategyResult:
    """根据节点分数 / 父子关系 / 配置，产出策略面板四块数据。

    Args:
        nodes: {node_id: StrategyNodeBrief}。配置中引用的节点缺失时按 score=0 / delta5d=None 处理。
        children_map: {parent_id: [child_id, ...]}，用于 Q2 广度统计。
        config: 通过 load_chain_strategy_config 加载。

    Returns:
        ChainStrategyResult。

    Raises:
        无。缺数据节点统一降级处理，不阻断面板渲染。
    """
    l1_ranking = _rank_l1(nodes, config.l1_nodes)
    top_l1 = l1_ranking[0] if l1_ranking else None
    breadth = _calc_breadth(top_l1, children_map, nodes)
    confirmation = _calc_confirmation(nodes, config)
    best_drill = _pick_best_drill(nodes, config.l2_drill_nodes)
    return ChainStrategyResult(
        l1_ranking=l1_ranking,
        breadth=breadth,
        confirmation=confirmation,
        best_drill=best_drill,
    )
