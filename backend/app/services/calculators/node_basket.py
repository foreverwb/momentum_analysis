"""Synthetic 节点价格篮合成器。

职责: 把没有 ETF proxy 的 synthetic 节点（硬件 / 设备 / 计算 / 存储 / 连接 / 光 / 铜）
从成分股价格序列合成出节点级日频"价格 / 收益 / 广度"序列，写入 NodePriceSeries，
并提供节点 holdings / proxy 查询的统一接口。

禁止:
- 修改 etf_score.py / momentum.py / technical.py（4.4 才动）
- 在计算层抛 HTTPException（按 CLAUDE.md 分层错误处理）
- 价格序列对齐使用 ffill 跨多日
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_t
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.database import (
    AnalyticNode,
    ETFHolding,
    ImportedData,
    NodeEdge,
    NodeEdgeType,
    NodePriceSeries,
    NodeProxy,
    NodeProxyRole,
    PriceHistory,
    SyntheticBasketDefinition,
)


# 篮内归一化权重和的目标值；任何策略最终归一到该值
# 来源: 需求文档 §4.3 — 节点收益 = Σ w_i * r_i, Σw_i = 1
_WEIGHT_SUM_TARGET = 1.0

# market_cap 字段在 ImportedData.data JSON 中的常见键名
# 需求文档 §4.3 — finviz market_cap 优先, 缺失时退化 equal
_MCAP_KEYS = ("market_cap", "marketcap", "Market Cap", "marketCap")


@dataclass
class BasketComputeResult:
    """compute_basket_price_series 的返回值。"""

    node_id: str
    rows_written: int
    coverage_avg: float
    representation_confidence: float
    last_date: Optional[date_t]
    error: Optional[str] = None


# ============ 主接口 ============

def compute_basket_price_series(
    node_id: str,
    db: Session,
    *,
    base_value: float = 100.0,
    min_constituents: int = 2,
    force_recompute: bool = False,
) -> BasketComputeResult:
    """合成 synthetic 节点的日频"价格"序列并写入 NodePriceSeries。

    Args:
        node_id: 节点业务主键。
        db: SQLAlchemy session。
        base_value: 起始基准价格（默认 100）。
        min_constituents: 当日有效成分股数下限，低于则跳过该日。
        force_recompute: True 时先清空既有 NodePriceSeries 再重算。

    Returns:
        BasketComputeResult — 写入行数、平均覆盖率、representation_confidence。

    Raises:
        ValueError: node_id 不是合法字符串。
    """
    if not node_id or not isinstance(node_id, str):
        raise ValueError("node_id must be a non-empty string")

    defs = (
        db.query(SyntheticBasketDefinition)
        .filter(SyntheticBasketDefinition.node_id == node_id)
        .all()
    )
    if not defs:
        return BasketComputeResult(
            node_id=node_id, rows_written=0, coverage_avg=0.0,
            representation_confidence=0.0, last_date=None,
            error="no synthetic basket definition",
        )

    pivot = _load_price_pivot(db, [d.ticker for d in defs])
    if pivot is None or pivot.empty:
        return BasketComputeResult(
            node_id=node_id, rows_written=0, coverage_avg=0.0,
            representation_confidence=0.0, last_date=None,
            error="no price history for any constituent",
        )

    strategy = _basket_strategy(defs)
    weights_df = _build_weight_matrix(strategy, defs, pivot, db, node_id)

    rows = _build_synthetic_series(
        pivot=pivot,
        weights=weights_df,
        total_constituents=len(defs),
        base_value=base_value,
        min_constituents=min_constituents,
    )

    rows_written = _persist_series(db, node_id, strategy, rows, force_recompute)

    coverage_avg = float(np.mean([r["coverage"] for r in rows])) if rows else 0.0
    base_conf = _node_representation_confidence(db, node_id)
    rep_conf = base_conf * coverage_avg
    last_date = rows[-1]["date"] if rows else None

    return BasketComputeResult(
        node_id=node_id,
        rows_written=rows_written,
        coverage_avg=coverage_avg,
        representation_confidence=rep_conf,
        last_date=last_date,
    )


def get_node_holdings(node_id: str, db: Session) -> List[Dict[str, Any]]:
    """返回节点成分股清单（统一 ETF proxy 与 synthetic 两种来源）。

    Args:
        node_id: 节点业务主键。
        db: SQLAlchemy session。

    Returns:
        按 weight 降序的 dict 列表，字段 ticker/weight/name/is_chain_extension/weighting_strategy。

    Raises:
        ValueError: node_id 不合法。
    """
    if not node_id or not isinstance(node_id, str):
        raise ValueError("node_id must be a non-empty string")

    proxy_etf = get_node_proxy_etf(node_id, db)
    if proxy_etf:
        return _holdings_from_etf(db, proxy_etf)
    return _holdings_from_basket(db, node_id)


def get_node_proxy_etf(node_id: str, db: Session) -> Optional[str]:
    """返回节点的 primary proxy ETF symbol；synthetic 节点返回 None。"""
    proxy = (
        db.query(NodeProxy)
        .filter(NodeProxy.node_id == node_id)
        .filter(NodeProxy.role == NodeProxyRole.PRIMARY.value)
        .first()
    )
    return proxy.etf_symbol if proxy else None


def is_synthetic_node(node_id: str, db: Session) -> bool:
    """没有 primary ETF proxy 且存在 basket 定义 → True。"""
    if get_node_proxy_etf(node_id, db) is not None:
        return False
    has_basket = (
        db.query(SyntheticBasketDefinition.id)
        .filter(SyntheticBasketDefinition.node_id == node_id)
        .first()
        is not None
    )
    return has_basket


# ============ 内部辅助 ============

def _load_price_pivot(db: Session, tickers: List[str]) -> Optional[pd.DataFrame]:
    """读取成分股 PriceHistory 并 pivot 为 date × ticker 的 close 矩阵。"""
    rows = (
        db.query(PriceHistory.symbol, PriceHistory.date, PriceHistory.close)
        .filter(PriceHistory.symbol.in_(tickers))
        .all()
    )
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    pivot = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    pivot = pivot.sort_index()
    pivot.index = pd.to_datetime(pivot.index)

    # 按业务日历对齐, 不 ffill 跨多日（避免污染累乘）
    bdays = pd.bdate_range(pivot.index.min(), pivot.index.max())
    pivot = pivot.reindex(bdays)

    # 补齐缺失列（某 ticker 完全无数据）以便后续按列广播
    for t in tickers:
        if t not in pivot.columns:
            pivot[t] = np.nan
    return pivot[tickers]


def _basket_strategy(defs: List[SyntheticBasketDefinition]) -> str:
    """同一篮内所有成分共享一个策略；取第一个非空值。"""
    for d in defs:
        if d.weighting_strategy:
            return d.weighting_strategy
    return "equal"


def _build_weight_matrix(
    strategy: str,
    defs: List[SyntheticBasketDefinition],
    pivot: pd.DataFrame,
    db: Session,
    node_id: str,
) -> pd.DataFrame:
    """构造与 pivot 同形的权重矩阵；NaN 表示当日该 ticker 无数据。

    每日按行从 pivot 的 mask 派生有效成分集合，权重已在 _build_synthetic_series
    内做最终归一化（这里只给出"原始权重"的列向量并广播到每日）。
    """
    tickers = list(pivot.columns)
    raw = _strategy_dispatch(strategy, defs, tickers, db, node_id)

    weights = pd.DataFrame(
        np.tile(raw.values, (len(pivot.index), 1)),
        index=pivot.index,
        columns=tickers,
    )
    # 当日 ticker 无价格 → 权重置 NaN, 在归一化时被剔除
    weights = weights.where(pivot.notna(), other=np.nan)
    return weights


def _strategy_dispatch(
    strategy: str,
    defs: List[SyntheticBasketDefinition],
    tickers: List[str],
    db: Session,
    node_id: str,
) -> pd.Series:
    """策略表分派，避免 if-else 枚举链。"""
    handlers = {
        "equal": _weights_equal,
        "mcap": _weights_mcap,
        "parent_etf_weight": _weights_parent_etf,
        "fixed": _weights_fixed,
    }
    handler = handlers.get(strategy, _weights_equal)
    return handler(defs, tickers, db, node_id)


def _weights_equal(
    defs: List[SyntheticBasketDefinition],
    tickers: List[str],
    db: Session,
    node_id: str,
) -> pd.Series:
    return pd.Series(1.0, index=tickers)


def _weights_fixed(
    defs: List[SyntheticBasketDefinition],
    tickers: List[str],
    db: Session,
    node_id: str,
) -> pd.Series:
    target = {d.ticker: d.target_weight for d in defs}
    raw = pd.Series(
        [target.get(t) if target.get(t) is not None else np.nan for t in tickers],
        index=tickers,
    )
    if raw.isna().all():
        return _weights_equal(defs, tickers, db, node_id)
    return raw.fillna(raw.dropna().mean())


def _weights_mcap(
    defs: List[SyntheticBasketDefinition],
    tickers: List[str],
    db: Session,
    node_id: str,
) -> pd.Series:
    """从 ImportedData(source='finviz') 取最新 market_cap; 缺失退化 equal。"""
    caps: Dict[str, float] = {}
    for ticker in tickers:
        row = (
            db.query(ImportedData)
            .filter(ImportedData.symbol == ticker)
            .filter(ImportedData.source == "finviz")
            .order_by(ImportedData.date.desc(), ImportedData.id.desc())
            .first()
        )
        if not row or not isinstance(row.data, dict):
            continue
        cap = _extract_mcap(row.data)
        if cap is not None and cap > 0:
            caps[ticker] = cap

    if not caps:
        return _weights_equal(defs, tickers, db, node_id)

    fallback = float(np.mean(list(caps.values())))
    return pd.Series([caps.get(t, fallback) for t in tickers], index=tickers)


def _weights_parent_etf(
    defs: List[SyntheticBasketDefinition],
    tickers: List[str],
    db: Session,
    node_id: str,
) -> pd.Series:
    """以节点 GICS 父节点的 primary proxy ETF 持仓权重为权重。"""
    parent_etf = _find_classification_parent_etf(db, node_id)
    if not parent_etf:
        return _weights_equal(defs, tickers, db, node_id)

    latest_date = (
        db.query(ETFHolding.data_date)
        .filter(ETFHolding.etf_symbol == parent_etf)
        .order_by(ETFHolding.data_date.desc())
        .first()
    )
    if not latest_date:
        return _weights_equal(defs, tickers, db, node_id)

    holdings = (
        db.query(ETFHolding.ticker, ETFHolding.weight)
        .filter(ETFHolding.etf_symbol == parent_etf)
        .filter(ETFHolding.data_date == latest_date[0])
        .all()
    )
    weight_map = {t: w for t, w in holdings}

    extension_flags = {d.ticker: bool(d.chain_extension) for d in defs}
    raw_values: List[float] = []
    has_any = False
    for t in tickers:
        w = weight_map.get(t)
        if w is None:
            # 跨链扩展票允许缺失, 退化为后续填充
            raw_values.append(np.nan if extension_flags.get(t) else np.nan)
        else:
            raw_values.append(float(w))
            has_any = True

    raw = pd.Series(raw_values, index=tickers)
    if not has_any:
        return _weights_equal(defs, tickers, db, node_id)
    # 缺失票回退为篮内已知权重的均值（chain_extension 票常见）
    raw = raw.fillna(raw.dropna().mean())
    return raw


def _find_classification_parent_etf(db: Session, node_id: str) -> Optional[str]:
    """通过 NodeEdge.classification_parent 找父节点, 再取其 primary proxy ETF。"""
    edge = (
        db.query(NodeEdge)
        .filter(NodeEdge.dst_node_id == node_id)
        .filter(NodeEdge.edge_type == NodeEdgeType.CLASSIFICATION_PARENT.value)
        .first()
    )
    if not edge:
        return None
    return get_node_proxy_etf(edge.src_node_id, db)


def _extract_mcap(data: Dict[str, Any]) -> Optional[float]:
    for key in _MCAP_KEYS:
        if key in data:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    return None


def _build_synthetic_series(
    pivot: pd.DataFrame,
    weights: pd.DataFrame,
    total_constituents: int,
    base_value: float,
    min_constituents: int,
) -> List[Dict[str, Any]]:
    """累乘日频加权收益, 输出 NodePriceSeries 行字典列表。"""
    returns = pivot.pct_change()  # 第一天全 NaN

    out: List[Dict[str, Any]] = []
    cumulative = float(base_value)

    for ts in returns.index:
        r_row = returns.loc[ts]
        valid_mask = r_row.notna()
        valid_count = int(valid_mask.sum())
        if valid_count < min_constituents:
            continue

        valid_returns = r_row[valid_mask]
        w_row = weights.loc[ts, valid_mask.index][valid_mask]
        # 清洗并归一化到 Σw = 1
        w_clean = pd.Series(np.nan_to_num(w_row.values, nan=0.0), index=w_row.index)
        if w_clean.sum() <= 0:
            w_clean = pd.Series(1.0 / valid_count, index=valid_returns.index)
        else:
            w_clean = w_clean * (_WEIGHT_SUM_TARGET / w_clean.sum())

        period_return = float((w_clean.values * valid_returns.values).sum())
        cumulative *= 1.0 + period_return

        out.append({
            "date": ts.date() if hasattr(ts, "date") else ts,
            "close": cumulative,
            "constituents_count": valid_count,
            "coverage": valid_count / float(total_constituents) if total_constituents else 0.0,
        })

    return out


def _persist_series(
    db: Session,
    node_id: str,
    strategy: str,
    rows: List[Dict[str, Any]],
    force_recompute: bool,
) -> int:
    """将合成序列幂等写入 NodePriceSeries, 返回新插入的行数。"""
    if force_recompute:
        db.query(NodePriceSeries).filter(NodePriceSeries.node_id == node_id).delete()
        db.flush()
        existing: set = set()
    else:
        existing = {
            r[0]
            for r in db.query(NodePriceSeries.date)
            .filter(NodePriceSeries.node_id == node_id)
            .all()
        }

    written = 0
    for r in rows:
        if r["date"] in existing:
            continue
        db.add(NodePriceSeries(
            node_id=node_id,
            date=r["date"],
            close=float(r["close"]),
            constituents_count=int(r["constituents_count"]),
            coverage_ratio=float(r["coverage"]),
            weighting_strategy=strategy,
        ))
        written += 1
    db.commit()
    return written


def _node_representation_confidence(db: Session, node_id: str) -> float:
    node = db.query(AnalyticNode).filter(AnalyticNode.node_id == node_id).first()
    if not node or node.representation_confidence is None:
        return 1.0
    return float(node.representation_confidence)


def _holdings_from_etf(db: Session, etf_symbol: str) -> List[Dict[str, Any]]:
    latest_date = (
        db.query(ETFHolding.data_date)
        .filter(ETFHolding.etf_symbol == etf_symbol)
        .order_by(ETFHolding.data_date.desc())
        .first()
    )
    if not latest_date:
        return []
    rows = (
        db.query(ETFHolding.ticker, ETFHolding.weight)
        .filter(ETFHolding.etf_symbol == etf_symbol)
        .filter(ETFHolding.data_date == latest_date[0])
        .all()
    )
    holdings = [
        {
            "ticker": t,
            "weight": float(w),
            "name": None,
            "is_chain_extension": False,
            "weighting_strategy": "etf_proxy",
        }
        for t, w in rows
    ]
    holdings.sort(key=lambda x: x["weight"], reverse=True)
    return holdings


def _holdings_from_basket(db: Session, node_id: str) -> List[Dict[str, Any]]:
    defs = (
        db.query(SyntheticBasketDefinition)
        .filter(SyntheticBasketDefinition.node_id == node_id)
        .all()
    )
    if not defs:
        return []

    strategy = _basket_strategy(defs)
    tickers = [d.ticker for d in defs]
    raw = _strategy_dispatch(strategy, defs, tickers, db, node_id)
    cleaned = pd.Series(np.nan_to_num(raw.values, nan=0.0), index=raw.index)
    total = float(cleaned.sum())
    if total <= 0:
        cleaned = pd.Series(1.0 / len(tickers), index=tickers)
        total = 1.0
    weights_pct = (cleaned / total) * 100.0

    extension_flags = {d.ticker: bool(d.chain_extension) for d in defs}
    holdings = [
        {
            "ticker": t,
            "weight": float(weights_pct[t]),
            "name": None,
            "is_chain_extension": extension_flags.get(t, False),
            "weighting_strategy": strategy,
        }
        for t in tickers
    ]
    holdings.sort(key=lambda x: x["weight"], reverse=True)
    return holdings
