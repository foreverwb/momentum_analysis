"""节点 taxonomy YAML → 数据库 loader

职责: 解析 node_taxonomy/*.yaml 并幂等写入 4.1 定义的五张表。
禁止: 直接抛出 HTTP 异常；不触及 ETF/Stock/PriceHistory 等业务表。
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.models.database import (
    AnalyticNode,
    NodeEdge,
    NodeProxy,
    SessionLocal,
    SyntheticBasketDefinition,
)

logger = logging.getLogger(__name__)

# 业务主键字段名，便于阅读 upsert 逻辑
_NODE_PK = "node_id"
_EDGE_UK = ("src_node_id", "dst_node_id", "edge_type")
_PROXY_UK = ("node_id", "etf_symbol", "role")
_BASKET_UK = ("node_id", "ticker")

# ETF 表检查是可选警告，不阻断写入
_WARN_MISSING_ETF = True


def load_taxonomy(
    yaml_path: Path,
    db: Session | None = None,
) -> dict[str, int]:
    """从 YAML 加载节点 taxonomy 到数据库（幂等 upsert）。

    Args:
        yaml_path: YAML 文件路径。
        db: SQLAlchemy session；None 时自动新建并在成功后提交。

    Returns:
        统计 dict，键为 ``nodes`` / ``edges`` / ``proxies`` / ``baskets``，
        值为本次实际写入（新建 + 更新）的行数。

    Raises:
        FileNotFoundError: yaml_path 不存在。
        ValueError: YAML 中引用了未声明的 node_id，或格式不符合约定。
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"taxonomy YAML 不存在: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)

    raw_nodes = data.get("nodes") or []
    raw_edges = data.get("edges") or []
    raw_proxies = data.get("proxies") or []
    raw_baskets = data.get("baskets") or []

    _validate_references(raw_nodes, raw_edges, raw_baskets)

    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        counts = {
            "nodes": _upsert_nodes(db, raw_nodes),
            "edges": _upsert_edges(db, raw_edges),
            "proxies": _upsert_proxies(db, raw_proxies),
            "baskets": _upsert_baskets(db, raw_baskets),
        }
        if own_session:
            db.commit()
        return counts
    except Exception:
        if own_session:
            db.rollback()
        raise
    finally:
        if own_session:
            db.close()


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _validate_references(
    raw_nodes: list[dict],
    raw_edges: list[dict],
    raw_baskets: list[dict],
) -> None:
    """确保 edges / baskets 引用的 node_id 均已在 nodes 段中声明。

    Raises:
        ValueError: 发现未声明的 node_id 引用。
    """
    declared = {n["node_id"] for n in raw_nodes}

    missing_edge: set[str] = set()
    for edge in raw_edges:
        for key in ("src", "dst"):
            nid = edge.get(key)
            if nid and nid not in declared:
                missing_edge.add(nid)
    if missing_edge:
        raise ValueError(
            f"edges 中引用了未在 nodes 中声明的 node_id: {sorted(missing_edge)}"
        )

    missing_basket: set[str] = set()
    for basket in raw_baskets:
        nid = basket.get("node_id")
        if nid and nid not in declared:
            missing_basket.add(nid)
    if missing_basket:
        raise ValueError(
            f"baskets 中引用了未在 nodes 中声明的 node_id: {sorted(missing_basket)}"
        )


# ---------------------------------------------------------------------------
# Upsert 各表
# ---------------------------------------------------------------------------

def _upsert_nodes(db: Session, raw_nodes: list[dict]) -> int:
    """Upsert AnalyticNode 按 node_id 业务主键。"""
    count = 0
    for item in raw_nodes:
        node_id = item["node_id"]
        existing = db.query(AnalyticNode).filter_by(node_id=node_id).first()
        if existing is None:
            row = AnalyticNode(
                node_id=node_id,
                label=item["label"],
                sublabel=item.get("sublabel"),
                node_type=item["node_type"],
                level=item.get("level", 0),
                representation_confidence=item.get("representation_confidence", 1.0),
            )
            db.add(row)
        else:
            existing.label = item["label"]
            existing.sublabel = item.get("sublabel")
            existing.node_type = item["node_type"]
            existing.level = item.get("level", 0)
            existing.representation_confidence = item.get(
                "representation_confidence", 1.0
            )
        db.flush()
        count += 1
    return count


def _upsert_edges(db: Session, raw_edges: list[dict]) -> int:
    """Upsert NodeEdge 按 (src_node_id, dst_node_id, edge_type) 三元组。"""
    count = 0
    for item in raw_edges:
        src = item["src"]
        dst = item["dst"]
        etype = item["type"]
        weight = float(item.get("weight", 1.0))

        existing = (
            db.query(NodeEdge)
            .filter_by(src_node_id=src, dst_node_id=dst, edge_type=etype)
            .first()
        )
        if existing is None:
            row = NodeEdge(
                src_node_id=src,
                dst_node_id=dst,
                edge_type=etype,
                weight=weight,
            )
            db.add(row)
        else:
            existing.weight = weight
        db.flush()
        count += 1
    return count


def _upsert_proxies(db: Session, raw_proxies: list[dict]) -> int:
    """Upsert NodeProxy 按 (node_id, etf_symbol, role) 三元组。"""
    count = 0
    for item in raw_proxies:
        node_id = item["node_id"]
        etf = item["etf"]
        role = item.get("role", "primary")
        purity = float(item.get("purity", 1.0))

        existing = (
            db.query(NodeProxy)
            .filter_by(node_id=node_id, etf_symbol=etf, role=role)
            .first()
        )
        if existing is None:
            row = NodeProxy(
                node_id=node_id,
                etf_symbol=etf,
                role=role,
                purity=purity,
            )
            db.add(row)
        else:
            existing.purity = purity
        db.flush()
        count += 1

    _warn_missing_etfs(db, raw_proxies)
    return count


def _warn_missing_etfs(db: Session, raw_proxies: list[dict]) -> None:
    """对 ETF 表中不存在的 proxy ETF 发出警告（不阻断写入）。"""
    if not _WARN_MISSING_ETF:
        return
    try:
        from app.models.database import ETF  # noqa: PLC0415

        etf_symbols = {p["etf"] for p in raw_proxies}
        existing_symbols = {
            row.symbol
            for row in db.query(ETF.symbol).filter(ETF.symbol.in_(etf_symbols)).all()
        }
        missing = etf_symbols - existing_symbols
        if missing:
            warnings.warn(
                f"以下 proxy ETF 在 etfs 表中不存在（仅警告，不阻断写入）: "
                f"{sorted(missing)}",
                stacklevel=4,
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("ETF 存在性检查跳过: %s", exc)


def _upsert_baskets(db: Session, raw_baskets: list[dict]) -> int:
    """Upsert SyntheticBasketDefinition 按 (node_id, ticker) 二元组。"""
    count = 0
    for item in raw_baskets:
        node_id = item["node_id"]
        ticker = item["ticker"]
        strategy = item.get("weighting_strategy", "equal")
        chain_ext = bool(item.get("chain_extension", False))

        existing = (
            db.query(SyntheticBasketDefinition)
            .filter_by(node_id=node_id, ticker=ticker)
            .first()
        )
        if existing is None:
            row = SyntheticBasketDefinition(
                node_id=node_id,
                ticker=ticker,
                weighting_strategy=strategy,
                chain_extension=chain_ext,
            )
            db.add(row)
        else:
            existing.weighting_strategy = strategy
            existing.chain_extension = chain_ext
        db.flush()
        count += 1
    return count
