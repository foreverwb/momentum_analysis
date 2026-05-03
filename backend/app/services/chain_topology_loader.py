"""产业链拓扑 YAML → 数据库 loader（Task DD-10）。

职责：把 backend/app/configs/chain_topology/<sector>.yaml 幂等 upsert 到
chain_nodes / chain_edges 两张表。task_id 全部为 NULL（板块模板）。

禁止：
- 在本模块硬编码节点 ID 或坐标（CLAUDE.md §扩展性 — 新增板块只改 YAML）
- 直接抛 HTTPException（计算/数据层只抛领域异常）
- 触及 ETF / Stock / AnalyticNode 等其它表
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy.orm import Session

from app.models.database import (
    ChainEdge,
    ChainNode,
    SessionLocal,
)

logger = logging.getLogger(__name__)

# 配置目录：相对当前文件 ../configs/chain_topology/
_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs" / "chain_topology"


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


def load_chain_topology(
    sector: str,
    *,
    db: Optional[Session] = None,
    dry_run: bool = False,
    yaml_path: Optional[Path] = None,
) -> Dict[str, int]:
    """从 chain_topology/<sector>.yaml 幂等 upsert 单个板块的拓扑。

    Args:
        sector: 板块标识，大小写不敏感（内部转小写 + YAML 文件名匹配）。
        db: SQLAlchemy session；None 时自建并提交/回滚。
        dry_run: True 时仅解析 YAML，不写库（用于校验 / 预览）。
        yaml_path: 显式指定 YAML 路径；缺省时按 sector 在 _CONFIGS_DIR 查找。

    Returns:
        统计 dict: {nodes, edges}, 值为本次实际 upsert 的行数（dry_run 也返回 YAML 行数）。

    Raises:
        FileNotFoundError: YAML 文件不存在。
        ValueError: YAML 中 edges 引用了未声明的 node_id，或字段类型非法。
    """
    sector_key = sector.strip().lower()
    cfg_path = yaml_path or (_CONFIGS_DIR / f"{sector_key}.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"chain_topology YAML 不存在: {cfg_path}. "
            f"创建 backend/app/configs/chain_topology/{sector_key}.yaml 以启用此板块。"
        )

    with cfg_path.open("r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    yaml_sector = str(raw.get("sector") or sector_key).strip().lower()
    raw_nodes: List[Dict[str, Any]] = list(raw.get("nodes") or [])
    raw_edges: List[Dict[str, Any]] = list(raw.get("edges") or [])

    _validate_topology(raw_nodes, raw_edges)

    if dry_run:
        return {"nodes": len(raw_nodes), "edges": len(raw_edges)}

    own_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        nodes_count = _upsert_nodes(session, yaml_sector, raw_nodes)
        edges_count = _upsert_edges(session, yaml_sector, raw_edges)
        if own_session:
            session.commit()
        return {"nodes": nodes_count, "edges": edges_count}
    except Exception:
        if own_session:
            session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def load_all_chain_topologies(
    *,
    db: Optional[Session] = None,
    dry_run: bool = False,
) -> Dict[str, Dict[str, int]]:
    """扫描 chain_topology/ 目录下所有 *.yaml 并依次 upsert（幂等）。

    Args:
        db: SQLAlchemy session；None 时为每个文件自建（共享 commit/rollback）。
        dry_run: 只解析、不写库。

    Returns:
        {sector_key: {nodes, edges}} 总览。

    Raises:
        FileNotFoundError / ValueError 透传第一次失败。
    """
    if not _CONFIGS_DIR.exists():
        return {}

    summary: Dict[str, Dict[str, int]] = {}
    for entry in sorted(_CONFIGS_DIR.glob("*.yaml")):
        sector_key = entry.stem.lower()
        try:
            summary[sector_key] = load_chain_topology(
                sector_key, db=db, dry_run=dry_run, yaml_path=entry
            )
        except (FileNotFoundError, ValueError):
            logger.exception("chain_topology 加载失败: %s", entry)
            raise
    return summary


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def _validate_topology(
    raw_nodes: List[Dict[str, Any]],
    raw_edges: List[Dict[str, Any]],
) -> None:
    declared = {str(n["node_id"]) for n in raw_nodes if n.get("node_id")}
    if len(declared) != len(raw_nodes):
        raise ValueError("nodes 中存在重复的 node_id")

    missing: set[str] = set()
    for edge in raw_edges:
        for key in ("src", "dst"):
            nid = edge.get(key)
            if nid and nid not in declared:
                missing.add(str(nid))
    if missing:
        raise ValueError(
            f"edges 引用了未声明的 node_id: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def _upsert_nodes(
    db: Session,
    sector: str,
    raw_nodes: List[Dict[str, Any]],
) -> int:
    """按 (task_id=NULL, sector, node_id) 幂等 upsert 节点。"""
    count = 0
    for item in raw_nodes:
        node_id = str(item["node_id"])
        existing = (
            db.query(ChainNode)
            .filter(
                ChainNode.task_id.is_(None),
                ChainNode.sector == sector,
                ChainNode.node_id == node_id,
            )
            .first()
        )
        payload = {
            "role": item.get("role"),
            "tier": _opt_int(item.get("tier")),
            "cx": _opt_float(item.get("cx")),
            "cy": _opt_float(item.get("cy")),
            "w": _opt_float(item.get("w")),
            "h": _opt_float(item.get("h")),
            "proxy": item.get("proxy"),
            "proxy_type": item.get("proxy_type"),
            "proxy_label": item.get("proxy_label"),
        }
        if existing is None:
            db.add(ChainNode(
                task_id=None,
                sector=sector,
                node_id=node_id,
                **payload,
            ))
        else:
            for field, value in payload.items():
                setattr(existing, field, value)
        db.flush()
        count += 1
    return count


def _upsert_edges(
    db: Session,
    sector: str,
    raw_edges: List[Dict[str, Any]],
) -> int:
    """按 (task_id=NULL, sector, src, dst) 幂等 upsert 边。"""
    count = 0
    for item in raw_edges:
        src = str(item["src"])
        dst = str(item["dst"])
        is_cross = bool(item.get("is_cross", False))
        existing = (
            db.query(ChainEdge)
            .filter(
                ChainEdge.task_id.is_(None),
                ChainEdge.sector == sector,
                ChainEdge.src_node_id == src,
                ChainEdge.dst_node_id == dst,
            )
            .first()
        )
        if existing is None:
            db.add(ChainEdge(
                task_id=None,
                sector=sector,
                src_node_id=src,
                dst_node_id=dst,
                is_cross=is_cross,
            ))
        else:
            existing.is_cross = is_cross
        db.flush()
        count += 1
    return count


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _opt_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def configs_dir() -> Path:
    """暴露给测试用，避免直接访问 _CONFIGS_DIR 私有变量。"""
    return _CONFIGS_DIR
