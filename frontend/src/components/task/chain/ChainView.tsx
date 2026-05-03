/**
 * ChainView — 产业链 lens 独立双栏视图（Phase 4 DD-2 / DD-8）。
 *
 * 职责：lens==='chain' 时替换 DrilldownView 的三列区域，
 * 渲染左侧全幅 SVG 画布（含顶栏工具条 + ChainSignalBar + 底栏图例）
 * 与右侧 380px StrategicPanel。
 *
 * 不做：数据拉取、lens 切换管理（由 DrilldownView 负责）。
 * 禁止：直接操作 selectedNodeId 字符串；统一通过 onSelectNode 回调。
 */
import React from 'react';
import type {
  Task,
  ResearchNode,
  NodeHolding,
  TaskChainGraphResponse,
  ChainSignalResult,
  ChainStrategyResult,
  NodeTrendPeriod,
} from '../../../types';
import { ChainGraph } from './ChainGraph';
import { StrategicPanel } from './StrategicPanel';
import { ChainSignalBar } from '../ChainSignalBar';

export interface ChainViewProps {
  task: Task;
  selectedNode: ResearchNode | null;
  allNodes: ResearchNode[];
  holdings: NodeHolding[];
  chainGraph: TaskChainGraphResponse | null;
  chainSignals: ChainSignalResult | null;
  chainStrategy: ChainStrategyResult | null;
  period: NodeTrendPeriod;
  onSelectNode: (node: ResearchNode) => void;
  onPeriodChange: (period: NodeTrendPeriod) => void;
  onBackToGics: () => void;
}

export function ChainView({
  task,
  selectedNode,
  allNodes,
  holdings,
  chainGraph,
  chainSignals,
  chainStrategy,
  onSelectNode,
  onBackToGics,
}: ChainViewProps): React.ReactElement {
  const sectorLabel = task.sector ?? allNodes[0]?.label ?? '产业链';

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', height: '100%' }}>
      {/* LEFT — full-width SVG canvas area */}
      <div style={{
        flex: 3,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        borderRight: '1px solid #e2e8f0',
        background: '#f8fafc',
      }}>
        {/* Top toolbar: back button + title + ChainSignalBar */}
        <div style={{
          height: 48,
          flexShrink: 0,
          background: '#fff',
          borderBottom: '1px solid #e2e8f0',
          padding: '0 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}>
          <button
            onClick={onBackToGics}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '5px 12px',
              borderRadius: 8,
              border: '1px solid #e2e8f0',
              background: '#fff',
              fontSize: 12,
              color: '#475569',
              cursor: 'pointer',
              fontFamily: 'inherit',
              flexShrink: 0,
            }}
          >
            ← GICS 分类视图
          </button>
          <span style={{
            fontSize: 13,
            fontWeight: 700,
            color: '#1e293b',
            flexShrink: 0,
          }}>
            {sectorLabel} 产业链图
          </span>
          <ChainSignalBar signals={chainSignals} />
        </div>

        {/* ChainGraph SVG — fills remaining height */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <ChainGraph
            chainGraph={chainGraph}
            allNodes={allNodes}
            selectedNodeId={selectedNode?.id ?? null}
            onSelect={onSelectNode}
          />
        </div>
      </div>

      {/* RIGHT 380 — StrategicPanel */}
      <div style={{
        width: 380,
        flexShrink: 0,
        overflowY: 'auto',
        padding: 12,
        background: '#f8fafc',
      }}>
        {selectedNode && chainStrategy ? (
          <StrategicPanel
            strategy={chainStrategy}
            allNodes={allNodes}
            selectedNode={selectedNode}
            holdings={holdings}
            onSelectNode={onSelectNode}
          />
        ) : (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            fontSize: 12,
            color: '#94a3b8',
          }}>
            {chainStrategy ? '请选择节点' : '加载策略数据中…'}
          </div>
        )}
      </div>
    </div>
  );
}
