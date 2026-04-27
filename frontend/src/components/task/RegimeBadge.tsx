/**
 * RegimeBadge — Card 1 of the center panel in DrilldownView.
 *
 * 职责：调用 getMarketRegime API，每 5 分钟 refetch，渲染三档（A/B/C）背景渐变、
 *       5 列指标（SPY价 / 距20MA% / 距50MA% / 广度% / VIX）。
 * 不做：数据持久化、用户交互。
 */
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import * as api from '../../services/api';

// ─── Gradient per regime — 需求文档 §Card 1 Regime Badge ──────────────────────
const REGIME_GRADIENTS: Record<string, string> = {
  A: 'linear-gradient(105deg,#059669 0%,#10b981 50%,#34d399 100%)',
  B: 'linear-gradient(105deg,#d97706,#f59e0b,#fbbf24)',
  C: 'linear-gradient(105deg,#dc2626,#ef4444,#f87171)',
};

const REGIME_SHADOW: Record<string, string> = {
  A: '0 2px 10px rgba(16,185,129,0.2)',
  B: '0 2px 10px rgba(245,158,11,0.2)',
  C: '0 2px 10px rgba(239,68,68,0.2)',
};

const REGIME_TITLES: Record<string, string> = {
  A: 'Risk-On 满火力',
  B: '中性偏谨慎',
  C: 'Risk-Off 防御',
};

function extractRegimeLetter(regimeText: string | undefined): 'A' | 'B' | 'C' {
  if (!regimeText) return 'B';
  const upper = regimeText.toUpperCase();
  if (upper.includes('RISK_ON') || upper.includes('RISK-ON') || upper.startsWith('A')) return 'A';
  if (upper.includes('RISK_OFF') || upper.includes('RISK-OFF') || upper.startsWith('C')) return 'C';
  return 'B';
}

function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v === null || v === undefined) return '--';
  return (v > 0 ? '+' : '') + (v * 100).toFixed(decimals) + '%';
}

function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--';
  return v.toFixed(2);
}

function fmtVix(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--';
  return v.toFixed(1);
}

const REGIME_REFETCH_MS = 5 * 60 * 1000;

export function RegimeBadge(): React.ReactElement {
  const { data } = useQuery({
    queryKey: ['market-regime'],
    queryFn: () => api.getMarketRegime(),
    staleTime: REGIME_REFETCH_MS,
    refetchInterval: REGIME_REFETCH_MS,
  });

  const regime = extractRegimeLetter(data?.regime_text);
  const gradient = REGIME_GRADIENTS[regime];
  const shadow = REGIME_SHADOW[regime];
  const title = REGIME_TITLES[regime];

  const spy = data?.spy;
  const distTo20ma = spy?.dist_to_sma20 ?? data?.indicators?.dist_to_sma20;
  const distTo50ma = spy?.dist_to_sma50 ?? data?.indicators?.dist_to_sma50;

  // 广度%: indicators 里的 return_20d 不是广度，暂无直接字段，显示 '--'
  const breadthPct: string = '--';
  const vix = data?.vix;

  const metrics: [string, string][] = [
    ['$SPY', fmtPrice(spy?.price)],
    ['距20MA', fmtPct(distTo20ma)],
    ['距50MA', fmtPct(distTo50ma)],
    ['广度', breadthPct],
    ['VIX', fmtVix(vix)],
  ];

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'stretch',
        borderRadius: 12,
        overflow: 'hidden',
        background: gradient,
        color: '#fff',
        boxShadow: shadow,
        flexShrink: 0,
      }}
    >
      {/* Grade + title block */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 16px',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: 34,
            height: 34,
            background: 'rgba(255,255,255,0.2)',
            borderRadius: 9,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 800,
            fontSize: 16,
          }}
        >
          {regime}
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13 }}>{title}</div>
          <div style={{ fontSize: 10, opacity: 0.75, marginTop: 1 }}>市场环境 · 实时</div>
        </div>
      </div>

      {/* Vertical divider */}
      <div style={{ width: 1, background: 'rgba(255,255,255,0.18)', margin: '8px 0' }} />

      {/* 5 metric columns */}
      {metrics.map(([label, val], i) => (
        <div
          key={label}
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '8px 4px',
            borderRight:
              i < metrics.length - 1 ? '1px solid rgba(255,255,255,0.15)' : 'none',
            minWidth: 58,
          }}
        >
          <div style={{ fontSize: 10, opacity: 0.72, marginBottom: 2, whiteSpace: 'nowrap' }}>
            {label}
          </div>
          <div style={{ fontWeight: 700, fontSize: 13, whiteSpace: 'nowrap' }}>{val}</div>
        </div>
      ))}
    </div>
  );
}
