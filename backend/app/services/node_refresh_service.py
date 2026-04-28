"""节点层数据管道冷启动服务 (Phase 4 — Drilldown Upgrade Task 4.12)。

职责: 把 Task 4.3 (synthetic 节点价格篮合成) 与 Task 4.4 (节点评分写
ScoreSnapshot) 串成"每日一次"的入口。供 CLI 子命令 / 后续 import.sh 调用。

禁止:
- 修改 node_basket / node_score 任何已有函数 (CLAUDE.md §扩展性)
- 在本层抛 HTTPException (分层错误处理 — 服务层只抛领域异常 / 返回 dict)
- 改动 rotation refresh 路径 (Phase 4 §0.6 R10)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.api.nodes import _traverse_nodes  # noqa: WPS437 — 复用 hybrid 遍历
from app.models.database import AnalyticNode
from app.services.calculators.node_basket import (
    compute_basket_price_series,
    is_synthetic_node,
)
from app.services.calculators.node_score import batch_calculate_node_scores

logger = logging.getLogger(__name__)


# 节点层最大深度 — 与 Task.max_depth 默认一致
_DEFAULT_MAX_DEPTH = 5


def refresh_node_pipeline(
    root_node: str,
    db: Session,
    *,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> Dict[str, Any]:
    """串联 Task 4.3 + 4.4: 拉取根节点子树, 合成 synthetic 价格序列, 批量计算评分。

    步骤:
        1. 用 hybrid lens 遍历 root_node 子树, 拿到所有 node_id
        2. 对每个 synthetic 节点调 compute_basket_price_series (内部 idempotent upsert)
        3. 调 batch_calculate_node_scores 批量评分 (末尾写 ScoreSnapshot symbol_type=node)
        4. 返回汇总统计 + 异常节点列表 (不阻断主流程)

    Args:
        root_node: 根节点业务主键 (如 'XLK')。
        db: SQLAlchemy session。
        max_depth: 子树遍历深度上限。

    Returns:
        {processed, basket_rows_written, snapshots_written, synthetic_nodes, errors[]}.

    Raises:
        ValueError: root_node 不合法 / 不存在。
    """
    if not isinstance(root_node, str) or not root_node.strip():
        raise ValueError("root_node must be a non-empty string")
    normalized_root = root_node.strip().upper()

    root_exists = (
        db.query(AnalyticNode.id)
        .filter(AnalyticNode.node_id == normalized_root)
        .first()
        is not None
    )
    if not root_exists:
        raise ValueError(f"root_node '{normalized_root}' not found in AnalyticNode")

    node_ids, _ = _traverse_nodes(db, normalized_root, "hybrid", max_depth)
    if not node_ids:
        node_ids = [normalized_root]

    errors: List[Dict[str, str]] = []

    # Step 1: 合成 synthetic 节点价格序列
    basket_rows_written = 0
    synthetic_nodes: List[str] = []
    for node_id in node_ids:
        try:
            if not is_synthetic_node(node_id, db):
                continue
            synthetic_nodes.append(node_id)
            result = compute_basket_price_series(node_id, db)
            if result.error:
                errors.append({"node_id": node_id, "stage": "basket", "error": result.error})
            basket_rows_written += result.rows_written
        except Exception as exc:  # 计算层异常不阻断后续节点
            logger.exception("compute_basket_price_series failed for %s", node_id)
            errors.append({"node_id": node_id, "stage": "basket", "error": str(exc)})

    # Step 2: 批量评分 (Task 4.4 末尾会 upsert ScoreSnapshot symbol_type='node')
    snapshots_written = 0
    try:
        results = batch_calculate_node_scores(node_ids, db)
        snapshots_written = len(results)
    except Exception as exc:
        logger.exception("batch_calculate_node_scores failed for root=%s", normalized_root)
        errors.append({"node_id": normalized_root, "stage": "score", "error": str(exc)})

    return {
        "root_node": normalized_root,
        "processed": len(node_ids),
        "synthetic_nodes": synthetic_nodes,
        "basket_rows_written": basket_rows_written,
        "snapshots_written": snapshots_written,
        "errors": errors,
    }
