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

// score / breadth 在后端可能未就绪而返回 null，这里统一用 base 兜底
export function scoreTierColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return SCORE_COLORS.base;
  if (score >= TIER_HIGH) return SCORE_COLORS.high;
  if (score >= TIER_MID) return SCORE_COLORS.mid;
  if (score >= TIER_LOW) return SCORE_COLORS.low;
  return SCORE_COLORS.base;
}

// Sparkline 折线专用色 — 500-series 更鲜亮，阈值 80/65（原型 §Sparkline colors）
// 与 scoreTierColor 刻意区分：文字用 600 系高对比度，折线用 500 系高饱和
export function sparklineTierColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return '#f59e0b';
  if (score >= 80) return '#22c55e';  // green-500
  if (score >= 65) return '#3b82f6';  // blue-500
  return '#f59e0b';                   // amber-500
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

// 节点 score 文案：null → '--'；其余按 digits 精度展示
export function fmtScore(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '--';
  return v.toFixed(digits);
}

// 节点 breadth / contribution 等百分位：null → '--'；不带 % 后缀，由调用方拼接
export function fmtPercent(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '--';
  return v.toFixed(digits);
}
