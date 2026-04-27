/**
 * DrilldownView — Phase 4 三栏骨架。
 *
 * 职责：
 *  - 拉取节点树 / 当前节点持仓 / 趋势序列（React Query）
 *  - 维护选中节点、展开集合、趋势 period/metric、显示开关
 *  - localStorage 持久化 selectedNodeId（每个 task 独立 key）
 *
 * 不做：
 *  - 具体 NodeTree / 中栏内容 / NodeDetailPanel 的 UI 实现（留给 Task 4.8 / 4.9 / 4.10）
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as api from '../../services/api';
import type {
  Task,
  ResearchNode,
  NodeTrendPeriod,
  NodeTrendMetric,
  TaskViewMode,
} from '../../types';

interface DrilldownViewProps {
  task: Task;
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

export function DrilldownView({ task, onViewStockDetail: _onViewStockDetail }: DrilldownViewProps) {
  // _onViewStockDetail 由 Task 4.10 NodeDetailPanel 使用，这里保留 prop 接通点。
  void _onViewStockDetail;

  const [lens, _setLens] = useState<TaskViewMode>('gics');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [_expandedIds, _setExpandedIds] = useState<Set<string>>(new Set());
  const [trendPeriod, _setTrendPeriod] = useState<NodeTrendPeriod>('20d');
  const [trendMetric, _setTrendMetric] = useState<NodeTrendMetric>('relative');
  const [_showAllHoldings, _setShowAllHoldings] = useState<boolean>(false);

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

  const { data: nodeTree } = useQuery({
    queryKey: api.drilldownQueryKeys.nodeTree(task.id, lens),
    queryFn: () => api.getTaskNodeTree(task.id, lens),
    staleTime: TREE_STALE_MS,
  });

  const allNodes = useMemo<ResearchNode[]>(
    () => (nodeTree ? flattenTree(nodeTree) : []),
    [nodeTree]
  );
  const selectedNode = useMemo<ResearchNode | null>(
    () => allNodes.find((n) => n.id === selectedNodeId) ?? allNodes[0] ?? null,
    [allNodes, selectedNodeId]
  );

  // Holdings for selected node
  useQuery({
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
  useQuery({
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
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* LEFT 280 — Task 4.8 NodeTree */}
      <aside
        style={{
          width: 280,
          flexShrink: 0,
          borderRight: '1px solid #e2e8f0',
          background: '#fff',
        }}
      >
        <div style={{ padding: 16, fontSize: 12, color: '#64748b' }}>
          NodeTree (Task 4.8)
        </div>
      </aside>

      {/* CENTER flex — Task 4.9 regime / trend / matrix / holdings / data-source */}
      <main
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px 20px',
          background: '#f8fafc',
        }}
      >
        <div style={{ fontSize: 12, color: '#64748b' }}>
          Center (Task 4.9). Selected: {selectedNode?.label ?? '—'}
        </div>
      </main>

      {/* RIGHT 300 — Task 4.10 NodeDetailPanel */}
      <aside
        style={{
          width: 300,
          flexShrink: 0,
          borderLeft: '1px solid #e2e8f0',
          background: '#f8fafc',
        }}
      >
        <div style={{ padding: 16, fontSize: 12, color: '#64748b' }}>
          NodeDetailPanel (Task 4.10)
        </div>
      </aside>
    </div>
  );
}
