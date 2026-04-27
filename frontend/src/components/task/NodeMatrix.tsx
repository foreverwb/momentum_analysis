/**
 * NodeMatrix — Card 3 of the center panel in DrilldownView.
 *
 * 职责：渲染子节点矩阵卡片网格（仅当 selectedNode.children.length > 0 时出现）。
 *       每张卡含 Sparkline、贡献进度条、三列底部指标，点击触发 onSelectChild。
 * 不做：数据拉取、状态管理。
 */
import React, { useMemo } from 'react';
import type { ResearchNode } from '../../types';
import { Sparkline } from './Sparkline';
import { scoreTierColor, deltaColor, fmtDelta } from './nodeStyles';

// ─── Contribution progress bar — 需求文档 §Card 3 Sub-Node Matrix ─────────────
function ContribBar({
  value,
  max = 100,
  color = '#3b82f6',
}: {
  value: number;
  max?: number;
  color?: string;
}): React.ReactElement {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div
      style={{
        height: 5,
        background: '#e2e8f0',
        borderRadius: 3,
        overflow: 'hidden',
        flex: 1,
      }}
    >
      <div
        style={{
          height: '100%',
          width: `${pct}%`,
          background: color,
          borderRadius: 3,
          transition: 'width 0.3s ease',
        }}
      />
    </div>
  );
}

function buildSparkData(node: ResearchNode): number[] {
  const { score, delta3d, delta5d } = node;
  const d3 = delta3d ?? 0;
  const d5 = delta5d ?? 0;
  return [
    score - d5 - d3,
    score - d5,
    score - d3,
    score + d3 * 0.5,
    score,
  ];
}

interface ChildCardProps {
  child: ResearchNode;
  onSelect: (child: ResearchNode) => void;
}

function ChildCard({ child, onSelect }: ChildCardProps): React.ReactElement {
  const sparkData = useMemo(() => buildSparkData(child), [child]);
  const scoreColor = scoreTierColor(child.score);
  const contribVal = child.contribution ?? 0;

  const [hovered, setHovered] = React.useState(false);

  return (
    <div
      onClick={() => onSelect(child)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: hovered ? 'rgba(59,130,246,0.03)' : '#f8fafc',
        border: hovered ? '1px solid #3b82f6' : '1px solid #e2e8f0',
        borderRadius: 12,
        padding: '12px 14px',
        cursor: 'pointer',
        transition: 'border-color 0.12s ease, background 0.12s ease',
      }}
    >
      {/* Header row: label + proxy tag | score */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: 8,
          gap: 8,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>
              {child.label}
            </span>
            <span
              style={{
                fontSize: 10,
                padding: '1px 5px',
                borderRadius: 4,
                fontWeight: 600,
                background:
                  child.proxyType === 'etf'
                    ? 'rgba(59,130,246,0.1)'
                    : 'rgba(245,158,11,0.1)',
                color: child.proxyType === 'etf' ? '#2563eb' : '#d97706',
                flexShrink: 0,
              }}
            >
              {child.proxyType === 'etf' ? (child.proxy ?? 'ETF') : '合成'}
            </span>
          </div>
        </div>
        <span
          style={{
            fontSize: 20,
            fontWeight: 700,
            color: scoreColor,
            lineHeight: 1,
            flexShrink: 0,
          }}
        >
          {child.score.toFixed(0)}
        </span>
      </div>

      {/* Sparkline */}
      <div style={{ marginBottom: 8 }}>
        <Sparkline data={sparkData} color={scoreColor} width={220} height={28} />
      </div>

      {/* Contribution row */}
      <div style={{ marginBottom: 8 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 4,
          }}
        >
          <span style={{ fontSize: 10, color: '#94a3b8' }}>对母板块贡献</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#2563eb' }}>
            {contribVal.toFixed(0)}%
          </span>
        </div>
        <ContribBar value={contribVal} max={100} color="#3b82f6" />
      </div>

      {/* Bottom 3 columns */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 10,
          color: '#64748b',
          gap: 4,
        }}
      >
        <span>
          vs母{' '}
          <span
            style={{
              fontWeight: 600,
              color: deltaColor(child.scoreVsParent),
            }}
          >
            {fmtDelta(child.scoreVsParent)}
          </span>
        </span>
        <span>
          5D{' '}
          <span
            style={{
              fontWeight: 600,
              color: deltaColor(child.delta5d),
            }}
          >
            {fmtDelta(child.delta5d)}
          </span>
        </span>
        <span>
          广度{' '}
          <span style={{ fontWeight: 600, color: '#1e293b' }}>
            {child.breadth.toFixed(0)}%
          </span>
        </span>
      </div>
    </div>
  );
}

export interface NodeMatrixProps {
  selectedNode: ResearchNode;
  onSelectChild: (child: ResearchNode) => void;
}

export function NodeMatrix({
  selectedNode,
  onSelectChild,
}: NodeMatrixProps): React.ReactElement | null {
  const children = selectedNode.children;
  if (!children || children.length === 0) return null;

  const colCount = Math.min(4, children.length);

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: 16,
        padding: '16px 20px',
      }}
    >
      {/* Section header */}
      <div style={{ fontSize: 13, fontWeight: 700, color: '#1e293b', marginBottom: 12 }}>
        子节点矩阵
        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400, marginLeft: 6 }}>
          {children.length} 个子节点
        </span>
      </div>

      {/* Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${colCount}, 1fr)`,
          gap: 10,
        }}
      >
        {children.map((child) => (
          <ChildCard key={child.id} child={child} onSelect={onSelectChild} />
        ))}
      </div>
    </div>
  );
}
