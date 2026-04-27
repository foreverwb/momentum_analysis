"""节点综合评分计算器（Phase 4 — Drilldown Upgrade Task 4.4）。

职责: 在保留 ETFScoreCalculator 主权重 (rel_mom 0.45 / trend 0.25 / breadth 0.20 /
options 0.10) 的基础上, 对节点 (AnalyticNode) 增加两个 overlay：
  1) representation_confidence — 节点被 proxy / synthetic 表达得有多纯
  2) chain_confirmation        — 上下游是否共振 (drives / depends_on / corroborates)

禁止:
- 修改 etf_score.py / momentum_pool.py / stock_score.py 任何函数 (CLAUDE.md §扩展性)
- 在计算层抛 HTTPException (CLAUDE.md §可维护性)
- 重写 momentum / etf_score / node_basket 已有逻辑 (强制复用)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_t
from datetime import timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.database import (
    AnalyticNode,
    ETFHolding,
    IVData,
    NodeEdge,
    NodeEdgeType,
    NodePriceSeries,
    NodeProxy,
    NodeProxyRole,
    PriceHistory,
    ScoreSnapshot,
    SyntheticBasketDefinition,
)

from .etf_score import rank_percentile_normalize
from .momentum import MomentumCalculator
from .node_basket import (
    compute_basket_price_series,
    get_node_holdings,
    get_node_proxy_etf,
    is_synthetic_node,
)
from .technical import calculate_max_drawdown, calculate_sma, calculate_sma_slope_pct

logger = logging.getLogger(__name__)


# ============ 常量 (来源标注于行尾) ============

# 主权重 — 需求文档 §6 明确, 与 ETFScoreCalculator.WEIGHTS 一致
NODE_BASE_WEIGHTS: Dict[str, float] = {
    "rel_mom": 0.45,
    "trend": 0.25,
    "breadth": 0.20,
    "options": 0.10,
}

# total_score 公式中的 chain_confirmation overlay 系数
# 公式: total = base × rep_conf × (FLOOR + GAIN × chain_confirmation)
# 来源: Phase4_Drilldown_Upgrade.md Task 4.4 §3
_CHAIN_FLOOR = 0.7
_CHAIN_GAIN = 0.3

# 计算分数所需的最少价格序列长度 (低于此值标 "数据不足")
_MIN_PRICE_DAYS = 30
# 趋势分数所需 SMA50, 低于此值 trend_raw=None
_TREND_MIN_DAYS = 50

# 横截面标准化所需的最少节点数; 低于此值直接用 raw->100 映射
_CROSS_SECTION_MIN = 3

# rel_mom 单值映射: 与 ETFScoreCalculator._map_rel_mom_absolute 同口径
_REL_MOM_OFFSET = 0.1
_REL_MOM_DENOM = 0.25

# breadth 计算 SMA 窗口
_BREADTH_SMA_WINDOW = 50

# chain_confirmation 中 "节点已合格" 的阈值 — 需求文档 §6
_CHAIN_QUALIFIED_THRESHOLD = 60.0
# corroborates 入边的权重折算系数 — Task 4.4 §1
_CORROBORATES_WEIGHT_FACTOR = 0.5

# recommended_drill 阈值 — 子节点需高于父节点 5 分以上才推荐
_DRILL_DELTA_THRESHOLD = 5.0

# delta3d / delta5d 回看窗口 (自然日)
_DELTA_LOOKBACK_3D = 3
_DELTA_LOOKBACK_5D = 5

# ScoreSnapshot 的 symbol_type 取值
_SNAPSHOT_SYMBOL_TYPE = "node"


# ============ 数据结构 ============


@dataclass
class NodeScoreResult:
    node_id: str
    label: str
    level: int
    proxy_type: str
    proxy_symbol: Optional[str]
    proxy_label: Optional[str]
    total_score: float
    base_score: float
    representation_confidence: float
    chain_confirmation: float
    score_vs_parent: Optional[float]
    contribution: Optional[float]
    rel_strength: Optional[float]
    breadth: Optional[float]
    delta3d: Optional[float]
    delta5d: Optional[float]
    raw_subscores: Dict[str, Optional[float]]
    norm_subscores: Dict[str, Optional[float]]
    notes: List[str] = field(default_factory=list)
    recommended_drill: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============ 主接口 ============


def batch_calculate_node_scores(
    node_ids: List[str],
    db: Session,
    *,
    benchmark_symbol: str = "SPY",
    label_tz: str = "beijing",  # 保留参数, 与 etf_score 统一签名
) -> List[NodeScoreResult]:
    """批量计算节点评分 (同批节点做横截面标准化, 详见 Task 4.4 §1)。

    Args:
        node_ids: 节点业务主键列表。
        db: SQLAlchemy session。
        benchmark_symbol: 计算 RS 时的基准, 默认 SPY。
        label_tz: 时区参数, 当前未使用 (与 etf_score 统一签名)。

    Returns:
        按 total_score 降序排序的 NodeScoreResult 列表;
        无效 / 不存在的 node_id 会被跳过 (写日志, 不抛异常)。

    Raises:
        ValueError: node_ids 非列表或包含非字符串。
    """
    if not isinstance(node_ids, list):
        raise ValueError("node_ids must be a list")
    if any(not isinstance(n, str) or not n for n in node_ids):
        raise ValueError("node_ids must contain non-empty strings")

    unique_ids = list(dict.fromkeys(node_ids))
    if not unique_ids:
        return []

    # 节点元数据 (label / level / representation_confidence)
    meta_map = _load_node_meta(db, unique_ids)

    # 每节点的价格 DataFrame + proxy 信息
    benchmark_df = _load_price_df_for_symbol(db, benchmark_symbol)
    feature_map: Dict[str, _NodeFeatures] = {}
    for nid in unique_ids:
        meta = meta_map.get(nid)
        if meta is None:
            logger.warning("node %s not found in AnalyticNode, skipped", nid)
            continue
        feature_map[nid] = _build_node_features(
            nid, meta, db, benchmark_df=benchmark_df
        )

    if not feature_map:
        return []

    # 横截面标准化或 raw->100 直接映射
    normalized_map = _normalize_subscores(feature_map)

    # base_score (权重重分配处理 None)
    base_score_map: Dict[str, float] = {}
    weight_alloc_map: Dict[str, Dict[str, float]] = {}
    for nid, features in feature_map.items():
        base_score, weights = _compose_base_score(normalized_map[nid])
        base_score_map[nid] = base_score
        weight_alloc_map[nid] = weights

    # chain_confirmation 用 base_score 判定 "已合格", 避免与 total 形成循环
    chain_conf_map = {
        nid: compute_chain_confirmation(nid, base_score_map, db)
        for nid in feature_map
    }

    # total_score = base × rep_conf × (FLOOR + GAIN × chain_conf)
    total_score_map: Dict[str, float] = {}
    for nid, features in feature_map.items():
        rep_conf = features.representation_confidence
        chain_conf = chain_conf_map[nid]
        base = base_score_map[nid]
        total = base * rep_conf * (_CHAIN_FLOOR + _CHAIN_GAIN * chain_conf)
        total_score_map[nid] = round(_clip01_100(total), 2)

    # 父子关系 (用于 score_vs_parent / contribution / recommended_drill)
    parent_map = _load_parent_map(db, list(feature_map.keys()))
    children_map = _invert_parent_map(parent_map, batch_keys=set(feature_map.keys()))
    contribution_map = _compute_contributions(
        feature_map=feature_map,
        total_score_map=total_score_map,
        parent_map=parent_map,
        db=db,
    )

    # delta3d / delta5d 从 ScoreSnapshot 历史读
    snapshot_date = _resolve_snapshot_date(feature_map)
    delta_map = _load_score_deltas(db, list(feature_map.keys()), snapshot_date)

    # 组装结果
    results: List[NodeScoreResult] = []
    for nid, features in feature_map.items():
        meta = meta_map[nid]
        norm = normalized_map[nid]
        deltas = delta_map.get(nid, (None, None))
        recommended = _pick_recommended_drill(
            node_id=nid,
            children=children_map.get(nid, []),
            total_score_map=total_score_map,
        )
        parent_id = parent_map.get(nid)
        parent_total = total_score_map.get(parent_id) if parent_id else None
        score_vs_parent = (
            round(total_score_map[nid] - parent_total, 2)
            if parent_total is not None
            else None
        )
        results.append(
            NodeScoreResult(
                node_id=nid,
                label=meta.label,
                level=int(meta.level or 0),
                proxy_type=features.proxy_type,
                proxy_symbol=features.proxy_symbol,
                proxy_label=features.proxy_label,
                total_score=total_score_map[nid],
                base_score=round(base_score_map[nid], 2),
                representation_confidence=round(features.representation_confidence, 4),
                chain_confirmation=round(chain_conf_map[nid], 4),
                score_vs_parent=score_vs_parent,
                contribution=contribution_map.get(nid),
                rel_strength=features.rel_strength,
                breadth=features.breadth_pct,
                delta3d=deltas[0],
                delta5d=deltas[1],
                raw_subscores=features.raw_subscores,
                norm_subscores=norm,
                notes=list(features.notes),
                recommended_drill=recommended,
            )
        )

    # 写当日 ScoreSnapshot, 供下次调用计算 delta 使用
    _persist_score_snapshots(db, results, snapshot_date)

    results.sort(key=lambda r: r.total_score, reverse=True)
    return results


def calculate_node_score(
    node_id: str,
    db: Session,
    *,
    benchmark_symbol: str = "SPY",
) -> Optional[NodeScoreResult]:
    """单节点评分 (内部委托给 batch_calculate_node_scores)。"""
    results = batch_calculate_node_scores(
        [node_id], db, benchmark_symbol=benchmark_symbol
    )
    return results[0] if results else None


def compute_chain_confirmation(
    node_id: str,
    other_node_scores: Dict[str, float],
    db: Session,
) -> float:
    """基于 NodeEdge 的 drives / depends_on / corroborates 计算上下游共振度。

    Args:
        node_id: 当前节点。
        other_node_scores: {node_id: score}; 用于判定"对端节点已合格"。
        db: SQLAlchemy session。

    Returns:
        0.0 ~ 1.0 — 0=完全无共振, 1=所有相关边对端都已合格。
        无任何边时返回 1.0 (中性: 不引入下行修正)。

    Raises:
        ValueError: node_id 非空字符串。
    """
    if not node_id or not isinstance(node_id, str):
        raise ValueError("node_id must be a non-empty string")

    out_edges = (
        db.query(NodeEdge)
        .filter(NodeEdge.src_node_id == node_id)
        .filter(
            NodeEdge.edge_type.in_(
                [NodeEdgeType.DRIVES.value, NodeEdgeType.DEPENDS_ON.value]
            )
        )
        .all()
    )
    in_corroborates = (
        db.query(NodeEdge)
        .filter(NodeEdge.dst_node_id == node_id)
        .filter(NodeEdge.edge_type == NodeEdgeType.CORROBORATES.value)
        .all()
    )

    matched = 0.0
    total = 0.0
    for edge in out_edges:
        weight = float(edge.weight or 1.0)
        total += weight
        peer_score = other_node_scores.get(edge.dst_node_id)
        if peer_score is not None and peer_score >= _CHAIN_QUALIFIED_THRESHOLD:
            matched += weight
    for edge in in_corroborates:
        weight = float(edge.weight or 1.0) * _CORROBORATES_WEIGHT_FACTOR
        total += weight
        peer_score = other_node_scores.get(edge.src_node_id)
        if peer_score is not None and peer_score >= _CHAIN_QUALIFIED_THRESHOLD:
            matched += weight

    if total <= 0:
        # 没有任何上下游边 → 中性 (不强制下行修正)
        return 1.0
    return round(min(1.0, max(0.0, matched / total)), 4)


# ============ 内部数据结构 ============


@dataclass
class _NodeFeatures:
    proxy_type: str  # 'etf' | 'synthetic'
    proxy_symbol: Optional[str]
    proxy_label: Optional[str]
    price_df: Optional[pd.DataFrame]
    representation_confidence: float
    raw_subscores: Dict[str, Optional[float]]
    rel_strength: Optional[float]
    breadth_pct: Optional[float]
    notes: List[str] = field(default_factory=list)


# ============ 节点元数据 / 价格序列 ============


def _load_node_meta(db: Session, node_ids: List[str]) -> Dict[str, AnalyticNode]:
    rows = (
        db.query(AnalyticNode)
        .filter(AnalyticNode.node_id.in_(node_ids))
        .all()
    )
    return {r.node_id: r for r in rows}


def _load_price_df_for_symbol(db: Session, symbol: str) -> Optional[pd.DataFrame]:
    rows = (
        db.query(PriceHistory.date, PriceHistory.close)
        .filter(PriceHistory.symbol == symbol)
        .order_by(PriceHistory.date.asc())
        .all()
    )
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _load_price_df_for_node(node_id: str, db: Session) -> Optional[pd.DataFrame]:
    rows = (
        db.query(NodePriceSeries.date, NodePriceSeries.close)
        .filter(NodePriceSeries.node_id == node_id)
        .order_by(NodePriceSeries.date.asc())
        .all()
    )
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _resolve_proxy_info(
    node_id: str, db: Session
) -> Tuple[str, Optional[str], Optional[str]]:
    """返回 (proxy_type, proxy_symbol, proxy_label)."""
    proxy_etf = get_node_proxy_etf(node_id, db)
    if proxy_etf:
        return "etf", proxy_etf, proxy_etf
    if is_synthetic_node(node_id, db):
        holdings = get_node_holdings(node_id, db)
        tickers = [h["ticker"] for h in holdings[:3]]
        label = " + ".join(tickers) if tickers else None
        return "synthetic", None, label
    return "unknown", None, None


# ============ 子分数计算 ============


def _build_node_features(
    node_id: str,
    meta: AnalyticNode,
    db: Session,
    *,
    benchmark_df: Optional[pd.DataFrame],
) -> _NodeFeatures:
    proxy_type, proxy_symbol, proxy_label = _resolve_proxy_info(node_id, db)
    notes: List[str] = []

    price_df = _resolve_node_price_df(
        node_id=node_id, proxy_type=proxy_type, proxy_symbol=proxy_symbol, db=db
    )

    raw_subscores: Dict[str, Optional[float]] = {
        "rel_mom": None,
        "trend": None,
        "breadth": None,
        "options": None,
    }
    rel_strength: Optional[float] = None
    breadth_pct: Optional[float] = None

    if price_df is None or len(price_df) < _MIN_PRICE_DAYS:
        notes.append("数据不足")
    else:
        rel_mom_raw, rs20 = _compute_rel_mom_raw(price_df, benchmark_df)
        raw_subscores["rel_mom"] = rel_mom_raw
        rel_strength = rs20

        trend_raw = _compute_trend_raw(price_df)
        raw_subscores["trend"] = trend_raw

        breadth_raw, breadth_pct_local = _compute_breadth_raw(node_id, db)
        raw_subscores["breadth"] = breadth_raw
        breadth_pct = breadth_pct_local

        options_raw = _compute_options_raw(node_id, db)
        raw_subscores["options"] = options_raw

    rep_conf = float(meta.representation_confidence or 1.0)

    return _NodeFeatures(
        proxy_type=proxy_type,
        proxy_symbol=proxy_symbol,
        proxy_label=proxy_label,
        price_df=price_df,
        representation_confidence=rep_conf,
        raw_subscores=raw_subscores,
        rel_strength=rel_strength,
        breadth_pct=breadth_pct,
        notes=notes,
    )


def _resolve_node_price_df(
    *,
    node_id: str,
    proxy_type: str,
    proxy_symbol: Optional[str],
    db: Session,
) -> Optional[pd.DataFrame]:
    if proxy_type == "etf" and proxy_symbol:
        return _load_price_df_for_symbol(db, proxy_symbol)
    if proxy_type == "synthetic":
        # 懒加载缓存: 已存在则跳过, 不存在则合成
        existing = (
            db.query(NodePriceSeries.id)
            .filter(NodePriceSeries.node_id == node_id)
            .first()
        )
        if existing is None:
            try:
                compute_basket_price_series(node_id, db)
            except Exception as exc:
                logger.warning("compute_basket_price_series(%s) failed: %s", node_id, exc)
        return _load_price_df_for_node(node_id, db)
    return None


def _compute_rel_mom_raw(
    node_price_df: pd.DataFrame,
    benchmark_df: Optional[pd.DataFrame],
) -> Tuple[Optional[float], Optional[float]]:
    """返回 (RelMom, RS_20D_change) — 复用 MomentumCalculator。"""
    if benchmark_df is None or benchmark_df.empty:
        return None, None
    rs_df = MomentumCalculator.calculate_relative_strength(
        node_price_df, benchmark_df
    )
    if rs_df is None or rs_df.empty:
        return None, None
    relmom_df = MomentumCalculator.calculate_rel_mom(rs_df)
    if relmom_df is None or relmom_df.empty:
        return None, None
    last = relmom_df.iloc[-1]
    rel_mom = _to_float_safe(last.get("RelMom"))
    rs_20d = _to_float_safe(last.get("RS_20D_change"))
    return rel_mom, rs_20d


def _compute_trend_raw(price_df: pd.DataFrame) -> Optional[float]:
    """复制 ETFScoreCalculator.calculate_trend_quality_score 的 4×25 评分逻辑。

    复用 technical 库 (calculate_sma / calculate_sma_slope_pct / calculate_max_drawdown)。
    """
    prices = pd.to_numeric(price_df["close"], errors="coerce").dropna()
    if len(prices) < _TREND_MIN_DAYS:
        return None
    sma20 = calculate_sma(prices, 20)
    sma50 = calculate_sma(prices, 50)
    cur = float(prices.iloc[-1])
    s20 = float(sma20.iloc[-1])
    s50 = float(sma50.iloc[-1])
    slope = float(calculate_sma_slope_pct(sma20, period=5))
    max_dd = float(calculate_max_drawdown(prices, 20))

    score = 0.0
    if cur > s50:
        score += 25.0
    if s20 > s50:
        score += 25.0
    if slope > 0:
        score += 25.0
    if max_dd > -0.10:
        score += 25.0
    return round(_clip01_100(score), 2)


def _compute_breadth_raw(
    node_id: str, db: Session
) -> Tuple[Optional[float], Optional[float]]:
    """%above_50ma 作为节点广度 raw 值; 同时返回 0..1 的 breadth_pct 用于展示。

    对 ETF proxy / synthetic 节点统一通过 get_node_holdings 取成分清单, 然后
    各成分独立从 PriceHistory 读最近 50 天计算 SMA50 是否被当前价上穿。
    """
    holdings = get_node_holdings(node_id, db)
    if not holdings:
        return None, None

    above_count = 0
    valid_count = 0
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker:
            continue
        prices = _load_recent_prices(db, ticker, days=120)
        if prices is None or len(prices) < _BREADTH_SMA_WINDOW:
            continue
        sma50 = calculate_sma(prices, _BREADTH_SMA_WINDOW)
        if pd.isna(sma50.iloc[-1]):
            continue
        valid_count += 1
        if float(prices.iloc[-1]) > float(sma50.iloc[-1]):
            above_count += 1

    if valid_count == 0:
        return None, None
    breadth_pct = above_count / valid_count
    return round(breadth_pct * 100.0, 2), round(breadth_pct, 4)


def _compute_options_raw(node_id: str, db: Session) -> Optional[float]:
    """节点 options raw 分: 用 basket / proxy 成分的 IV term-score 加权。

    简化口径 (期权数据缺失时直接 None, 不污染 base_score):
      - 拿成分股最近一条 IVData
      - term_score = 50 + (iv30 - iv90) * 100  → clip 0..100
      - 节点 options_raw = Σ weight_i × term_score_i / Σ weight_i

    完整口径 (mc + futu) 留待 API 层组装, 计算层只做基础版本。
    """
    holdings = get_node_holdings(node_id, db)
    if not holdings:
        return None

    weight_sum = 0.0
    weighted_term = 0.0
    for holding in holdings:
        ticker = holding.get("ticker")
        weight = float(holding.get("weight") or 0.0)
        if not ticker or weight <= 0:
            continue
        iv_row = (
            db.query(IVData)
            .filter(IVData.symbol == ticker)
            .order_by(IVData.date.desc())
            .first()
        )
        if iv_row is None:
            continue
        iv30 = _to_float_safe(iv_row.iv30)
        iv90 = _to_float_safe(iv_row.iv90)
        if iv30 is None or iv90 is None:
            continue
        term_score = _clip01_100(50.0 + (iv30 - iv90) * 100.0)
        weighted_term += term_score * weight
        weight_sum += weight

    if weight_sum <= 0:
        return None
    return round(weighted_term / weight_sum, 2)


def _load_recent_prices(
    db: Session, ticker: str, days: int
) -> Optional[pd.Series]:
    rows = (
        db.query(PriceHistory.date, PriceHistory.close)
        .filter(PriceHistory.symbol == ticker)
        .order_by(PriceHistory.date.desc())
        .limit(days)
        .all()
    )
    if not rows:
        return None
    rows = list(reversed(rows))
    series = pd.Series(
        [float(r[1]) for r in rows if r[1] is not None],
        index=[r[0] for r in rows if r[1] is not None],
    )
    return series if not series.empty else None


# ============ 标准化与 base_score ============


def _normalize_subscores(
    feature_map: Dict[str, _NodeFeatures]
) -> Dict[str, Dict[str, Optional[float]]]:
    """对 4 个维度做横截面 rank percentile 标准化; n<3 时直接 raw->0..100 映射。"""
    nids = list(feature_map.keys())
    use_cross_section = len(nids) >= _CROSS_SECTION_MIN

    norm_map: Dict[str, Dict[str, Optional[float]]] = {nid: {} for nid in nids}

    for dim in NODE_BASE_WEIGHTS.keys():
        raw_map = {
            nid: feature_map[nid].raw_subscores.get(dim) for nid in nids
        }
        if use_cross_section:
            normed = rank_percentile_normalize(raw_map)
        else:
            normed = {
                nid: _raw_to_score(dim, raw_map[nid]) for nid in nids
            }
        for nid in nids:
            norm_map[nid][dim] = normed.get(nid)
    return norm_map


def _raw_to_score(dim: str, raw: Optional[float]) -> Optional[float]:
    """单样本 fallback: 把 raw 映射到 0..100。"""
    if raw is None:
        return None
    if dim == "rel_mom":
        # 与 ETFScoreCalculator._map_rel_mom_absolute 同口径
        return round(_clip01_100((raw + _REL_MOM_OFFSET) / _REL_MOM_DENOM * 100.0), 2)
    # trend / breadth / options 已经是 0..100
    return round(_clip01_100(float(raw)), 2)


def _compose_base_score(
    norm_subscores: Dict[str, Optional[float]]
) -> Tuple[float, Dict[str, float]]:
    """权重重分配: NO_DATA 维度的权重按比例分给其他维度 (与 etf_score 同口径)。"""
    available = {k: v for k, v in norm_subscores.items() if v is not None}
    if not available:
        return 0.0, {}
    total_w = sum(NODE_BASE_WEIGHTS[k] for k in available)
    if total_w <= 0:
        return 0.0, {}
    redistributed = {k: NODE_BASE_WEIGHTS[k] / total_w for k in available}
    base = sum(available[k] * redistributed[k] for k in available)
    return round(_clip01_100(base), 2), {
        k: round(v, 6) for k, v in redistributed.items()
    }


# ============ 父子关系 / contribution / recommended_drill ============


def _load_parent_map(db: Session, node_ids: List[str]) -> Dict[str, str]:
    """node_id -> parent_node_id, 取 classification_parent / chain_parent (优先前者)."""
    rows = (
        db.query(NodeEdge.src_node_id, NodeEdge.dst_node_id, NodeEdge.edge_type)
        .filter(NodeEdge.dst_node_id.in_(node_ids))
        .filter(
            NodeEdge.edge_type.in_(
                [
                    NodeEdgeType.CLASSIFICATION_PARENT.value,
                    NodeEdgeType.CHAIN_PARENT.value,
                ]
            )
        )
        .all()
    )
    parent_map: Dict[str, str] = {}
    chain_map: Dict[str, str] = {}
    for src, dst, etype in rows:
        if etype == NodeEdgeType.CLASSIFICATION_PARENT.value:
            parent_map[dst] = src
        elif etype == NodeEdgeType.CHAIN_PARENT.value:
            chain_map.setdefault(dst, src)
    # classification 优先, 缺失才退化到 chain
    for nid, parent in chain_map.items():
        parent_map.setdefault(nid, parent)
    return parent_map


def _invert_parent_map(
    parent_map: Dict[str, str], batch_keys: set
) -> Dict[str, List[str]]:
    children: Dict[str, List[str]] = {}
    for child, parent in parent_map.items():
        if parent not in batch_keys or child not in batch_keys:
            continue
        children.setdefault(parent, []).append(child)
    return children


def _compute_contributions(
    *,
    feature_map: Dict[str, _NodeFeatures],
    total_score_map: Dict[str, float],
    parent_map: Dict[str, str],
    db: Session,
) -> Dict[str, Optional[float]]:
    """contribution = (total × weight_in_parent) / Σ_siblings(...) × 100.

    weight_in_parent 取节点成分在父 ETF 持仓中的合计权重; 父 ETF 不可解析或
    重叠为 0 时退化为 1.0 (兄弟之间用 total_score 直接比例)。
    """
    contribution_map: Dict[str, Optional[float]] = {}

    # 把同父亲的兄弟分组
    siblings_map: Dict[str, List[str]] = {}
    for nid, parent in parent_map.items():
        if parent is None:
            continue
        siblings_map.setdefault(parent, []).append(nid)

    # 缓存 weight_in_parent
    weight_cache: Dict[Tuple[str, str], float] = {}

    for parent_id, sibling_ids in siblings_map.items():
        contributions_raw: Dict[str, float] = {}
        for sib in sibling_ids:
            weight = _node_weight_in_parent(sib, parent_id, db, weight_cache)
            contributions_raw[sib] = total_score_map.get(sib, 0.0) * weight
        total = sum(contributions_raw.values())
        for sib in sibling_ids:
            if total <= 0:
                contribution_map[sib] = None
            else:
                contribution_map[sib] = round(
                    contributions_raw[sib] / total * 100.0, 2
                )

    # 顶层节点 (无 parent in batch) 的 contribution = None
    for nid in feature_map:
        contribution_map.setdefault(nid, None)
    return contribution_map


def _node_weight_in_parent(
    child_id: str,
    parent_id: str,
    db: Session,
    cache: Dict[Tuple[str, str], float],
) -> float:
    key = (child_id, parent_id)
    if key in cache:
        return cache[key]

    parent_etf = get_node_proxy_etf(parent_id, db)
    if not parent_etf:
        cache[key] = 1.0
        return 1.0

    latest = (
        db.query(ETFHolding.data_date)
        .filter(ETFHolding.etf_symbol == parent_etf)
        .order_by(ETFHolding.data_date.desc())
        .first()
    )
    if not latest:
        cache[key] = 1.0
        return 1.0

    parent_holdings = (
        db.query(ETFHolding.ticker, ETFHolding.weight)
        .filter(ETFHolding.etf_symbol == parent_etf)
        .filter(ETFHolding.data_date == latest[0])
        .all()
    )
    parent_map = {t: float(w) for t, w in parent_holdings}

    child_holdings = get_node_holdings(child_id, db)
    child_tickers = {h["ticker"] for h in child_holdings if h.get("ticker")}
    overlap = sum(parent_map.get(t, 0.0) for t in child_tickers)
    weight = overlap if overlap > 0 else 1.0
    cache[key] = weight
    return weight


def _pick_recommended_drill(
    *,
    node_id: str,
    children: List[str],
    total_score_map: Dict[str, float],
) -> Optional[str]:
    if not children:
        return None
    self_score = total_score_map.get(node_id, 0.0)
    best_child: Optional[str] = None
    best_score = -1.0
    for child in children:
        score = total_score_map.get(child, 0.0)
        if score > best_score:
            best_score = score
            best_child = child
    if best_child is None:
        return None
    if best_score - self_score >= _DRILL_DELTA_THRESHOLD:
        return best_child
    return None


# ============ ScoreSnapshot 持久化 / delta ============


def _resolve_snapshot_date(feature_map: Dict[str, _NodeFeatures]) -> date_t:
    """取所有节点价格序列中最新的一个日期作为快照日; 全部缺失时退化今天。"""
    latest: Optional[pd.Timestamp] = None
    for features in feature_map.values():
        df = features.price_df
        if df is None or df.empty:
            continue
        candidate = pd.to_datetime(df["date"].iloc[-1])
        if latest is None or candidate > latest:
            latest = candidate
    if latest is None:
        return date_t.today()
    return latest.date()


def _load_score_deltas(
    db: Session, node_ids: List[str], current_date: date_t
) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """返回 {node_id: (delta3d, delta5d)}; 历史缺失时为 None。"""
    if not node_ids:
        return {}
    earliest = current_date - timedelta(days=_DELTA_LOOKBACK_5D + 5)
    rows = (
        db.query(
            ScoreSnapshot.symbol,
            ScoreSnapshot.date,
            ScoreSnapshot.total_score,
        )
        .filter(ScoreSnapshot.symbol.in_(node_ids))
        .filter(ScoreSnapshot.symbol_type == _SNAPSHOT_SYMBOL_TYPE)
        .filter(ScoreSnapshot.date >= earliest)
        .filter(ScoreSnapshot.date < current_date)
        .all()
    )
    history: Dict[str, List[Tuple[date_t, float]]] = {}
    for sym, dt, score in rows:
        if score is None:
            continue
        history.setdefault(sym, []).append((dt, float(score)))

    deltas: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for nid in node_ids:
        records = sorted(history.get(nid, []), key=lambda x: x[0])
        d3 = _pick_delta_score(records, current_date, _DELTA_LOOKBACK_3D)
        d5 = _pick_delta_score(records, current_date, _DELTA_LOOKBACK_5D)
        deltas[nid] = (d3, d5)
    return deltas


def _pick_delta_score(
    records: List[Tuple[date_t, float]],
    current_date: date_t,
    lookback_days: int,
) -> Optional[float]:
    target = current_date - timedelta(days=lookback_days)
    # 取 ≤ target 的最新一条
    candidate: Optional[float] = None
    for dt, score in records:
        if dt <= target:
            candidate = score
        else:
            break
    return candidate


def _persist_score_snapshots(
    db: Session,
    results: List[NodeScoreResult],
    snapshot_date: date_t,
) -> None:
    """把当日 total_score 写回 ScoreSnapshot, 供后续 delta 计算使用。

    幂等: (symbol, symbol_type, date) 已存在时只更新 total_score / breakdown。
    """
    if not results:
        return
    for result in results:
        existing = (
            db.query(ScoreSnapshot)
            .filter(ScoreSnapshot.symbol == result.node_id)
            .filter(ScoreSnapshot.symbol_type == _SNAPSHOT_SYMBOL_TYPE)
            .filter(ScoreSnapshot.date == snapshot_date)
            .first()
        )
        breakdown = {
            "base_score": result.base_score,
            "representation_confidence": result.representation_confidence,
            "chain_confirmation": result.chain_confirmation,
            "raw_subscores": result.raw_subscores,
            "norm_subscores": result.norm_subscores,
            "notes": result.notes,
        }
        if existing is None:
            db.add(
                ScoreSnapshot(
                    symbol=result.node_id,
                    symbol_type=_SNAPSHOT_SYMBOL_TYPE,
                    date=snapshot_date,
                    total_score=float(result.total_score),
                    score_breakdown=breakdown,
                    thresholds_pass=True,
                )
            )
        else:
            existing.total_score = float(result.total_score)
            existing.score_breakdown = breakdown
    db.commit()


# ============ 工具 ============


def _clip01_100(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _to_float_safe(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f
