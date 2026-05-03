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
import { ChainSignalBar } from './ChainSignalBar';
import { StrategicPanel } from './chain/StrategicPanel';
import { ChainGraph } from './chain/ChainGraph';

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

  // Chain signals — only fetched when lens=chain (DD-8)
  const { data: chainSignals = null } = useQuery({
    queryKey: api.drilldownQueryKeys.chainSignals(task.id),
    queryFn: () => api.getChainSignals(task.id),
    enabled: lens === 'chain',
    staleTime: TREE_STALE_MS,
  });

  // Chain strategy (StrategicPanel data) — only fetched when lens=chain (DD-4)
  const { data: chainStrategy = null } = useQuery({
    queryKey: api.drilldownQueryKeys.chainGraph(task.id),
    queryFn: () => api.getChainGraph(task.id),
    enabled: lens === 'chain',
    staleTime: TREE_STALE_MS,
  });

  // Chain topology graph (DD-7) — nodes with coords + edges for ChainGraph SVG
  const { data: taskChainGraph = null } = useQuery({
    queryKey: api.drilldownQueryKeys.taskChainGraph(task.id),
    queryFn: () => api.getTaskChainGraph(task.id),
    enabled: lens === 'chain',
    staleTime: TREE_STALE_MS,
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
    /*
     * Integrates with MainLayout's global header — no fixed overlay.
     * Height: 100vh minus global header offset (p-4=16 + header=80 + mb-6=24 = 120px) + 4px buffer.
     * Negative margin breaks out of the container's 16px horizontal padding for full-width columns.
     */
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: 'calc(100vh - 124px)',
      overflow: 'hidden',
      margin: '0 -16px',
      width: 'calc(100% + 32px)',
    }}>
      {/* Breadcrumb sub-header — 48px, matches CoreTerminal's section-header style */}
      <div style={{
        height: 48,
        flexShrink: 0,
        background: '#fff',
        borderBottom: '1px solid #e2e8f0',
        padding: '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, color: '#94a3b8' }}>监控任务</span>
          <span style={{ color: '#cbd5e1', fontSize: 14 }}>›</span>
          <span style={{
            fontSize: 13, color: '#475569',
            maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {task.title}
          </span>
          <span style={{ color: '#cbd5e1', fontSize: 14 }}>›</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#2563eb', whiteSpace: 'nowrap' }}>
            板块内下钻
          </span>
        </div>

        {lens === 'chain' && <ChainSignalBar signals={chainSignals} />}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={onBack}
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '6px 14px', borderRadius: 8,
              border: '1px solid #e2e8f0', background: '#fff',
              fontSize: 13, color: '#475569', cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            ← 返回列表
          </button>
          <button
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '6px 14px', borderRadius: 8,
              border: '1px solid #e2e8f0', background: '#fff',
              fontSize: 13, color: '#475569', cursor: 'pointer', fontFamily: 'inherit',
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
              padding: '6px 14px', borderRadius: 8,
              background: 'linear-gradient(to right,#2563eb,#4f46e5)',
              color: '#fff', border: 'none',
              fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
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

        {/* CENTER flex — chain lens: ChainGraph SVG; other lenses: Trend/Matrix/Holdings */}
        <main
          style={{
            flex: 1,
            overflowY: lens === 'chain' ? 'hidden' : 'auto',
            padding: lens === 'chain' ? 0 : '16px 20px',
            background: '#f8fafc',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {lens === 'chain' ? (
            <ChainGraph
              chainGraph={taskChainGraph}
              allNodes={allNodes}
              selectedNodeId={selectedNodeId}
              onSelect={handleSelect}
            />
          ) : (
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
          )}
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
            lens === 'chain' && chainStrategy ? (
              <div style={{ overflowY: 'auto', padding: 12 }}>
                <StrategicPanel
                  strategy={chainStrategy}
                  allNodes={allNodes}
                  selectedNode={selectedNode}
                  holdings={holdings}
                  onSelectNode={(n) => setSelectedNodeId(n.id)}
                />
              </div>
            ) : (
              <NodeDetailPanel
                selectedNode={selectedNode}
                allNodes={allNodes}
                holdings={holdings}
                onSelectNode={(n) => setSelectedNodeId(n.id)}
              />
            )
          )}
        </aside>
      </div>
    </div>
  );
}
