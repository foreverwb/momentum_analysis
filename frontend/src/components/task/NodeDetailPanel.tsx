/**
 * NodeDetailPanel — 右栏（300px）节点详情面板，Task 4.10。
 *
 * 职责：展示选中节点的 Header、Node Header Card、贡献与广度、同层排名、持仓 Top5、子节点概览。
 * 不做：数据拉取（holdings / trend 由 DrilldownView 统一管理）；sparkline 数据生成（使用真实持仓序列占位）。
 */
import React, { useMemo } from 'react';
import type { ResearchNode, NodeHolding } from '../../types';
import { Sparkline } from './Sparkline';
import { NodeHoldingsTable } from './NodeHoldingsTable';

// ─── Score / Delta helpers ────────────────────────────────────────────────────
// score / breadth 在后端可能未就绪而返回 null，所有 helper 接受 null

function scoreColor(s: number | null | undefined): string {
  if (s === null || s === undefined) return '#64748b';
  if (s >= 85) return '#059669';
  if (s >= 70) return '#2563eb';
  if (s >= 60) return '#d97706';
  return '#64748b';
}

function fmtScore(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '--';
  return v.toFixed(digits);
}

function deltaColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return '#94a3b8';
  return v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : '#94a3b8';
}

function fmtDelta(v: number | null | undefined, suffix = ''): string {
  if (v === null || v === undefined) return '--';
  return (v > 0 ? '+' : '') + v.toFixed(1) + suffix;
}

function breadthColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return '#94a3b8';
  if (v >= 70) return '#22c55e';
  if (v >= 50) return '#2563eb';
  return '#d97706';
}

function breadthFill(v: number | null | undefined): string {
  if (v === null || v === undefined) return '#cbd5e1';
  if (v >= 70) return '#22c55e';
  if (v >= 50) return '#3b82f6';
  return '#f59e0b';
}

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CFG: Record<string, { label: string; color: string }> = {
  complete: { label: '已更新', color: '#16a34a' },
  pending:  { label: '待计算', color: '#d97706' },
  missing:  { label: '缺失',   color: '#dc2626' },
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function ProxyTag({ node }: { node: ResearchNode }) {
  if (node.proxyType === 'etf' && node.proxy) {
    return (
      <span style={{
        fontSize: 11, padding: '2px 8px', borderRadius: 6,
        background: 'rgba(59,130,246,0.08)', color: '#2563eb', fontWeight: 600,
      }}>
        {node.proxy}
      </span>
    );
  }
  if (node.proxyType === 'synthetic') {
    return (
      <span style={{
        fontSize: 11, padding: '2px 8px', borderRadius: 6,
        background: 'rgba(245,158,11,0.08)', color: '#d97706', fontWeight: 600,
      }}>
        合成篮
      </span>
    );
  }
  return null;
}

function ProxyTagSmall({ node }: { node: ResearchNode }) {
  const label = node.proxyType === 'etf' ? (node.proxy ?? '') : '合成';
  if (!label) return null;
  return (
    <span style={{
      fontSize: 10, padding: '1px 5px', borderRadius: 4, fontWeight: 600,
      background: node.proxyType === 'etf' ? 'rgba(59,130,246,0.1)' : 'rgba(245,158,11,0.1)',
      color: node.proxyType === 'etf' ? '#2563eb' : '#d97706',
    }}>
      {label}
    </span>
  );
}

function ContribBar({ value, fill }: { value: number | null | undefined; fill: string }) {
  // value=null（计算未就绪）时显示空槽
  const pct = value === null || value === undefined ? 0 : Math.min(100, value);
  return (
    <div style={{ height: 5, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden', flex: 1 }}>
      <div style={{
        height: '100%',
        width: `${pct}%`,
        background: fill,
        borderRadius: 3,
        transition: 'width 0.3s ease',
      }} />
    </div>
  );
}

// ─── Cards ────────────────────────────────────────────────────────────────────

function NodeHeaderCard({ node }: { node: ResearchNode }) {
  const relVal = node.scoreVsParent;
  const relStrNum = parseFloat(node.relStrength);

  return (
    <div style={{
      background: '#fff',
      border: '1px solid #e2e8f0',
      borderRadius: 14,
      padding: 14,
    }}>
      {/* Label + Score row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 17, fontWeight: 700, color: '#1e293b' }}>{node.label}</span>
            <ProxyTag node={node} />
          </div>
          <div style={{ fontSize: 12, color: '#64748b' }}>{node.sublabel}</div>
          {node.proxyType === 'synthetic' && node.proxyLabel && (
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{node.proxyLabel}</div>
          )}
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 10 }}>
          <div style={{ fontSize: 30, fontWeight: 700, lineHeight: 1, color: scoreColor(node.score) }}>
            {fmtScore(node.score, 1)}
          </div>
          <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>综合分</div>
        </div>
      </div>

      {/* 2×2 metric grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {[
          {
            label: '相对母节点',
            value: relVal !== null ? fmtDelta(relVal, '分') : '--',
            color: deltaColor(relVal),
          },
          {
            label: '相对强度',
            value: node.relStrength,
            color: isNaN(relStrNum) ? '#94a3b8' : relStrNum >= 0 ? '#22c55e' : '#ef4444',
          },
          {
            label: '3D Δ分',
            value: fmtDelta(node.delta3d),
            color: deltaColor(node.delta3d),
          },
          {
            label: '5D Δ分',
            value: fmtDelta(node.delta5d),
            color: deltaColor(node.delta5d),
          },
        ].map((m) => (
          <div key={m.label} style={{
            background: '#f8fafc',
            border: '1px solid #f1f5f9',
            borderRadius: 8,
            padding: '7px 10px',
          }}>
            <div style={{ fontSize: 10, color: '#94a3b8', marginBottom: 3 }}>{m.label}</div>
            <div style={{
              fontSize: 14,
              fontWeight: 700,
              color: m.color,
              fontFeatureSettings: '"tnum"',
            }}>
              {m.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ContributionCard({ node }: { node: ResearchNode }) {
  if (node.contribution === null) return null;
  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 12 }}>节点贡献与广度</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>对母板块贡献</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: '#2563eb' }}>{fmtScore(node.contribution)}%</span>
          </div>
          <ContribBar value={node.contribution} fill="#3b82f6" />
        </div>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>持仓广度 (&gt;50MA)</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: breadthColor(node.breadth) }}>{fmtScore(node.breadth)}%</span>
          </div>
          <ContribBar value={node.breadth} fill={breadthFill(node.breadth)} />
        </div>
      </div>
    </div>
  );
}

interface SiblingRankingCardProps {
  siblings: ResearchNode[];
  selectedNode: ResearchNode;
  onSelectNode: (node: ResearchNode) => void;
}

function SiblingRankingCard({ siblings, selectedNode, onSelectNode }: SiblingRankingCardProps) {
  if (siblings.length === 0) return null;
  const sorted = useMemo(
    () => [...siblings].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)),
    [siblings]
  );

  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 12 }}>同层节点排名</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map((sib, i) => {
          const isSelected = sib.id === selectedNode.id;
          // Flat placeholder sparkline — score=null（计算未就绪）退化为平线 0
          const sScore = sib.score ?? 0;
          const sparkData = [sScore * 0.9, sScore * 0.92, sScore * 0.95, sScore * 0.97, sScore];
          return (
            <div
              key={sib.id}
              onClick={() => !isSelected && onSelectNode(sib)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '7px 10px',
                borderRadius: 8,
                cursor: isSelected ? 'default' : 'pointer',
                background: isSelected ? 'rgba(37,99,235,0.06)' : 'transparent',
                border: isSelected ? '1px solid rgba(59,130,246,0.2)' : '1px solid transparent',
                transition: 'background 0.12s',
              }}
              onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = '#f1f5f9'; }}
              onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
            >
              <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 18, textAlign: 'center' }}>#{i + 1}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: isSelected ? 700 : 500, color: '#334155' }}>{sib.label}</div>
                <ProxyTagSmall node={sib} />
              </div>
              <Sparkline
                data={sparkData}
                color={(sib.score ?? 0) >= 80 ? '#22c55e' : '#3b82f6'}
                width={36}
                height={16}
              />
              <span style={{
                fontSize: 13,
                fontWeight: 700,
                color: scoreColor(sib.score),
                minWidth: 28,
                textAlign: 'right',
              }}>
                {fmtScore(sib.score)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}


interface ChildrenOverviewCardProps {
  children: ResearchNode[];
  onSelectNode: (node: ResearchNode) => void;
}

function ChildrenOverviewCard({ children, onSelectNode }: ChildrenOverviewCardProps) {
  if (children.length === 0) return null;
  const sorted = useMemo(
    () => [...children].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)),
    [children]
  );

  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 12 }}>子节点概览</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {sorted.map((child) => {
          const proxy = child.proxyType === 'etf' ? child.proxy : child.proxyLabel;
          return (
            <div
              key={child.id}
              onClick={() => onSelectNode(child)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '6px 8px', borderRadius: 8, background: '#f8fafc',
                cursor: 'pointer', transition: 'background 0.12s',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#eff6ff'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = '#f8fafc'; }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: '#334155' }}>{child.label}</div>
                {proxy && (
                  <div style={{
                    fontSize: 10, color: '#94a3b8',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {proxy}
                  </div>
                )}
              </div>
              <span style={{ fontSize: 11, fontWeight: 600, color: deltaColor(child.delta5d) }}>
                {fmtDelta(child.delta5d)}
              </span>
              <span style={{
                fontSize: 13, fontWeight: 700,
                color: scoreColor(child.score),
                minWidth: 28, textAlign: 'right',
              }}>
                {fmtScore(child.score)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

export interface NodeDetailPanelProps {
  selectedNode: ResearchNode;
  allNodes: ResearchNode[];
  holdings: NodeHolding[];
  onSelectNode: (node: ResearchNode) => void;
}

export function NodeDetailPanel({
  selectedNode,
  allNodes,
  holdings,
  onSelectNode,
}: NodeDetailPanelProps): React.ReactElement {
  // Siblings = nodes sharing same parent (exclude self)
  const siblings = useMemo<ResearchNode[]>(() => {
    if (selectedNode.level === 0) return [];
    // Find the parent node by scanning allNodes for one that has selectedNode as direct child
    const parent = allNodes.find((n) =>
      n.children?.some((c) => c.id === selectedNode.id)
    );
    return parent?.children ?? [];
  }, [allNodes, selectedNode]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Panel header */}
      <div style={{
        background: '#fff',
        borderBottom: '1px solid #e2e8f0',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: '#475569' }}>
            <line x1="18" y1="20" x2="18" y2="10" />
            <line x1="12" y1="20" x2="12" y2="4" />
            <line x1="6" y1="20" x2="6" y2="14" />
          </svg>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>节点详情</span>
        </div>
        <span style={{
          fontSize: 10,
          color: '#94a3b8',
          background: '#f1f5f9',
          padding: '2px 7px',
          borderRadius: 5,
        }}>
          L{selectedNode.level + 1}
        </span>
      </div>

      {/* Scrollable cards */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}>
        <NodeHeaderCard node={selectedNode} />
        <ContributionCard node={selectedNode} />
        <SiblingRankingCard
          siblings={siblings}
          selectedNode={selectedNode}
          onSelectNode={onSelectNode}
        />
        {holdings.length > 0 && (
          <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14, padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#475569' }}>持仓标的</span>
              <span style={{ fontSize: 10, color: '#94a3b8' }}>共 {holdings.length} 只 · 按分数</span>
            </div>
            <NodeHoldingsTable
              compact
              holdings={holdings}
              showAll={false}
              onShowAll={() => {}}
              isLoading={false}
            />
          </div>
        )}
        <ChildrenOverviewCard
          children={selectedNode.children ?? []}
          onSelectNode={onSelectNode}
        />
      </div>
    </div>
  );
}
