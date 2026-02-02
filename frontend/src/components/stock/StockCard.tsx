import React from 'react';
import type { Stock } from '../../types';
import { DimensionCard } from './DimensionCard';

interface StockCardProps {
  stock: Stock;
  rank: number;
  onClick?: () => void;
}

export function StockCard({ stock, rank, onClick }: StockCardProps) {
  if (!stock) return null;

  const formatPercent = (value?: number | null, digits = 1, withSign = true) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    const sign = value > 0 && withSign ? '+' : '';
    return `${sign}${value.toFixed(digits)}%`;
  };

  const formatNumber = (value?: number | null, digits = 2, withSign = false) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    const sign = value > 0 && withSign ? '+' : '';
    return `${sign}${value.toFixed(digits)}`;
  };

  const formatMultiple = (value?: number | null, digits = 2) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return `${value.toFixed(digits)}x`;
  };

  const handleClick = () => {
    if (!stock?.id) return;
    console.log('Stock card clicked:', stock.symbol);
    onClick?.();
  };

  // Helper to format delta values
  const formatDelta = (value: number | null): { text: string; className: string } => {
    if (value === null || value === undefined) {
      return { text: '--', className: '' };
    }
    if (value > 0) {
      return { text: `+${value}`, className: 'text-[var(--accent-green)]' };
    }
    if (value < 0) {
      return { text: `${value}`, className: 'text-[var(--accent-red)]' };
    }
    return { text: '+0', className: 'text-[var(--accent-green)]' };
  };

  // Helper to determine score color
  const getScoreColor = (score: number): 'green' | 'amber' | 'blue' | 'purple' => {
    if (score >= 60) return 'green';
    if (score >= 40) return 'amber';
    return 'blue';
  };

  const delta3d = formatDelta(stock.changes?.delta3d);
  const delta5d = formatDelta(stock.changes?.delta5d);

  const metrics = (stock.metrics ?? {}) as Stock['metrics'];
  const momentumMetrics = [
    { label: '20D收益', value: formatPercent(metrics.return20d, 1), variant: 'highlight' as const },
    { label: '20D收益(去3日)', value: formatPercent(metrics.return20dEx3d, 1) },
    { label: '63D收益', value: formatPercent(metrics.return63d, 1), variant: 'highlight' as const },
    { label: '相对行业强度', value: formatNumber(metrics.relativeStrength, 2) },
    { label: '距20日高点', value: formatPercent(metrics.distanceToHigh20d, 1, false), variant: 'warning' as const },
    { label: '放量倍数', value: formatMultiple(metrics.volumeMultiple ?? metrics.breakoutVolume, 2), variant: 'warning' as const }
  ];

  const maAlignmentValue = metrics.maAlignment ?? 'N/A';
  const maAlignmentVariant = maAlignmentValue === 'N/A' ? 'muted' as const : undefined;
  const trendMetrics = [
    { label: '均线排列', value: maAlignmentValue, variant: maAlignmentVariant },
    { label: '20DMA斜率', value: formatNumber(metrics.sma20Slope, 2, true), variant: 'highlight' as const },
    { label: '趋势持续度', value: formatPercent(metrics.trendPersistence, 0, false) }
  ];

  const volumeMetrics = [
    { label: '突破放量', value: formatMultiple(metrics.breakoutVolume, 2) },
    { label: '量比结构', value: formatNumber(metrics.volumeRatio, 2) },
    { label: 'OBV趋势', value: metrics.obvTrend ?? 'Neutral', variant: metrics.obvTrend ? undefined : 'muted' as const }
  ];

  const overheatValue = metrics.overheat ?? 'Normal';
  const overheatVariant = overheatValue === 'Hot' ? 'warning' as const : undefined;
  const qualityMetrics = [
    { label: '20D回撤', value: formatPercent(metrics.maxDrawdown20d, 1, true), variant: 'highlight' as const },
    { label: 'ATR%', value: formatPercent(metrics.atrPercent, 1, false), variant: 'highlight' as const },
    { label: '偏离20MA', value: formatPercent(metrics.deviationFrom20ma, 1, true), variant: 'highlight' as const },
    { label: '过热程度', value: overheatValue, variant: overheatVariant }
  ];

  const optionsHeatValue = metrics.optionsHeat ?? 'Medium';
  const optionsHeatVariant = optionsHeatValue === 'High' ? 'warning' as const : undefined;
  const optionsMetrics = [
    { label: '热度', value: optionsHeatValue, variant: optionsHeatVariant },
    { label: '相对成交', value: formatMultiple(metrics.optionsRelVolume, 2) },
    { label: 'IVR', value: formatNumber(metrics.ivr, 0) },
    { label: 'IV30', value: formatNumber(metrics.iv30, 2) }
  ];

  return (
    <div 
      className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6 mb-5 cursor-pointer hover:shadow-md transition-shadow"
      onClick={handleClick}
    >
      {/* Stock Header */}
      <div className="flex items-start justify-between mb-5">
        {/* Left: Stock Info */}
        <div className="flex items-center gap-4">
          {/* Rank Circle */}
          <div 
            className="w-11 h-11 rounded-full flex items-center justify-center text-white text-base font-bold"
            style={{ background: 'linear-gradient(135deg, var(--accent-purple), #a855f7)' }}
          >
            {rank}
          </div>
          
          {/* Stock Details */}
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <span className="text-xl font-bold text-[var(--text-primary)]">
                {stock.symbol ?? '--'}
              </span>
              <span className="text-sm text-[var(--text-muted)]">
                {stock.name ?? '--'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[13px] text-[var(--text-secondary)]">
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">板块:</span>
                <span className="text-[var(--accent-blue)]">{stock.sector ?? '--'}</span>
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">行业:</span>
                <span className="text-[var(--accent-blue)]">{stock.industry ?? '--'}</span>
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">价格:</span>
                <span className="text-[var(--accent-green)] font-medium">
                  ${stock.price?.toFixed(2) ?? '--'}
                </span>
              </span>
            </div>
          </div>
        </div>

        {/* Right: Score Box */}
        <div className="text-right">
          <div className="text-xs text-[var(--text-muted)] mb-1">综合得分</div>
          <div className="text-[40px] font-bold text-[var(--text-primary)] leading-none">
            {stock.scoreTotal?.toFixed(1) ?? '--'}
          </div>
        </div>
      </div>

      {/* Change Indicators */}
      <div className="mb-5 pb-4 border-b border-[var(--border-light)]">
        <div className="text-xs text-[var(--text-muted)] mb-2">变化指标</div>
        <div className="flex gap-6">
          <div className="flex items-center gap-2">
            <span className="text-sm text-[var(--text-secondary)]">3D Δ Score:</span>
            <span className={`text-sm font-semibold ${delta3d.className}`}>
              {delta3d.text}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-[var(--text-secondary)]">5D Δ Score:</span>
            <span className={`text-sm font-semibold ${delta5d.className}`}>
              {delta5d.text}
            </span>
          </div>
        </div>
      </div>

      {/* Dimension Grid - 5 Columns */}
      <div className="grid grid-cols-5 gap-4 mb-5">
        {/* Price Momentum */}
        <DimensionCard
          title="价格动能"
          subtitle="主要权重"
          score={stock.scores?.momentum ?? 0}
          scoreColor={getScoreColor(stock.scores?.momentum ?? 0)}
          metrics={momentumMetrics}
        />

        {/* Trend Structure */}
        <DimensionCard
          title="趋势结构"
          score={stock.scores?.trend ?? 0}
          scoreColor={getScoreColor(stock.scores?.trend ?? 0)}
          metrics={trendMetrics}
        />

        {/* Volume Confirmation */}
        <DimensionCard
          title="量价确认"
          score={stock.scores?.volume ?? 0}
          scoreColor={getScoreColor(stock.scores?.volume ?? 0)}
          metrics={volumeMetrics}
        />

        {/* Quality Filter */}
        <DimensionCard
          title="质量过滤"
          score={stock.scores?.quality ?? 0}
          scoreColor="blue"
          metrics={qualityMetrics}
        />

        {/* Options Coverage */}
        <DimensionCard
          title="期权覆盖"
          subtitle="20%权重"
          score={stock.scores?.options ?? 0}
          scoreColor="orange"
          metrics={optionsMetrics}
        />
      </div>
    </div>
  );
}
