/**
 * StrategicPanel — 产业链下钻策略面板（Task DD-4）。
 *
 * 职责：渲染右栏 4 张卡片（Q1 L1 排名 / Q2 广度 / Q3 上下游确认 / Q4 推荐下钻），
 * 卡片底部嵌入已有 NodeDetailPanel 显示当前 selectedNode 详情。
 * 数据由 DrilldownView 通过 props 注入；本组件不发请求、不维护选中态。
 *
 * 样式严格对齐 docs/design/drilldown-upgrade.html L757-908。
 */
import React from 'react';
import type {
  ChainStrategyResult,
  StrategyNodeBrief,
  ResearchNode,
  NodeHolding,
} from '../../../types';
import { NodeDetailPanel } from '../NodeDetailPanel';

// ─── 设计令牌（来自 HTML L749-752 / L782-785） ─────────────────────────────

interface ScoreTier {
  border: string;
  bg: string;
  text: string;
}

function scoreTierStyle(score: number): ScoreTier {
  if (score >= 85) return { border: '#059669', bg: 'rgba(5,150,105,0.07)',  text: '#059669' };
  if (score >= 70) return { border: '#3b82f6', bg: 'rgba(59,130,246,0.07)', text: '#2563eb' };
  if (score >= 60) return { border: '#d97706', bg: 'rgba(217,119,6,0.07)',  text: '#d97706' };
  return              { border: '#cbd5e1', bg: 'rgba(148,163,184,0.05)', text: '#64748b' };
}

const BREADTH_COLOR: Record<string, string> = {
  '全面扩散': '#059669',
  '主线驱动': '#2563eb',
  '单点拉动': '#d97706',
};

const CARD_STYLE: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 14,
  padding: '12px 14px',
};

const CARD_TITLE_STYLE: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#94a3b8',
  marginBottom: 10,
  display: 'flex',
  alignItems: 'center',
  gap: 6,
};

// ─── 子组件 ────────────────────────────────────────────────────────────────

function QBadge({ n }: { n: 1 | 2 | 3 | 4 }): React.ReactElement {
  return (
    <span style={{
      background: '#f1f5f9',
      color: '#475569',
      width: 18,
      height: 18,
      borderRadius: 5,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 10,
      fontWeight: 700,
      flexShrink: 0,
    }}>
      Q{n}
    </span>
  );
}

interface CardProps {
  strategy: ChainStrategyResult;
  onSelectNode: (briefId: string) => void;
}

function HeaderCard({ topL1Label }: { topL1Label: string }): React.ReactElement {
  return (
    <div style={{
      padding: '12px 16px',
      background: 'linear-gradient(135deg,#f8fafc,#eff6ff)',
      borderRadius: 14,
      border: '1px solid #e2e8f0',
    }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#1e293b', marginBottom: 3 }}>
        下钻策略分析
      </div>
      <div style={{ fontSize: 11, color: '#64748b' }}>
        基于 {topL1Label} 当前动能结构自动计算
      </div>
    </div>
  );
}

function L1RankingCard({ strategy, onSelectNode }: CardProps): React.ReactElement {
  const ranking = strategy.l1_ranking;
  return (
    <div style={CARD_STYLE}>
      <div style={CARD_TITLE_STYLE}><QBadge n={1} /> 一级节点谁最强？</div>
      {ranking.map((node, i) => {
        const tier = scoreTierStyle(node.score);
        const isLast = i === ranking.length - 1;
        return (
          <div
            key={node.id}
            onClick={() => onSelectNode(node.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginBottom: isLast ? 0 : 8,
              cursor: 'pointer',
            }}
          >
            <span style={{ fontSize: 11, color: '#94a3b8', width: 16, fontWeight: 700 }}>
              #{i + 1}
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: '#1e293b' }}>{node.label}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: tier.text }}>
                  {node.score.toFixed(1)}
                </span>
              </div>
              <div style={{ height: 4, background: '#f1f5f9', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${Math.max(0, Math.min(100, node.score))}%`,
                  background: tier.border,
                  borderRadius: 2,
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface BreadthCardProps extends CardProps {
  topL1Label: string;
  /** Top L1 node's children rendered as score chips (passed via parent for label/score). */
  topL1Children: StrategyNodeBrief[];
}

function BreadthCard({
  strategy,
  topL1Label,
  topL1Children,
  onSelectNode,
}: BreadthCardProps): React.ReactElement {
  const { label, strong_count, total } = strategy.breadth;
  const color = BREADTH_COLOR[label] ?? '#64748b';
  return (
    <div style={CARD_STYLE}>
      <div style={CARD_TITLE_STYLE}>
        <QBadge n={2} /> {topL1Label} 内部广还是窄？
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 16, fontWeight: 800, color }}>{label}</span>
        <span style={{ fontSize: 11, color: '#64748b' }}>
          {strong_count}/{total} 个子节点 &gt;75分
        </span>
      </div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {topL1Children.map((c) => {
          const strong = c.score > 75;
          return (
            <div
              key={c.id}
              onClick={() => onSelectNode(c.id)}
              style={{
                padding: '3px 9px',
                borderRadius: 20,
                fontSize: 11,
                cursor: 'pointer',
                background: strong ? 'rgba(5,150,105,0.08)' : 'rgba(148,163,184,0.08)',
                border: `1px solid ${strong ? 'rgba(5,150,105,0.25)' : '#e2e8f0'}`,
                color: strong ? '#059669' : '#94a3b8',
                fontWeight: 500,
              }}
            >
              {c.label} <span style={{ fontWeight: 700 }}>{c.score.toFixed(0)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ConfirmationCard({ strategy }: CardProps): React.ReactElement {
  const { equip_score, conn_score, compute_leading, message } = strategy.confirmation;
  const items = [
    { label: '上游设备', score: equip_score, ok: equip_score > 70 },
    { label: '高速互联', score: conn_score,  ok: conn_score > 70 },
  ];
  return (
    <div style={CARD_STYLE}>
      <div style={CARD_TITLE_STYLE}><QBadge n={3} /> 上下游是否开始确认？</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((item) => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 66, display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
              <span style={{
                fontSize: 11,
                color: item.ok ? '#059669' : '#d97706',
                fontWeight: 700,
              }}>
                {item.ok ? '✓' : '○'}
              </span>
              <span style={{ fontSize: 11, color: '#475569' }}>{item.label}</span>
            </div>
            <div style={{
              flex: 1, height: 4, background: '#f1f5f9',
              borderRadius: 2, overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${Math.max(0, Math.min(100, item.score))}%`,
                background: item.ok ? '#22c55e' : '#f59e0b',
                borderRadius: 2,
              }} />
            </div>
            <span style={{
              fontSize: 11, fontWeight: 700,
              color: item.ok ? '#059669' : '#d97706',
              minWidth: 24, textAlign: 'right', flexShrink: 0,
            }}>
              {item.score.toFixed(0)}
            </span>
          </div>
        ))}
        <div style={{
          marginTop: 2,
          padding: '7px 10px',
          borderRadius: 8,
          fontSize: 11,
          lineHeight: 1.5,
          background: compute_leading ? 'rgba(37,99,235,0.06)' : 'rgba(5,150,105,0.06)',
          color: compute_leading ? '#2563eb' : '#059669',
          border: `1px solid ${compute_leading ? 'rgba(59,130,246,0.15)' : 'rgba(5,150,105,0.15)'}`,
        }}>
          {message}
        </div>
      </div>
    </div>
  );
}

function BestDrillCard({ strategy, onSelectNode }: CardProps): React.ReactElement | null {
  const drill = strategy.best_drill;
  return (
    <div style={CARD_STYLE}>
      <div style={CARD_TITLE_STYLE}><QBadge n={4} /> 建议下钻方向？</div>
      {drill ? (
        <div
          onClick={() => onSelectNode(drill.id)}
          style={{
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 12px',
            borderRadius: 10,
            background: 'rgba(37,99,235,0.05)',
            border: '1px solid rgba(59,130,246,0.2)',
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>{drill.label}</div>
            <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>{drill.sublabel}</div>
          </div>
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#22c55e' }}>
              5D {drill.delta5d !== null && drill.delta5d > 0 ? '+' : ''}
              {drill.delta5d !== null ? drill.delta5d.toFixed(1) : '--'}
            </div>
            <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 1 }}>动能最强</div>
          </div>
          <span style={{ color: '#3b82f6', fontSize: 16, marginLeft: 4 }}>→</span>
        </div>
      ) : (
        <div style={{ fontSize: 11, color: '#94a3b8', padding: '8px 4px' }}>
          暂无可推荐节点（候选节点均缺数据）
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ────────────────────────────────────────────────────────────────

export interface StrategicPanelProps {
  strategy: ChainStrategyResult;
  /** 用于在 Q2 展示 top L1 子节点；通常来自 nodeTree 的 flatten 结果。 */
  allNodes: ResearchNode[];
  /** 当前选中节点；用于底部 NodeDetailPanel。 */
  selectedNode: ResearchNode | null;
  /** 当前节点持仓，传给 NodeDetailPanel。 */
  holdings: NodeHolding[];
  /** 卡片项点击 / 底部 NodeDetailPanel 切换均触发此回调。 */
  onSelectNode: (node: ResearchNode) => void;
}

export function StrategicPanel({
  strategy,
  allNodes,
  selectedNode,
  holdings,
  onSelectNode,
}: StrategicPanelProps): React.ReactElement {
  // selectById：把卡片返回的 node id 解析为完整 ResearchNode 后回调
  const selectById = (nodeId: string): void => {
    const target = allNodes.find((n) => n.id === nodeId);
    if (target) onSelectNode(target);
  };

  const topL1 = strategy.l1_ranking[0] ?? null;
  const topL1Label = topL1?.label ?? '--';

  // Q2 子节点列表：优先从 ResearchNode 树取（含 sublabel/proxy），后端 strategy
  // 只给出 top L1 的 score/total，不直接返回 children 列表。
  const topL1Children: StrategyNodeBrief[] = (() => {
    if (!topL1) return [];
    const treeNode = allNodes.find((n) => n.id === topL1.id);
    const kids = treeNode?.children ?? [];
    return kids.map((k) => ({
      id: k.id,
      label: k.label,
      sublabel: k.sublabel,
      score: k.score ?? 0,
      delta5d: k.delta5d,
    }));
  })();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <HeaderCard topL1Label={topL1Label} />
      <L1RankingCard strategy={strategy} onSelectNode={selectById} />
      <BreadthCard
        strategy={strategy}
        topL1Label={topL1Label}
        topL1Children={topL1Children}
        onSelectNode={selectById}
      />
      <ConfirmationCard strategy={strategy} onSelectNode={selectById} />
      <BestDrillCard strategy={strategy} onSelectNode={selectById} />

      {/* 底部嵌入已有 NodeDetailPanel — HTML L900-905 */}
      {selectedNode && (
        <div style={{
          background: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: 14,
          padding: 0,
          overflow: 'hidden',
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: '#94a3b8',
            padding: '12px 14px 4px',
          }}>
            当前选中节点
          </div>
          <NodeDetailPanel
            selectedNode={selectedNode}
            allNodes={allNodes}
            holdings={holdings}
            onSelectNode={onSelectNode}
          />
        </div>
      )}
    </div>
  );
}
