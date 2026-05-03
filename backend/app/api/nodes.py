"""节点中心化下钻 API（Phase 4 — Drilldown Upgrade Task 4.6/4.11）。

职责: 提供前端"节点树 / 节点持仓 / 节点走势对比 / 节点目录"4 个只读端点。
所有计算结果来自 Task 4.3/4.4 的引擎; 本模块不做任何评分或合成逻辑,
只负责图遍历、契约组装、字段格式化。

禁止:
- 修改 node_score / node_basket / series_utils 的任何函数 (CLAUDE.md §扩展性)
- 在本层抛领域异常 (按 CLAUDE.md 分层错误处理: HTTPException 仅在本层)
- 写库 (节点价格/snapshot 的 idempotent upsert 由计算引擎内部完成,
  与 Task 4.6 约束中"compute_basket_price_series 已在 4.3 内部 idempotent upsert"
  的兜底口径一致)
"""

from __future__ import annotations

from datetime import date as date_t
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.models import get_db
from app.models.database import (
    AnalyticNode,
    ChainEdge,
    ChainNode,
    NodeEdge,
    NodeEdgeType,
    NodeProxy,
    NodePriceSeries,
    PriceHistory,
    Stock,
    Task,
)
from app.api.series_utils import _format_date_labels  # noqa: WPS437 — 复用同模块格式化
from app.services.calculators.node_basket import get_node_holdings
from app.services.calculators.node_score import (
    NodeScoreResult,
    batch_calculate_node_scores,
)
from app.services.calculators.chain_signals import (
    ChainSignalResult,
    compute_chain_signals_for_sector,
    load_chain_signal_rules,
    compute_chain_signals,
)
from app.services.calculators.chain_strategy import (
    ChainStrategyResult,
    StrategyConfig,
    StrategyNodeBrief,
    compute_chain_strategy,
    load_chain_strategy_config,
)


router = APIRouter()

# 目录端点挂在 /api/nodes (不含 task_id) — Task 4.11
catalog_router = APIRouter()


# ============ 常量 ============

# 节点树缓存窗口 — 与前端 React Query staleTime 5min 对齐
_NODE_TREE_CACHE_SECONDS = 300

# 走势对比固定 3 路 (node / parent / SPY) 的颜色
# 来源: README "Trend Chart" 段 + Phase4 Task 4.6 §3
_COLOR_NODE = "#3b82f6"
_COLOR_PARENT = "#8b5cf6"
_COLOR_SPY = "#94a3b8"
_BENCHMARK_SYMBOL = "SPY"

# 走势对比读取的最大天数, 满足 period=63 + 缓冲
_TREND_PRICE_LIMIT = 120

# 持仓 rs20d / return20d 计算窗口
_HOLDING_RS_WINDOW = 20

# proxyType 映射: 计算层 'unknown' (无 proxy 也无 basket) 退化为 'synthetic'
# README 类型 NodeProxyType 仅允许 'etf' | 'synthetic'
_PROXY_TYPE_FALLBACK = "synthetic"

# 合法 lens
_VALID_LENS = ("gics", "chain", "hybrid")

# 走势对比合法参数
_VALID_TREND_PERIODS = (5, 20, 63)
_VALID_TREND_METRICS = ("relative", "return20d", "score")
_VALID_LABEL_TZ = ("beijing", "market")


# ============ 0. GET /api/nodes/catalog (Task 4.11 — task-free) ============


@catalog_router.get("/catalog", response_model=List[Dict[str, Any]])
async def get_node_catalog(
    root_node: str,
    include_evidence: bool = True,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """返回某个根节点（如 XLK）下可被选中的所有子节点 + 证据节点。

    用于创建任务和追加节点的 modal（Task 4.11）。

    Args:
        root_node: 根节点业务 ID（如 'XLK'）。
        include_evidence: 是否包含 corroborates 边连到子树内任意节点的 evidence 节点。
        db: SQLAlchemy session。

    Returns:
        [{id, label, sublabel, level, node_type, proxy_etf, proxy_label, parent_id}]
        按 level 升序 / label 字典序排列。

    Raises:
        HTTPException 404: root_node 不存在。
    """
    normalized_root = root_node.strip().upper()
    if not _node_exists(db, normalized_root):
        raise HTTPException(status_code=404, detail=f"Node {normalized_root} not found")

    # 取 root 的所有后代 (hybrid lens 覆盖 gics + chain 两类边)
    node_ids, _ = _traverse_nodes(db, normalized_root, "hybrid", max_depth=10)

    # 批量拉节点元数据
    nodes = (
        db.query(AnalyticNode)
        .filter(AnalyticNode.node_id.in_(node_ids))
        .all()
    )
    node_meta: Dict[str, AnalyticNode] = {n.node_id: n for n in nodes}

    # 批量拉 primary proxy (每节点至多一条)
    proxy_rows = (
        db.query(NodeProxy.node_id, NodeProxy.etf_symbol)
        .filter(NodeProxy.node_id.in_(node_ids))
        .filter(NodeProxy.role == "primary")
        .all()
    )
    primary_proxy: Dict[str, str] = {r.node_id: r.etf_symbol for r in proxy_rows}

    # 批量拉父节点 (classification_parent edge src → node)
    parent_rows = (
        db.query(NodeEdge.dst_node_id, NodeEdge.src_node_id)
        .filter(NodeEdge.dst_node_id.in_(node_ids))
        .filter(NodeEdge.edge_type == NodeEdgeType.CLASSIFICATION_PARENT.value)
        .all()
    )
    # dst=child, src=parent
    parent_map: Dict[str, str] = {r.dst_node_id: r.src_node_id for r in parent_rows}

    result_ids = set(node_ids)

    # 可选: evidence 节点 — corroborates 边目标在子树内
    if include_evidence:
        evidence_rows = (
            db.query(NodeEdge.src_node_id)
            .filter(NodeEdge.dst_node_id.in_(node_ids))
            .filter(NodeEdge.edge_type == NodeEdgeType.CORROBORATES.value)
            .all()
        )
        evidence_ids = [r.src_node_id for r in evidence_rows if r.src_node_id not in result_ids]
        if evidence_ids:
            ev_nodes = (
                db.query(AnalyticNode)
                .filter(AnalyticNode.node_id.in_(evidence_ids))
                .all()
            )
            for n in ev_nodes:
                node_meta[n.node_id] = n
            ev_proxy_rows = (
                db.query(NodeProxy.node_id, NodeProxy.etf_symbol)
                .filter(NodeProxy.node_id.in_(evidence_ids))
                .filter(NodeProxy.role == "primary")
                .all()
            )
            for r in ev_proxy_rows:
                primary_proxy[r.node_id] = r.etf_symbol
            result_ids.update(evidence_ids)

    out: List[Dict[str, Any]] = []
    for nid in result_ids:
        meta = node_meta.get(nid)
        if meta is None:
            continue
        proxy_sym = primary_proxy.get(nid)
        out.append({
            "id": nid,
            "label": meta.label,
            "sublabel": meta.sublabel or meta.label,
            "level": int(meta.level or 0),
            "node_type": meta.node_type,
            "proxy_etf": proxy_sym,
            "proxy_label": proxy_sym,
            "parent_id": parent_map.get(nid),
        })

    out.sort(key=lambda x: (x["level"], x["label"]))
    return out


# ============ 1. GET /api/tasks/{task_id}/nodes ============


@router.get("/{task_id}/nodes", response_model=List[Dict[str, Any]])
async def get_task_node_tree(
    task_id: int,
    response: Response,
    lens: Optional[str] = Query(
        None,
        description="视图: gics(分类) / chain(产业链) / hybrid(并集); 默认从 task.view_mode 兜底",
    ),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """返回任务的研究节点树 (含每个节点的实时分数)。

    Args:
        task_id: 任务 ID。
        lens: 视图; 缺省时回退到 task.view_mode, 仍缺省时为 'hybrid' (Task 4.12)。
        db: SQLAlchemy session。

    Returns:
        ResearchNode[] (深度遍历结果, 含 children); 字段语义见 README。
        计算结果未就绪的字段返回 null。

    Raises:
        HTTPException 404: task / root_node 不存在。
        HTTPException 400: lens 非法。
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    root_node_id, view_mode, max_depth = _resolve_task_node_config(task)
    resolved_lens = (lens or view_mode or "hybrid").strip().lower()
    if resolved_lens not in _VALID_LENS:
        raise HTTPException(
            status_code=400,
            detail=f"lens must be one of {_VALID_LENS}",
        )

    if not root_node_id:
        raise HTTPException(
            status_code=404,
            detail="Task has no resolvable root_node (run migration or set rootNode)",
        )

    if not _node_exists(db, root_node_id):
        raise HTTPException(status_code=404, detail=f"Node {root_node_id} not found")

    node_ids, child_map = _traverse_nodes(db, root_node_id, resolved_lens, max_depth)
    if not node_ids:
        node_ids = [root_node_id]

    score_results = batch_calculate_node_scores(node_ids, db)
    score_map: Dict[str, NodeScoreResult] = {r.node_id: r for r in score_results}

    response.headers["Cache-Control"] = f"max-age={_NODE_TREE_CACHE_SECONDS}"

    tree = _format_research_node(root_node_id, child_map, score_map, db)
    return [tree] if tree else []


# ============ 2. GET /api/tasks/{task_id}/nodes/{node_id}/holdings ============


@router.get(
    "/{task_id}/nodes/{node_id}/holdings",
    response_model=List[Dict[str, Any]],
)
async def get_node_holdings_endpoint(
    task_id: int,
    node_id: str,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """返回节点的成分股清单 + 节点级 RS / 收益 / 评分。

    Args:
        task_id: 任务 ID (用于校验 task 存在; 持仓本身与任务无关)。
        node_id: 节点业务主键。
        db: SQLAlchemy session。

    Returns:
        NodeHolding[] (按 score 降序; score 缺失时按 weight 降序)。
        rs20d 以"节点价格序列"为基准 (synthetic 走 NodePriceSeries, ETF proxy 走
        proxy ETF 的 PriceHistory), 不是 vs SPY。

    Raises:
        HTTPException 404: task / node 不存在。
    """
    if db.query(Task.id).filter(Task.id == task_id).first() is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not _node_exists(db, node_id):
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    holdings = get_node_holdings(node_id, db)
    if not holdings:
        return []

    node_prices = _load_node_close_series(db, node_id)
    node_closes = [c for _, c in node_prices]

    out: List[Dict[str, Any]] = []
    for holding in holdings:
        ticker = str(holding.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        out.append(_build_holding_entry(db, ticker, holding, node_closes))

    out.sort(
        key=lambda h: (
            h["score"] if h.get("score") is not None else -1.0,
            h.get("weight") or 0.0,
        ),
        reverse=True,
    )
    return out


# ============ 3. GET /api/tasks/{task_id}/nodes/{node_id}/trend-comparison ============


@router.get(
    "/{task_id}/nodes/{node_id}/trend-comparison",
    response_model=Dict[str, Any],
)
async def get_node_trend_comparison(
    task_id: int,
    node_id: str,
    period: int = Query(20, description="对比周期: 5/20/63"),
    metric: str = Query("relative", description="指标: relative/return20d/score"),
    label_tz: str = Query("beijing", description="日期标签时区"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """节点 vs 父节点 vs SPY 的走势对比 (与现有 /tasks/{id}/trend-comparison 同结构)。

    Args:
        task_id: 任务 ID。
        node_id: 节点业务主键。
        period: 对比交易日数。
        metric: relative (累计相对收益) / return20d / score。
        label_tz: 日期标签时区。
        db: SQLAlchemy session。

    Returns:
        {task_id, node_id, period, metric, label_tz, symbols, dates, series}.
        series 固定 3 条: [node, parent, SPY], 颜色固定。

    Raises:
        HTTPException 404: task / node 不存在。
        HTTPException 400: 参数非法。
    """
    if period not in _VALID_TREND_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"period must be one of {_VALID_TREND_PERIODS}",
        )
    if metric not in _VALID_TREND_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"metric must be one of {_VALID_TREND_METRICS}",
        )
    normalized_tz = (label_tz or "beijing").strip().lower()
    if normalized_tz not in _VALID_LABEL_TZ:
        raise HTTPException(
            status_code=400,
            detail=f"label_tz must be one of {_VALID_LABEL_TZ}",
        )

    if db.query(Task.id).filter(Task.id == task_id).first() is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not _node_exists(db, node_id):
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    parent_id = _find_classification_parent(db, node_id)
    symbols: List[str] = [node_id]
    if parent_id:
        symbols.append(parent_id)
    symbols.append(_BENCHMARK_SYMBOL)

    dates, series = _build_node_trend_series(
        db, symbols, period=period, metric=metric, label_tz=normalized_tz
    )

    color_map = _trend_color_map(node_id, parent_id)
    enriched_series = [
        {
            "symbol": entry["symbol"],
            "color": color_map.get(entry["symbol"], _COLOR_SPY),
            "values": entry["values"],
        }
        for entry in series
    ]

    return {
        "task_id": task_id,
        "node_id": node_id,
        "period": period,
        "metric": metric,
        "label_tz": normalized_tz,
        "symbols": symbols,
        "dates": dates,
        "series": enriched_series,
    }


# ============ 4. GET /api/tasks/{task_id}/nodes/chain-signals ============


@router.get(
    "/{task_id}/nodes/chain-signals",
    response_model=Dict[str, Any],
)
async def get_chain_signals(
    task_id: int,
    sector: Optional[str] = Query(
        None,
        description="板块标识（小写），如 'xlk'。缺省时从 task.root_node / task.sector 推断。",
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """计算产业链三维共振信号（上游共振 / 同层扩散 / 下游确认）。

    规则从 configs/chain_signals/<sector>.yaml 读取，节点分数从
    batch_calculate_node_scores 实时计算。

    Args:
        task_id: 任务 ID。
        sector: 板块标识；缺省时从 task.root_node 或 task.sector 推断（转小写）。
        db: SQLAlchemy session。

    Returns:
        {upstream, broad, downstream, label, color}。
        upstream/broad/downstream 为 bool；label/color 为综合信号字符串/色值。
        若板块无对应配置文件，返回 signals=null + warning 字段。

    Raises:
        HTTPException 404: task 不存在。
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    resolved_sector = _resolve_sector(task, sector)

    # 若无配置文件，优雅降级，不报 500
    try:
        rules = load_chain_signal_rules(resolved_sector)
    except FileNotFoundError:
        return {
            "signals": None,
            "warning": f"No chain signal config for sector '{resolved_sector}'. "
                       f"Create backend/app/configs/chain_signals/{resolved_sector}.yaml to enable.",
        }

    # 收集规则中所有关注节点，批量计算分数
    all_watched = (
        rules.upstream.watched_nodes
        + rules.broad.watched_nodes
        + rules.downstream.watched_nodes
    )
    unique_nodes = list(dict.fromkeys(all_watched))  # 去重保序

    score_results = batch_calculate_node_scores(unique_nodes, db)
    node_scores: Dict[str, float] = {
        r.node_id: float(r.total_score) for r in score_results
    }

    result: ChainSignalResult = compute_chain_signals(node_scores, rules)
    return {
        "upstream": result.upstream,
        "broad": result.broad,
        "downstream": result.downstream,
        "label": result.label,
        "color": result.color,
    }


# ============ 5. GET /api/tasks/{task_id}/nodes/chain-graph (Task DD-4) ============


@router.get(
    "/{task_id}/nodes/chain-graph",
    response_model=Dict[str, Any],
)
async def get_chain_graph(
    task_id: int,
    sector: Optional[str] = Query(
        None,
        description="板块标识（小写），如 'xlk'。缺省时从 task.root_node / task.sector 推断。",
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """产业链下钻视图后端：当前阶段只输出 StrategicPanel 4 卡所需的 strategy 字段。

    Args:
        task_id: 任务 ID。
        sector: 板块标识；缺省时从 task 推断。
        db: SQLAlchemy session。

    Returns:
        {strategy: {l1_ranking, breadth, confirmation, best_drill}}
        若该 sector 没有 strategy 配置，返回 {strategy: null, warning}。

    Raises:
        HTTPException 404: task 不存在。
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    resolved_sector = _resolve_sector(task, sector)
    try:
        config = load_chain_strategy_config(resolved_sector)
    except (FileNotFoundError, KeyError) as exc:
        return {
            "strategy": None,
            "warning": (
                f"No chain strategy config for sector '{resolved_sector}': {exc}. "
                f"Add a `strategy:` section to backend/app/configs/chain_signals/{resolved_sector}.yaml."
            ),
        }

    nodes_map, children_map = _collect_strategy_inputs(db, config)
    result = compute_chain_strategy(nodes_map, children_map, config)
    return {"strategy": _serialize_strategy(result)}


# ============ 6. GET /api/tasks/{task_id}/chain-graph (Task DD-10) ============
# 与 §5 不同：此端点直接吐出 chain_topology YAML 落库的拓扑（节点+边），
# 并把 chain_signals(DD-3) / chain_strategy(DD-4) 的输出一并返回，
# 用于前端「板块下钻」整图渲染（含坐标 / 角色 / 跨视图边）。


@router.get(
    "/{task_id}/chain-graph",
    response_model=Dict[str, Any],
)
async def get_task_chain_graph(
    task_id: int,
    sector: Optional[str] = Query(
        None,
        description="板块标识（小写）。缺省时从 task.root_node / task.sector 推断。",
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """返回某任务的产业链整图：nodes / edges / signals / strategy。

    Args:
        task_id: 任务 ID。
        sector: 板块标识；缺省时从 task 推断。
        db: SQLAlchemy session。

    Returns:
        {
            sector: 'xlk',
            nodes: [{node_id, role, tier, cx, cy, w, h, proxy, proxy_type, proxy_label}, ...],
            edges: [{src_node_id, dst_node_id, is_cross}, ...],
            signals: {upstream, broad, downstream, label, color} | null,
            strategy: {l1_ranking, breadth, confirmation, best_drill} | null,
        }

    Raises:
        HTTPException 404: task 不存在 / 该板块没有 chain_topology 拓扑。
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    resolved_sector = _resolve_sector(task, sector)

    nodes_payload, edges_payload = _load_chain_graph_for_sector(db, resolved_sector)
    if not nodes_payload:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No chain_topology loaded for sector '{resolved_sector}'. "
                f"Add backend/app/configs/chain_topology/{resolved_sector}.yaml "
                f"and restart, or run the loader explicitly."
            ),
        )

    signals_payload = _safe_compute_chain_signals(db, resolved_sector)
    strategy_payload = _safe_compute_chain_strategy(db, resolved_sector)

    return {
        "sector": resolved_sector,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "signals": signals_payload,
        "strategy": strategy_payload,
    }


def _load_chain_graph_for_sector(
    db: Session,
    sector: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """读取 chain_nodes / chain_edges 中指定板块的模板行（task_id IS NULL）。"""
    node_rows = (
        db.query(ChainNode)
        .filter(ChainNode.task_id.is_(None), ChainNode.sector == sector)
        .order_by(ChainNode.tier.is_(None), ChainNode.tier, ChainNode.id)
        .all()
    )
    edge_rows = (
        db.query(ChainEdge)
        .filter(ChainEdge.task_id.is_(None), ChainEdge.sector == sector)
        .order_by(ChainEdge.id)
        .all()
    )
    nodes_payload = [
        {
            "node_id": n.node_id,
            "role": n.role,
            "tier": n.tier,
            "cx": n.cx,
            "cy": n.cy,
            "w": n.w,
            "h": n.h,
            "proxy": n.proxy,
            "proxy_type": n.proxy_type,
            "proxy_label": n.proxy_label,
        }
        for n in node_rows
    ]
    edges_payload = [
        {
            "src_node_id": e.src_node_id,
            "dst_node_id": e.dst_node_id,
            "is_cross": bool(e.is_cross),
        }
        for e in edge_rows
    ]
    return nodes_payload, edges_payload


def _safe_compute_chain_signals(
    db: Session,
    sector: str,
) -> Optional[Dict[str, Any]]:
    """复用 DD-3 chain_signals 引擎；缺配置时返回 None（不阻断响应）。"""
    try:
        rules = load_chain_signal_rules(sector)
    except FileNotFoundError:
        return None

    watched = (
        rules.upstream.watched_nodes
        + rules.broad.watched_nodes
        + rules.downstream.watched_nodes
    )
    unique_nodes = list(dict.fromkeys(watched))
    score_results = batch_calculate_node_scores(unique_nodes, db)
    node_scores = {r.node_id: float(r.total_score) for r in score_results}

    res = compute_chain_signals(node_scores, rules)
    return {
        "upstream": res.upstream,
        "broad": res.broad,
        "downstream": res.downstream,
        "label": res.label,
        "color": res.color,
    }


def _safe_compute_chain_strategy(
    db: Session,
    sector: str,
) -> Optional[Dict[str, Any]]:
    """复用 DD-4 chain_strategy 引擎；缺配置时返回 None（不阻断响应）。"""
    try:
        config = load_chain_strategy_config(sector)
    except (FileNotFoundError, KeyError):
        return None
    nodes_map, children_map = _collect_strategy_inputs(db, config)
    result = compute_chain_strategy(nodes_map, children_map, config)
    return _serialize_strategy(result)


def _collect_strategy_inputs(
    db: Session,
    config: StrategyConfig,
) -> Tuple[Dict[str, StrategyNodeBrief], Dict[str, List[str]]]:
    """聚合 chain_strategy 所需的两个输入：节点 brief 字典 + 父子映射。

    节点 ID 集合 = l1 ∪ l1 的子节点 ∪ {equip,conn,compute} ∪ l2_drill_nodes。
    children_map 仅为 l1 节点查 classification/chain 子节点（与节点树同一 lens）。
    """
    seed_ids: List[str] = list(dict.fromkeys(
        [*config.l1_nodes, config.equip_node, config.conn_node,
         config.compute_node, *config.l2_drill_nodes]
    ))

    children_map: Dict[str, List[str]] = {}
    for parent_id in config.l1_nodes:
        child_ids = _query_chain_children(db, parent_id)
        children_map[parent_id] = child_ids
        seed_ids.extend(c for c in child_ids if c not in seed_ids)

    score_results = batch_calculate_node_scores(seed_ids, db)
    score_map = {r.node_id: r for r in score_results}

    meta_rows = (
        db.query(AnalyticNode)
        .filter(AnalyticNode.node_id.in_(seed_ids))
        .all()
    )
    meta_map = {n.node_id: n for n in meta_rows}

    nodes: Dict[str, StrategyNodeBrief] = {}
    for nid in seed_ids:
        meta = meta_map.get(nid)
        scored = score_map.get(nid)
        if meta is None and scored is None:
            continue
        label = (scored.label if scored else None) or (meta.label if meta else nid)
        sublabel = (meta.sublabel if meta and meta.sublabel else label)
        score_val = float(scored.total_score) if scored else 0.0
        delta5d = scored.delta5d if scored else None
        nodes[nid] = StrategyNodeBrief(
            id=nid,
            label=label,
            sublabel=sublabel,
            score=score_val,
            delta5d=delta5d,
        )
    return nodes, children_map


def _query_chain_children(db: Session, parent_id: str) -> List[str]:
    """取节点的 chain_parent / classification_parent 子节点（hybrid lens 同口径）。"""
    rows = (
        db.query(NodeEdge.dst_node_id)
        .filter(NodeEdge.src_node_id == parent_id)
        .filter(NodeEdge.edge_type.in_([
            NodeEdgeType.CHAIN_PARENT.value,
            NodeEdgeType.CLASSIFICATION_PARENT.value,
        ]))
        .all()
    )
    seen: Set[str] = set()
    out: List[str] = []
    for r in rows:
        cid = r[0]
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _serialize_brief(b: StrategyNodeBrief) -> Dict[str, Any]:
    return {
        "id": b.id,
        "label": b.label,
        "sublabel": b.sublabel,
        "score": round(b.score, 2),
        "delta5d": b.delta5d,
    }


def _serialize_strategy(r: ChainStrategyResult) -> Dict[str, Any]:
    return {
        "l1_ranking": [_serialize_brief(b) for b in r.l1_ranking],
        "breadth": {
            "label": r.breadth.label,
            "strong_count": r.breadth.strong_count,
            "total": r.breadth.total,
        },
        "confirmation": {
            "equip_score": round(r.confirmation.equip_score, 2),
            "conn_score": round(r.confirmation.conn_score, 2),
            "compute_score": round(r.confirmation.compute_score, 2),
            "compute_leading": r.confirmation.compute_leading,
            "message": r.confirmation.message,
        },
        "best_drill": _serialize_brief(r.best_drill) if r.best_drill else None,
    }


def _resolve_sector(task: Task, override: Optional[str]) -> str:
    """从 query param / root_node / sector 字段推断板块名（转小写）。"""
    if override:
        return override.strip().lower()
    root = (getattr(task, "root_node", None) or "").strip()
    if root:
        return root.lower()
    return (task.sector or "xlk").strip().lower()


# ============ 内部辅助: 任务配置解析 ============


def _resolve_task_node_config(task: Task) -> Tuple[Optional[str], str, int]:
    """从 task 取 (root_node, view_mode, max_depth); 旧任务 in-memory 兜底。

    旧任务 (root_node 为空) 用 sector 字段作为 root_node 兜底, 与
    migrate_drilldown_tasks_to_node_first 的映射一致, 但不写库。
    """
    root_node = (getattr(task, "root_node", None) or "").strip() or None
    if not root_node and task.sector:
        root_node = str(task.sector).strip().upper() or None
    # Task 4.12: 兜底由 'gics' 改 'hybrid', 让 semi 下的 chain 子节点默认可见
    view_mode = (getattr(task, "view_mode", None) or "hybrid").strip().lower()
    max_depth_val = getattr(task, "max_depth", None)
    try:
        max_depth = int(max_depth_val) if max_depth_val is not None else 3
    except (TypeError, ValueError):
        max_depth = 3
    return root_node, view_mode, max(0, max_depth)


def _node_exists(db: Session, node_id: str) -> bool:
    return (
        db.query(AnalyticNode.id)
        .filter(AnalyticNode.node_id == node_id)
        .first()
        is not None
    )


# ============ 内部辅助: 图遍历 ============


def _lens_edge_types(lens: str) -> List[str]:
    if lens == "gics":
        return [NodeEdgeType.CLASSIFICATION_PARENT.value]
    if lens == "chain":
        return [NodeEdgeType.CHAIN_PARENT.value]
    return [
        NodeEdgeType.CLASSIFICATION_PARENT.value,
        NodeEdgeType.CHAIN_PARENT.value,
    ]


def _traverse_nodes(
    db: Session,
    root_node_id: str,
    lens: str,
    max_depth: int,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """BFS 遍历 root 的所有后代; 返回 (节点列表, parent_id -> [child_id])。

    深度限制: max_depth (≤ 0 时只返回 root)。
    """
    edge_types = _lens_edge_types(lens)
    visited: Set[str] = {root_node_id}
    ordered: List[str] = [root_node_id]
    children_map: Dict[str, List[str]] = {}

    if max_depth <= 0:
        return ordered, children_map

    frontier: List[Tuple[str, int]] = [(root_node_id, 0)]
    while frontier:
        next_frontier: List[Tuple[str, int]] = []
        for parent_id, depth in frontier:
            if depth >= max_depth:
                continue
            child_rows = (
                db.query(NodeEdge.dst_node_id)
                .filter(NodeEdge.src_node_id == parent_id)
                .filter(NodeEdge.edge_type.in_(edge_types))
                .all()
            )
            child_ids = [c[0] for c in child_rows if c[0]]
            if not child_ids:
                continue
            for child_id in child_ids:
                if child_id in visited:
                    # 同一节点不重复挂载, 避免 hybrid lens 下成环
                    continue
                visited.add(child_id)
                ordered.append(child_id)
                children_map.setdefault(parent_id, []).append(child_id)
                next_frontier.append((child_id, depth + 1))
        frontier = next_frontier

    return ordered, children_map


def _find_classification_parent(db: Session, node_id: str) -> Optional[str]:
    edge = (
        db.query(NodeEdge.src_node_id)
        .filter(NodeEdge.dst_node_id == node_id)
        .filter(NodeEdge.edge_type == NodeEdgeType.CLASSIFICATION_PARENT.value)
        .first()
    )
    return edge[0] if edge else None


# ============ 内部辅助: ResearchNode 组装 ============


def _format_research_node(
    node_id: str,
    children_map: Dict[str, List[str]],
    score_map: Dict[str, NodeScoreResult],
    db: Session,
) -> Optional[Dict[str, Any]]:
    """递归把 NodeScoreResult 转成 ResearchNode JSON。

    没有 score 时仍输出节点骨架 (label / level 取自 AnalyticNode), 数值字段为 null。
    """
    score = score_map.get(node_id)
    if score is None:
        meta = (
            db.query(AnalyticNode)
            .filter(AnalyticNode.node_id == node_id)
            .first()
        )
        if meta is None:
            return None
        node_payload: Dict[str, Any] = {
            "id": node_id,
            "label": meta.label,
            "sublabel": meta.label,
            "level": int(meta.level or 0),
            "proxy": None,
            "proxyType": _PROXY_TYPE_FALLBACK,
            "proxyLabel": None,
            "score": None,
            "scoreVsParent": None,
            "contribution": None,
            "relStrength": _format_rs_string(None),
            "breadth": None,
            "delta3d": None,
            "delta5d": None,
        }
    else:
        proxy_type = (
            score.proxy_type if score.proxy_type in ("etf", "synthetic")
            else _PROXY_TYPE_FALLBACK
        )
        node_payload = {
            "id": score.node_id,
            "label": score.label,
            "sublabel": score.label,
            "level": int(score.level),
            "proxy": score.proxy_symbol,
            "proxyType": proxy_type,
            "proxyLabel": score.proxy_label,
            "score": float(score.total_score),
            "scoreVsParent": score.score_vs_parent,
            "contribution": score.contribution,
            "relStrength": _format_rs_string(score.rel_strength),
            "breadth": _round_or_none(score.breadth, 2),
            "delta3d": score.delta3d,
            "delta5d": score.delta5d,
        }

    children_payload: List[Dict[str, Any]] = []
    for child_id in children_map.get(node_id, []):
        child_node = _format_research_node(child_id, children_map, score_map, db)
        if child_node is not None:
            children_payload.append(child_node)
    node_payload["children"] = children_payload
    return node_payload


def _format_rs_string(rs_value: Optional[float]) -> str:
    """把 rel_strength (RS_20D_change, 单位 %) 格式化为 '+9.1%' / '-2.4%'。

    None / 数据不足 → 空串 (前端按需折叠显示)。
    """
    if rs_value is None:
        return ""
    sign = "+" if rs_value >= 0 else ""
    return f"{sign}{rs_value:.1f}%"


def _round_or_none(value: Optional[float], ndigits: int) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), ndigits)


# ============ 内部辅助: 持仓数据 ============


def _build_holding_entry(
    db: Session,
    ticker: str,
    holding: Dict[str, Any],
    node_closes: List[float],
) -> Dict[str, Any]:
    stock = db.query(Stock).filter(Stock.symbol == ticker).first()
    score_value: Optional[float] = None
    name: Optional[str] = None
    delta3d: Optional[float] = None
    delta5d: Optional[float] = None
    if stock is not None:
        score_value = (
            float(stock.score_total) if stock.score_total is not None else None
        )
        name = stock.name
        changes = stock.changes or {}
        if isinstance(changes, dict):
            delta3d = changes.get("delta3d")
            delta5d = changes.get("delta5d")

    stock_closes = _load_recent_closes(db, ticker, _TREND_PRICE_LIMIT)
    return20d = _compute_return_pct(stock_closes, _HOLDING_RS_WINDOW)
    rs20d = _compute_rs_change(stock_closes, node_closes, _HOLDING_RS_WINDOW)

    data_status = _resolve_holding_status(db, ticker)

    return {
        "ticker": ticker,
        "weight": float(holding.get("weight") or 0.0),
        "score": score_value,
        "name": name,
        "return20d": return20d,
        "rs20d": rs20d,
        "delta3d": delta3d if delta3d is not None else 0.0,
        "delta5d": delta5d if delta5d is not None else 0.0,
        "dataStatus": data_status,
    }


def _resolve_holding_status(db: Session, ticker: str) -> str:
    """finviz + iv 都齐 → 'complete'; 缺一 → 'pending'; 都缺 → 'missing'。"""
    from app.models import ImportedData, IVData  # 局部导入避免循环

    has_finviz = (
        db.query(ImportedData.id)
        .filter(ImportedData.symbol == ticker)
        .filter(ImportedData.source == "finviz")
        .first()
        is not None
    )
    has_iv = (
        db.query(IVData.id)
        .filter(IVData.symbol == ticker)
        .first()
        is not None
    )
    if has_finviz and has_iv:
        return "complete"
    if has_finviz or has_iv:
        return "pending"
    return "missing"


def _load_recent_closes(db: Session, symbol: str, limit: int) -> List[float]:
    rows = (
        db.query(PriceHistory.date, PriceHistory.close)
        .filter(PriceHistory.symbol == symbol.upper())
        .order_by(PriceHistory.date.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    return [float(c) for _, c in rows if c is not None]


def _compute_return_pct(closes: List[float], window: int) -> float:
    """近 window 个交易日累计收益 (decimal, 0.18 = +18%)。数据不足返回 0.0。"""
    if len(closes) <= window:
        return 0.0
    base = closes[-window - 1]
    if base <= 0:
        return 0.0
    return round((closes[-1] - base) / base, 4)


def _compute_rs_change(
    stock_closes: List[float],
    node_closes: List[float],
    window: int,
) -> float:
    """20D RS 变化 (单位: 百分点) — stock_return - node_return 的差值 × 100。

    任意一侧数据不足 → 0.0 (前端按 0 渲染)。
    """
    if len(stock_closes) <= window or len(node_closes) <= window:
        return 0.0
    s_now, s_then = stock_closes[-1], stock_closes[-window - 1]
    n_now, n_then = node_closes[-1], node_closes[-window - 1]
    if s_then <= 0 or n_then <= 0:
        return 0.0
    s_ret = (s_now - s_then) / s_then
    n_ret = (n_now - n_then) / n_then
    return round((s_ret - n_ret) * 100.0, 2)


# ============ 内部辅助: 节点价格序列 / 走势对比 ============


def _load_node_close_series(
    db: Session, node_id: str
) -> List[Tuple[date_t, float]]:
    """节点价格序列 (按日期升序); synthetic → NodePriceSeries, ETF proxy → PriceHistory。

    若两边都查不到, 返回空列表。
    """
    rows = (
        db.query(NodePriceSeries.date, NodePriceSeries.close)
        .filter(NodePriceSeries.node_id == node_id)
        .order_by(NodePriceSeries.date.asc())
        .all()
    )
    if rows:
        return [(d, float(c)) for d, c in rows if c is not None]

    # 退化: node_id 本身可能就是 ETF symbol (GICS 节点)
    rows = (
        db.query(PriceHistory.date, PriceHistory.close)
        .filter(PriceHistory.symbol == node_id.upper())
        .order_by(PriceHistory.date.asc())
        .all()
    )
    return [(d, float(c)) for d, c in rows if c is not None]


def _load_symbol_close_series(
    db: Session, symbol: str
) -> List[Tuple[date_t, float]]:
    rows = (
        db.query(PriceHistory.date, PriceHistory.close)
        .filter(PriceHistory.symbol == symbol.upper())
        .order_by(PriceHistory.date.asc())
        .all()
    )
    return [(d, float(c)) for d, c in rows if c is not None]


def _resolve_series_for_symbol(
    db: Session, symbol: str
) -> List[Tuple[date_t, float]]:
    """symbol 是节点 ID → 走 NodePriceSeries; 否则 (SPY/parent ETF) 走 PriceHistory。"""
    if _node_exists(db, symbol):
        return _load_node_close_series(db, symbol)
    return _load_symbol_close_series(db, symbol)


def _build_node_trend_series(
    db: Session,
    symbols: List[str],
    *,
    period: int,
    metric: str,
    label_tz: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """构造 trend-comparison 的 dates + series (兼容 node_id / ETF / SPY)。

    metric=score 暂不支持节点级 (ScoreSnapshot 写入但 build_metric_series 走 stock/etf
    类型映射), 统一退化为 relative。
    """
    series_data: Dict[str, Dict[date_t, float]] = {}
    for symbol in symbols:
        rows = _resolve_series_for_symbol(db, symbol)
        if len(rows) > _TREND_PRICE_LIMIT:
            rows = rows[-_TREND_PRICE_LIMIT:]
        series_data[symbol] = {d: c for d, c in rows}

    all_dates = sorted({d for data in series_data.values() for d in data.keys()})
    if metric == "return20d":
        if len(all_dates) > period + _HOLDING_RS_WINDOW:
            all_dates = all_dates[-(period + _HOLDING_RS_WINDOW):]
    if len(all_dates) > period:
        truncate_dates = all_dates[-period:]
    else:
        truncate_dates = list(all_dates)

    date_labels = _format_date_labels(truncate_dates, label_tz=label_tz)

    series: List[Dict[str, Any]] = []
    for symbol in symbols:
        data_map = series_data.get(symbol, {})
        if metric == "return20d":
            values = _series_return_window(data_map, truncate_dates, _HOLDING_RS_WINDOW)
        else:
            # relative / score (node 层无 score 序列, 退化 relative)
            values = _series_relative(data_map, truncate_dates)
        series.append({"symbol": symbol, "values": values})

    return date_labels, series


def _series_relative(
    data_map: Dict[date_t, float], dates: List[date_t]
) -> List[Optional[float]]:
    base_value: Optional[float] = None
    for d in dates:
        if d in data_map:
            base_value = data_map[d]
            break
    values: List[Optional[float]] = []
    for d in dates:
        close = data_map.get(d)
        if base_value is None or close is None or base_value == 0:
            values.append(None)
        else:
            values.append(round((close - base_value) / base_value * 100.0, 2))
    return values


def _series_return_window(
    data_map: Dict[date_t, float],
    dates: List[date_t],
    window: int,
) -> List[Optional[float]]:
    """rolling window return (%); 不足窗口返回 None。"""
    sorted_items = sorted(data_map.items())
    if len(sorted_items) <= window:
        return [None for _ in dates]
    by_date = {d: idx for idx, (d, _) in enumerate(sorted_items)}
    closes = [c for _, c in sorted_items]

    values: List[Optional[float]] = []
    for d in dates:
        idx = by_date.get(d)
        if idx is None or idx < window:
            values.append(None)
            continue
        base = closes[idx - window]
        if base == 0:
            values.append(None)
            continue
        values.append(round((closes[idx] - base) / base * 100.0, 2))
    return values


def _trend_color_map(node_id: str, parent_id: Optional[str]) -> Dict[str, str]:
    out = {node_id: _COLOR_NODE, _BENCHMARK_SYMBOL: _COLOR_SPY}
    if parent_id:
        out[parent_id] = _COLOR_PARENT
    return out
