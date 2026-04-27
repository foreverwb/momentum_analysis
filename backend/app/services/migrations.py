"""一次性数据迁移脚本集合。

本模块只放"一次性"或"按需重跑"的迁移函数，禁止承载常态业务逻辑。
每个迁移必须满足：
- 幂等：重复执行不会损坏已迁移数据
- 支持 dry_run：只打印计划不写库
- 不删除旧字段：保留向后兼容兜底
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.database import NodeProxy, Task

logger = logging.getLogger(__name__)


def migrate_drilldown_tasks_to_node_first(
    db: Session,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """把现有 drilldown 任务从 sector + etfs[] 迁移到 root_node + selected_nodes。

    映射规则:
    - root_node = sector  (XLK / XLF / ...)
    - selected_nodes 起始包含 root_node 自身, 然后对每个 etfs 中的 ETF symbol,
      反查 NodeProxy 找对应的 node_id; 找不到的 ETF 保留在 task.extra
      的 selected_etfs_legacy 列表里。
    - view_mode = 'gics' (默认)
    - max_depth = 3

    幂等性: 已存在 root_node 的任务跳过 (skipped).

    Args:
        db: SQLAlchemy session
        dry_run: True 时只统计不写库

    Returns:
        {"migrated": N, "skipped": M, "warnings": [...], "details": [...]}
    """
    drilldown_tasks: List[Task] = (
        db.query(Task).filter(Task.type == "drilldown").all()
    )

    migrated = 0
    skipped = 0
    warnings: List[str] = []
    details: List[Dict[str, Any]] = []

    for task in drilldown_tasks:
        # 幂等：已经迁移过的跳过
        if getattr(task, "root_node", None):
            skipped += 1
            details.append({
                "task_id": task.id,
                "status": "skipped",
                "reason": "root_node already set",
                "root_node": task.root_node,
            })
            continue

        sector = (task.sector or "").strip().upper()
        if not sector:
            warnings.append(f"task {task.id} has no sector, cannot migrate")
            skipped += 1
            details.append({
                "task_id": task.id,
                "status": "skipped",
                "reason": "missing sector",
            })
            continue

        etfs_raw = task.etfs or []
        etf_symbols = [
            str(s).strip().upper() for s in etfs_raw
            if isinstance(s, str) and str(s).strip()
        ]

        # selected_nodes 默认包含 root_node 自身, 然后追加 ETF 反查到的 node_id
        selected_nodes: List[str] = [sector]
        legacy_etfs: List[str] = []

        for etf_symbol in etf_symbols:
            proxies = (
                db.query(NodeProxy)
                .filter(NodeProxy.etf_symbol == etf_symbol)
                .all()
            )
            if not proxies:
                legacy_etfs.append(etf_symbol)
                warnings.append(
                    f"task {task.id}: ETF {etf_symbol} 未找到 NodeProxy, "
                    f"保留到 extra.selected_etfs_legacy"
                )
                continue
            # 优先取 primary, 否则任取一个
            primary = next(
                (p for p in proxies if (p.role or "").lower() == "primary"),
                proxies[0],
            )
            node_id = primary.node_id
            if node_id and node_id not in selected_nodes:
                selected_nodes.append(node_id)

        new_extra = dict(getattr(task, "extra", None) or {})
        if legacy_etfs:
            new_extra["selected_etfs_legacy"] = legacy_etfs

        details.append({
            "task_id": task.id,
            "status": "migrated",
            "root_node": sector,
            "selected_nodes": selected_nodes,
            "legacy_etfs": legacy_etfs,
        })

        if not dry_run:
            task.root_node = sector
            task.view_mode = task.view_mode or "gics"
            task.selected_nodes = selected_nodes
            task.pinned_evidence_nodes = list(getattr(task, "pinned_evidence_nodes", None) or [])
            task.max_depth = int(getattr(task, "max_depth", None) or 3)
            task.extra = new_extra

        migrated += 1

    if not dry_run:
        db.commit()
    else:
        logger.info(
            "[dry-run] migrate_drilldown_tasks_to_node_first: "
            "would migrate=%d, skip=%d", migrated, skipped,
        )

    return {
        "migrated": migrated,
        "skipped": skipped,
        "warnings": warnings,
        "details": details,
        "dry_run": dry_run,
    }
