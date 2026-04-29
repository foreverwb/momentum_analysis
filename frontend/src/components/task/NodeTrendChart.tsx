/**
 * NodeTrendChart — Card 2 of the center panel in DrilldownView.
 *
 * 职责：纯 SVG 趋势图（不依赖第三方图表库），含 period/metric 分段切换控件、图例。
 *       Series 数据全部来自 4.6 API（NodeTrendResponse），不含前端 mock。
 * 不做：数据拉取（由 DrilldownView 持有，通过 data prop 传入）、状态管理。
 */
import React, { useMemo } from 'react';
import type { ResearchNode, NodeTrendResponse, NodeTrendPeriod, NodeTrendMetric } from '../../types';

// ─── SVG 尺寸常量 — 需求文档 §Card 2 Trend Chart ─────────────────────────────
const SVG_W = 600;
const SVG_H = 200;
const PAD = { t: 12, r: 16, b: 28, l: 44 } as const;
const CHART_W = SVG_W - PAD.l - PAD.r;
const CHART_H = SVG_H - PAD.t - PAD.b;

// Series stroke widths / opacities — 需求文档 §Card 2 Series lines
const NODE_STROKE = 2;
const OTHER_STROKE = 1.5;
const OTHER_OPACITY = 0.6;

const PERIOD_OPTIONS: { value: NodeTrendPeriod; label: string }[] = [
  { value: '5d', label: '5d' },
  { value: '20d', label: '20d' },
  { value: '63d', label: '63d' },
];

const METRIC_OPTIONS: { value: NodeTrendMetric; label: string }[] = [
  { value: 'relative', label: '相对走势' },
  { value: 'return20d', label: '20D收益' },
  { value: 'score', label: '综合评分' },
];

// X-axis labels per period
const X_LABELS: Record<NodeTrendPeriod, string[]> = {
  '5d': ['5日前', '4日', '3日', '2日', '昨日', '今日'],
  '20d': ['20日前', '15日', '10日', '5日', '今日'],
  '63d': ['63日前', '45日', '30日', '15日', '今日'],
};

export interface NodeTrendChartProps {
  selectedNode: ResearchNode;
  data: NodeTrendResponse | null;
  period: NodeTrendPeriod;
  metric: NodeTrendMetric;
  onPeriodChange: (p: NodeTrendPeriod) => void;
  onMetricChange: (m: NodeTrendMetric) => void;
  isLoading: boolean;
}

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        background: '#f1f5f9',
        padding: 3,
        borderRadius: 8,
        gap: 2,
      }}
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '3px 10px',
              border: 'none',
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 500,
              cursor: 'pointer',
              background: active ? '#fff' : 'transparent',
              color: active ? '#1e293b' : '#64748b',
              boxShadow: active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
              transition: 'all 0.12s ease',
              whiteSpace: 'nowrap',
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function proxyTag({ proxy, proxyType, proxyLabel }: ResearchNode): string {
  if (proxyType === 'etf' && proxy) return proxy;
  return proxyLabel ?? '合成';
}

export function NodeTrendChart({
  selectedNode,
  data,
  period,
  metric,
  onPeriodChange,
  onMetricChange,
  isLoading,
}: NodeTrendChartProps): React.ReactElement {
  const series = data?.series ?? [];
  const dates = data?.dates ?? [];

  // Compute Y bounds from all valid values
  const allVals = useMemo(
    () => series.flatMap((s) => s.values.filter((v): v is number => v !== null)),
    [series]
  );
  const minV = allVals.length ? Math.min(...allVals) : -1;
  const maxV = allVals.length ? Math.max(...allVals) : 1;
  const range = maxV - minV || 1;

  function toX(i: number, len: number): number {
    return PAD.l + (i / Math.max(len - 1, 1)) * CHART_W;
  }
  function toY(v: number): number {
    return PAD.t + CHART_H - ((v - minV) / range) * CHART_H;
  }

  function buildPath(values: (number | null)[]): string {
    const segments: string[] = [];
    let inSegment = false;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (v === null) {
        inSegment = false;
        continue;
      }
      const x = toX(i, values.length).toFixed(1);
      const y = toY(v).toFixed(1);
      if (!inSegment) {
        segments.push(`M ${x} ${y}`);
        inSegment = true;
      } else {
        segments.push(`L ${x} ${y}`);
      }
    }
    return segments.join(' ');
  }

  const gridVals = [minV, (minV + maxV) / 2, maxV];
  const crossesZero = minV < 0 && maxV > 0;
  const xLabels = X_LABELS[period];
  const tag = proxyTag(selectedNode);
  const nodeLabel = selectedNode.label;

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: 16,
        padding: '18px 20px',
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: 12,
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        {/* Left: node label + proxy annotation + sublabel */}
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#1e293b', marginBottom: 2 }}>
            {nodeLabel}
            {selectedNode.proxyType === 'etf' && selectedNode.proxy && (
              <span style={{ marginLeft: 8, fontSize: 12, color: '#2563eb', fontWeight: 500 }}>
                ({selectedNode.proxy})
              </span>
            )}
            {selectedNode.proxyType === 'synthetic' && (
              <span style={{ marginLeft: 8, fontSize: 11, color: '#d97706', fontWeight: 500 }}>
                合成篮
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: '#64748b' }}>相对走势对比 · {selectedNode.sublabel}</div>
        </div>

        {/* Right: controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <SegmentedControl
            options={PERIOD_OPTIONS}
            value={period}
            onChange={onPeriodChange}
          />
          <SegmentedControl
            options={METRIC_OPTIONS}
            value={metric}
            onChange={onMetricChange}
          />
        </div>
      </div>

      {/* SVG chart */}
      {isLoading ? (
        <div style={{ height: SVG_H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 12 }}>
          加载中…
        </div>
      ) : series.length === 0 ? (
        <div style={{ height: SVG_H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 12 }}>
          暂无趋势数据
        </div>
      ) : (
        <div style={{ width: '100%', overflowX: 'hidden' }}>
          <svg
            viewBox={`0 0 ${SVG_W} ${SVG_H}`}
            style={{ width: '100%', height: 'auto', display: 'block' }}
          >
            {/* Y grid lines + labels */}
            {gridVals.map((v, i) => (
              <g key={i}>
                <line
                  x1={PAD.l}
                  y1={toY(v)}
                  x2={SVG_W - PAD.r}
                  y2={toY(v)}
                  stroke="#e2e8f0"
                  strokeWidth="1"
                />
                <text
                  x={PAD.l - 6}
                  y={toY(v) + 4}
                  textAnchor="end"
                  fontSize="10"
                  fill="#94a3b8"
                >
                  {v > 0 ? '+' : ''}{v.toFixed(1)}
                </text>
              </g>
            ))}

            {/* Zero line (only when data crosses zero) */}
            {crossesZero && (
              <line
                x1={PAD.l}
                y1={toY(0)}
                x2={SVG_W - PAD.r}
                y2={toY(0)}
                stroke="#cbd5e1"
                strokeWidth="1"
                strokeDasharray="4,3"
              />
            )}

            {/* Series paths */}
            {series.map((s, i) => (
              <path
                key={s.symbol}
                d={buildPath(s.values)}
                fill="none"
                stroke={s.color}
                strokeWidth={i === 0 ? NODE_STROKE : OTHER_STROKE}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={i === 0 ? 1 : OTHER_OPACITY}
              />
            ))}

            {/* X-axis labels */}
            {xLabels.map((lbl, i) => {
              const x = PAD.l + (i / (xLabels.length - 1)) * CHART_W;
              return (
                <text
                  key={i}
                  x={x}
                  y={SVG_H - 6}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#94a3b8"
                >
                  {lbl}
                </text>
              );
            })}
          </svg>

          {/* Legend */}
          <div
            style={{
              display: 'flex',
              gap: 16,
              paddingLeft: PAD.l,
              marginTop: 4,
              flexWrap: 'wrap',
            }}
          >
            {series.map((s, i) => (
              <div
                key={s.symbol}
                style={{ display: 'flex', alignItems: 'center', gap: 5 }}
              >
                <div
                  style={{
                    width: 20,
                    height: 2.5,
                    borderRadius: 2,
                    background: s.color,
                    opacity: i === 0 ? 1 : 0.65,
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: 11, color: '#475569' }}>{s.symbol}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dates range hint when no API data yet */}
      {!isLoading && dates.length > 0 && series.length === 0 && (
        <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 4, textAlign: 'right' }}>
          {dates[0]} → {dates[dates.length - 1]}
        </div>
      )}
    </div>
  );
}
