/**
 * NodeTree — 左栏研究节点树，280px，可折叠、可选中、Lens 切换。
 *
 * 职责：渲染节点行、展开/收起、Lens 切换、Footer Legend。
 * 不做：数据拉取、localStorage 持久化（由 DrilldownView 处理）。
 */
import React, { useMemo } from 'react';
import type { ResearchNode, TaskViewMode } from '../../types';
import { Sparkline } from './Sparkline';
import { scoreTierColor, fmtScore } from './nodeStyles';

// ─── Pixel constants — 需求文档 §Panel 2 ─────────────────────────────────────
const INDENT_BASE = 12;
const INDENT_PER_LEVEL = 16;

// ─── Icons (inline SVG, Lucide) ───────────────────────────────────────────────
function IconLayers() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="12 2 2 7 12 12 22 7 12 2" />
      <polyline points="2 17 12 22 22 17" />
      <polyline points="2 12 12 17 22 12" />
    </svg>
  );
}

function IconChevronRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function IconChevronDown() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

// ─── Proxy tag pill ───────────────────────────────────────────────────────────
interface ProxyTagProps {
  proxyType: 'etf' | 'synthetic';
  proxy: string | null;
}

function ProxyTag({ proxyType, proxy }: ProxyTagProps) {
  const isEtf = proxyType === 'etf';
  return (
    <span
      style={{
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 4,
        fontWeight: 600,
        background: isEtf ? 'rgba(59,130,246,0.1)' : 'rgba(245,158,11,0.1)',
        color: isEtf ? '#2563eb' : '#d97706',
        flexShrink: 0,
      }}
    >
      {isEtf ? proxy : '合成'}
    </span>
  );
}

// ─── Sparkline data derivation — 前端凑 5 点序列（需求文档 §3 Sparkline 数据来源）──
function buildSparkData(node: ResearchNode): number[] {
  // score=null（计算未就绪）时返回平线，避免 NaN 路径
  const s = node.score ?? 0;
  const d3 = node.delta3d ?? 0;
  const d5 = node.delta5d ?? 0;
  return [s - d5 - d3, s - d5, s - d3, s + d3 * 0.5, s];
}

// ─── Single node row ──────────────────────────────────────────────────────────
interface NodeItemProps {
  node: ResearchNode;
  selectedId: string | null;
  expandedIds: Set<string>;
  onSelect: (node: ResearchNode) => void;
  onToggleExpand: (nodeId: string) => void;
}

function NodeItem({
  node,
  selectedId,
  expandedIds,
  onSelect,
  onToggleExpand,
}: NodeItemProps): React.ReactElement {
  const isSelected = selectedId === node.id;
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expandedIds.has(node.id);
  const paddingLeft = INDENT_BASE + node.level * INDENT_PER_LEVEL;
  const sparkData = useMemo(() => buildSparkData(node), [node]);
  const scoreColor = scoreTierColor(node.score);

  function handleClick() {
    onSelect(node);
    if (hasChildren) onToggleExpand(node.id);
  }

  function handleMouseEnter(e: React.MouseEvent<HTMLDivElement>) {
    if (!isSelected) {
      e.currentTarget.style.background = '#f1f5f9';
    }
  }

  function handleMouseLeave(e: React.MouseEvent<HTMLDivElement>) {
    if (!isSelected) {
      e.currentTarget.style.background = 'transparent';
    }
  }

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 12px',
    paddingLeft,
    cursor: 'pointer',
    borderRadius: 8,
    margin: '1px 6px',
    border: isSelected ? '1px solid var(--accent-blue, #3b82f6)' : '1px solid transparent',
    background: isSelected
      ? 'linear-gradient(135deg, rgba(37,99,235,0.07), rgba(147,51,234,0.07))'
      : 'transparent',
    transition: 'background 0.12s ease',
  };

  return (
    <div>
      <div
        style={rowStyle}
        onClick={handleClick}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {/* Chevron or spacer */}
        <span style={{ width: 14, color: '#94a3b8', flexShrink: 0, lineHeight: 0 }}>
          {hasChildren
            ? (isExpanded ? <IconChevronDown /> : <IconChevronRight />)
            : <span style={{ display: 'inline-block', width: 14 }} />}
        </span>

        {/* Label block */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              style={{
                fontWeight: isSelected ? 700 : 500,
                fontSize: 13,
                color: isSelected ? '#1e293b' : '#334155',
                whiteSpace: 'nowrap',
              }}
            >
              {node.label}
            </span>
            {(node.proxy || node.proxyType === 'synthetic') && (
              <ProxyTag proxyType={node.proxyType} proxy={node.proxy} />
            )}
          </div>
          <div
            style={{
              fontSize: 10,
              color: '#94a3b8',
              marginTop: 1,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {node.sublabel}
          </div>
        </div>

        {/* Sparkline + score */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <Sparkline data={sparkData} color={scoreColor} width={44} height={18} />
          <span
            style={{
              fontWeight: 700,
              fontSize: 13,
              color: scoreColor,
              minWidth: 28,
              textAlign: 'right',
            }}
          >
            {fmtScore(node.score)}
          </span>
        </div>
      </div>

      {/* Children (recursive, depth ≤ 4) */}
      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <NodeItem
              key={child.id}
              node={child}
              selectedId={selectedId}
              expandedIds={expandedIds}
              onSelect={onSelect}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── NodeTree (main export) ────────────────────────────────────────────────────
export interface NodeTreeProps {
  nodes: ResearchNode[];
  selectedNodeId: string | null;
  expandedIds: Set<string>;
  lens: TaskViewMode;
  onSelect: (node: ResearchNode) => void;
  onToggleExpand: (nodeId: string) => void;
  onLensChange: (lens: TaskViewMode) => void;
  totalNodeCount: number;
  isLoading?: boolean;
}

const LENS_OPTIONS: { value: TaskViewMode; label: string }[] = [
  { value: 'gics', label: 'GICS 分类' },
  { value: 'chain', label: '产业链图' },
];

export function NodeTree({
  nodes,
  selectedNodeId,
  expandedIds,
  lens,
  onSelect,
  onToggleExpand,
  onLensChange,
  totalNodeCount,
  isLoading = false,
}: NodeTreeProps): React.ReactElement {
  return (
    <aside
      style={{
        width: 280,
        flexShrink: 0,
        borderRight: '1px solid #e2e8f0',
        background: '#fff',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '14px 16px 10px',
          borderBottom: '1px solid #f1f5f9',
          flexShrink: 0,
        }}
      >
        {/* Title row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#1e293b' }}>
            <IconLayers />
            <span style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>研究节点树</span>
          </div>
          <span style={{ fontSize: 11, color: '#94a3b8' }}>{totalNodeCount} 节点</span>
        </div>

        {/* Lens toggle — segmented control */}
        <div
          style={{
            display: 'flex',
            background: '#f1f5f9',
            padding: 3,
            borderRadius: 8,
            gap: 2,
          }}
        >
          {LENS_OPTIONS.map((opt) => {
            const active = lens === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => onLensChange(opt.value)}
                style={{
                  flex: 1,
                  padding: '4px 0',
                  border: 'none',
                  borderRadius: 6,
                  fontSize: 11,
                  fontWeight: 500,
                  cursor: 'pointer',
                  background: active ? '#fff' : 'transparent',
                  color: active ? '#1e293b' : '#64748b',
                  boxShadow: active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
                  transition: 'all 0.12s ease',
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Column header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '6px 18px 4px',
          fontSize: 10,
          color: '#94a3b8',
          flexShrink: 0,
        }}
      >
        <span style={{ flex: 1 }}>节点 / 代理</span>
        <span style={{ minWidth: 44, textAlign: 'right', marginRight: 6 }}>20D走势</span>
        <span style={{ minWidth: 28, textAlign: 'right' }}>分数</span>
      </div>

      {/* Scrollable node list */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 12 }}>
        {isLoading ? (
          <div style={{ padding: 16, fontSize: 12, color: '#94a3b8', textAlign: 'center' }}>
            加载中…
          </div>
        ) : (
          nodes.map((node) => (
            <NodeItem
              key={node.id}
              node={node}
              selectedId={selectedNodeId}
              expandedIds={expandedIds}
              onSelect={onSelect}
              onToggleExpand={onToggleExpand}
            />
          ))
        )}
      </div>

      {/* Footer legend */}
      <div
        style={{
          padding: '10px 16px',
          borderTop: '1px solid #f1f5f9',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: 10,
            padding: '1px 6px',
            borderRadius: 4,
            fontWeight: 600,
            background: 'rgba(59,130,246,0.1)',
            color: '#2563eb',
          }}
        >
          ETF 代理
        </span>
        <span
          style={{
            fontSize: 10,
            padding: '1px 6px',
            borderRadius: 4,
            fontWeight: 600,
            background: 'rgba(245,158,11,0.1)',
            color: '#d97706',
          }}
        >
          合成篮
        </span>
      </div>
    </aside>
  );
}
