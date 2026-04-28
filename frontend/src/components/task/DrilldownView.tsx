/**
 * DrilldownView — Phase 4 三栏布局（Task 4.9 中栏装配完成）。
 *
 * 职责：
 *  - 拉取节点树 / 当前节点持仓 / 趋势序列（React Query）
 *  - 维护选中节点、展开集合、趋势 period/metric、显示开关
 *  - localStorage 持久化 selectedNodeId（每个 task 独立 key）
 *
 * 不做：
 *  - NodeDetailPanel 的 UI 实现（留给 Task 4.10）
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as api from '../../services/api';
import type {
  Task,
  ResearchNode,
  NodeTrendPeriod,
  NodeTrendMetric,
  TaskViewMode,
} from '../../types';
import { NodeTree } from './NodeTree';
import { RegimeBadge } from './RegimeBadge';
import { NodeTrendChart } from './NodeTrendChart';
import { NodeMatrix } from './NodeMatrix';
import { NodeHoldingsTable } from './NodeHoldingsTable';
import { DataSourceBar } from './DataSourceBar';
import { NodeDetailPanel } from './NodeDetailPanel';

interface DrilldownViewProps {
  task: Task;
  onBack?: () => void;
  onViewStockDetail?: (ticker: string) => void;
}

// localStorage key 命名见 README §State Management
const lsKey = (taskId: number): string => `drilldown-selected-node-${taskId}`;

const TREE_STALE_MS = 5 * 60 * 1000;
const NODE_DATA_STALE_MS = 60 * 1000;

function flattenTree(nodes: ResearchNode[]): ResearchNode[] {
  const out: ResearchNode[] = [];
  const walk = (ns: ResearchNode[]): void => {
    for (const n of ns) {
      out.push(n);
      if (n.children?.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

// Task 4.12: 给定目标 nodeId, 返回从 root 到 target 的祖先 ID 链 (含 target).
// 找不到返回空数组. 用于 selectedNodeId 复位后自动展开整条路径.
function findPathToNode(
  nodes: ResearchNode[],
  targetId: string
): string[] {
  for (const node of nodes) {
    if (node.id === targetId) return [node.id];
    if (node.children?.length) {
      const sub = findPathToNode(node.children, targetId);
      if (sub.length > 0) return [node.id, ...sub];
    }
  }
  return [];
}

export function DrilldownView({ task, onBack, onViewStockDetail }: DrilldownViewProps) {
  const [lens, setLens] = useState<TaskViewMode>('hybrid');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [trendPeriod, setTrendPeriod] = useState<NodeTrendPeriod>('20d');
  const [trendMetric, setTrendMetric] = useState<NodeTrendMetric>('relative');
  const [showAllHoldings, setShowAllHoldings] = useState<boolean>(false);

  const handleSelect = useCallback((node: ResearchNode) => {
    setSelectedNodeId(node.id);
  }, []);

  // Reset expansion state on lens change so auto-expand logic runs fresh for the new tree.
  const handleLensChange = useCallback((newLens: TaskViewMode) => {
    setLens(newLens);
    setExpandedIds(new Set());
  }, []);

  const handleToggleExpand = useCallback((nodeId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  // Restore selection from localStorage
  useEffect(() => {
    const saved = localStorage.getItem(lsKey(task.id));
    if (saved) setSelectedNodeId(saved);
  }, [task.id]);

  // Persist selection
  useEffect(() => {
    if (selectedNodeId) {
      localStorage.setItem(lsKey(task.id), selectedNodeId);
    }
  }, [task.id, selectedNodeId]);

  const { data: nodeTree, isLoading: treeLoading } = useQuery({
    queryKey: api.drilldownQueryKeys.nodeTree(task.id, lens),
    queryFn: () => api.getTaskNodeTree(task.id, lens),
    staleTime: TREE_STALE_MS,
  });

  // Task 4.12: 兜底 — localStorage 里的 selectedNodeId 在最新 nodeTree 中找不到时,
  // 回退到 root.id; 否则会卡在 selectedNode=null, 中右栏全空.
  useEffect(() => {
    if (!nodeTree || nodeTree.length === 0 || !selectedNodeId) return;
    const flat = flattenTree(nodeTree);
    const exists = flat.some((n) => n.id === selectedNodeId);
    if (!exists) {
      setSelectedNodeId(nodeTree[0].id);
    }
  }, [nodeTree, selectedNodeId]);

  const allNodes = useMemo<ResearchNode[]>(
    () => (nodeTree ? flattenTree(nodeTree) : []),
    [nodeTree]
  );
  const selectedNode = useMemo<ResearchNode | null>(
    () => allNodes.find((n) => n.id === selectedNodeId) ?? allNodes[0] ?? null,
    [allNodes, selectedNodeId]
  );

  // Task 4.12: 树加载或 selectedNodeId 变化时, 把从 root 到 selectedNode 的整条
  // 路径展开. 只加不删, 保留用户手动折叠的兄弟分支. 首次加载 (prev.size===0) 额外
  // 展开 root 的直接子节点, 让 NodeTree 一进入就有视觉层次.
  useEffect(() => {
    if (!nodeTree || nodeTree.length === 0) return;
    setExpandedIds((prev) => {
      const next = new Set(prev);
      const root = nodeTree[0];
      next.add(root.id);
      if (selectedNodeId) {
        const path = findPathToNode(nodeTree, selectedNodeId);
        for (const id of path) next.add(id);
      }
      if (prev.size === 0) {
        for (const c of root.children ?? []) next.add(c.id);
      }
      return next;
    });
  }, [nodeTree, selectedNodeId]);

  // Holdings for selected node
  const { data: holdings = [] } = useQuery({
    queryKey: selectedNode
      ? api.drilldownQueryKeys.nodeHoldings(task.id, selectedNode.id)
      : ['node-holdings-noop'],
    queryFn: () =>
      selectedNode
        ? api.getNodeHoldings(task.id, selectedNode.id)
        : Promise.resolve([]),
    enabled: !!selectedNode,
    staleTime: NODE_DATA_STALE_MS,
  });

  // Trend series for selected node
  const { data: trendData } = useQuery({
    queryKey: selectedNode
      ? api.drilldownQueryKeys.nodeTrend(task.id, selectedNode.id, trendPeriod, trendMetric)
      : ['node-trend-noop'],
    queryFn: () =>
      selectedNode
        ? api.getNodeTrendSeries(task.id, selectedNode.id, trendPeriod, trendMetric)
        : null,
    enabled: !!selectedNode,
    staleTime: NODE_DATA_STALE_MS,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Drilldown breadcrumb bar — sits below the global app header */}
      <div
        style={{
          height: 44,
          flexShrink: 0,
          background: 'linear-gradient(to right, #f8fafc, #eff6ff, #f8fafc)',
          borderBottom: '1px solid #e2e8f0',
          padding: '0 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 13, color: '#94a3b8', whiteSpace: 'nowrap' }}>监控任务</span>
          <span style={{ color: '#cbd5e1', fontSize: 14 }}>›</span>
          <span
            style={{
              fontSize: 13,
              color: '#64748b',
              maxWidth: 200,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {task.title}
          </span>
          <span style={{ color: '#cbd5e1', fontSize: 14 }}>›</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#2563eb', whiteSpace: 'nowrap' }}>
            板块内下钻
          </span>
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          <button
            onClick={onBack}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '5px 12px',
              borderRadius: 6,
              border: '1px solid #e2e8f0',
              background: '#fff',
              fontSize: 13,
              color: '#475569',
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            刷新全部
          </button>
          <button
            style={{
              padding: '5px 12px',
              borderRadius: 6,
              background: 'linear-gradient(to right,#2563eb,#4f46e5)',
              color: '#fff',
              border: 'none',
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            + 添加 ETF
          </button>
        </div>
      </div>

      {/* Three-column area */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* LEFT 280 — NodeTree */}
        <NodeTree
          nodes={nodeTree ?? []}
          selectedNodeId={selectedNode?.id ?? null}
          expandedIds={expandedIds}
          lens={lens}
          onSelect={handleSelect}
          onToggleExpand={handleToggleExpand}
          onLensChange={handleLensChange}
          totalNodeCount={allNodes.length}
          isLoading={treeLoading}
        />

        {/* CENTER flex — Regime / Trend / Matrix / Holdings / DataSource */}
        <main
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px 20px',
            background: '#f8fafc',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <RegimeBadge />
            {selectedNode && (
              <>
                <NodeTrendChart
                  selectedNode={selectedNode}
                  data={trendData ?? null}
                  period={trendPeriod}
                  metric={trendMetric}
                  onPeriodChange={setTrendPeriod}
                  onMetricChange={setTrendMetric}
                  isLoading={false}
                />
                {(selectedNode.children?.length ?? 0) > 0 && (
                  <NodeMatrix
                    selectedNode={selectedNode}
                    onSelectChild={(child) => {
                      setSelectedNodeId(child.id);
                      setExpandedIds((prev) => new Set([...prev, selectedNode.id, child.id]));
                    }}
                  />
                )}
                <NodeHoldingsTable
                  holdings={holdings}
                  showAll={showAllHoldings}
                  onShowAll={() => setShowAllHoldings(true)}
                  onRowClick={onViewStockDetail}
                  isLoading={false}
                  nodeProxyType={selectedNode.proxyType}
                  nodeProxy={selectedNode.proxy}
                  nodeProxyLabel={selectedNode.proxyLabel}
                />
                <DataSourceBar
                  sourceUpdatedAt={task.updatedAt ? {
                    finviz: task.updatedAt,
                    marketchameleon: task.updatedAt,
                    ibkr: task.updatedAt,
                    futu: task.updatedAt,
                  } : undefined}
                />
              </>
            )}
          </div>
        </main>

        {/* RIGHT 300 — NodeDetailPanel */}
        <aside
          style={{
            width: 300,
            flexShrink: 0,
            borderLeft: '1px solid #e2e8f0',
            background: '#f8fafc',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {selectedNode && (
            <NodeDetailPanel
              selectedNode={selectedNode}
              allNodes={allNodes}
              holdings={holdings}
              onSelectNode={(n) => setSelectedNodeId(n.id)}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
