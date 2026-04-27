/**
 * nodeStyles — Score-tier color helpers shared by NodeTree, NodeDetailPanel, NodeMatrix.
 *
 * 职责：提供节点评分分段颜色映射，集中管理以便 4.9/4.10 复用。
 * 不做：任何 React 渲染或 DOM 操作。
 */

// Score tier thresholds — 需求文档 §Panel 2
const TIER_HIGH = 85;
const TIER_MID = 70;
const TIER_LOW = 60;

// Score tier colors — 需求文档 §Panel 2 Score colors
export const SCORE_COLORS = {
  high: '#059669',  // emerald-600
  mid: '#2563eb',   // blue-600
  low: '#d97706',   // amber-600
  base: '#64748b',  // slate-500
} as const;

export function scoreTierColor(score: number): string {
  if (score >= TIER_HIGH) return SCORE_COLORS.high;
  if (score >= TIER_MID) return SCORE_COLORS.mid;
  if (score >= TIER_LOW) return SCORE_COLORS.low;
  return SCORE_COLORS.base;
}

export function deltaColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return '#94a3b8';
  if (v > 0) return '#22c55e';
  if (v < 0) return '#ef4444';
  return '#94a3b8';
}

export function fmtDelta(v: number | null | undefined, suffix = ''): string {
  if (v === null || v === undefined) return '--';
  return (v > 0 ? '+' : '') + v.toFixed(1) + suffix;
}
