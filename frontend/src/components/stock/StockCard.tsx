import React, { memo, useMemo, useCallback } from 'react';
import type { Stock, StockMetrics } from '../../types';
import { DimensionCard } from './DimensionCard';

interface StockCardProps {
  stock: Stock;
  rank: number;
  onClick?: () => void;
  // Compare mode props
  isCompareMode?: boolean;
  isSelected?: boolean;
  onToggleSelect?: (symbol: string) => void;
}

// ============================================================================
// 格式化工具函数（移到组件外部）
// ============================================================================

const formatPercent = (value?: number | null, digits = 1, withSign = true): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value > 0 && withSign ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
};

const formatNumber = (value?: number | null, digits = 2, withSign = false): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value > 0 && withSign ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
};

const formatMultiple = (value?: number | null, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value.toFixed(digits)}x`;
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

// ============================================================================
// StockCard Component (Optimized with memo)
// ============================================================================

/**
 * StockCard - 股票卡片组件
 * 
 * 性能优化:
 * - 使用 React.memo 避免不必要的重渲染
 * - 工具函数移到组件外部
 * - 使用 useMemo 缓存复杂计算
 * - 使用 useCallback 缓存事件处理函数
 */
export const StockCard = memo(function StockCard({ 
  stock, 
  rank, 
  onClick, 
  isCompareMode = false, 
  isSelected = false, 
  onToggleSelect 
}: StockCardProps) {
  // 早期返回
  if (!stock) return null;

  // 使用 useCallback 缓存点击处理函数
  const handleClick = useCallback(() => {
    if (!stock?.id && !stock?.symbol) return;
    
    // In compare mode, toggle selection instead of navigating to detail
    if (isCompareMode && onToggleSelect) {
      onToggleSelect(stock.symbol);
    } else {
      onClick?.();
    }
  }, [stock?.id, stock?.symbol, isCompareMode, onToggleSelect, onClick]);

  const handleCheckboxClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (onToggleSelect) {
      onToggleSelect(stock.symbol);
    }
  }, [onToggleSelect, stock.symbol]);

  const scoreTotal = stock.scoreTotal ?? stock.totalScore ?? null;
  const momentumScore = stock.scores?.momentum ?? stock.momentumScore ?? 0;
  const trendScore = stock.scores?.trend ?? stock.technicalScore ?? 0;
  const volumeScore = stock.scores?.volume ?? stock.volumeScore ?? 0;
  const qualityScore = stock.scores?.quality ?? 0;
  const optionsScore = stock.scores?.options ?? stock.optionsScore ?? 0;

  const delta3dValue = stock.changes?.delta3d ?? null;
  const delta5dValue = stock.changes?.delta5d ?? null;
  const delta3d = useMemo(() => formatDelta(delta3dValue), [delta3dValue]);
  const delta5d = useMemo(() => formatDelta(delta5dValue), [delta5dValue]);

  const metrics = (stock.metrics ?? {}) as StockMetrics;
  const industryEtfs = stock.industryEtfs && stock.industryEtfs.length > 0
    ? stock.industryEtfs
    : stock.industry
      ? [stock.industry]
      : [];
  const betaValue = metrics?.beta ?? stock.beta;
  const rsiValue = metrics?.rsi ?? stock.rsi;
  
  // 使用 useMemo 缓存指标数组
  const momentumMetrics = useMemo(() => [
    { label: '20D收益', value: formatPercent(metrics.return20d ?? stock.return20d, 1), variant: 'highlight' as const },
    { label: '20D收益(去3日)', value: formatPercent(metrics.return20dEx3d, 1) },
    { label: '63D收益', value: formatPercent(metrics.return63d ?? stock.return63d, 1), variant: 'highlight' as const },
    { label: '相对行业强度', value: formatNumber(metrics.relativeStrength ?? stock.rs20d, 2) },
    { label: '距20日高点', value: formatPercent(metrics.distanceToHigh20d, 1, false), variant: 'warning' as const },
    { label: '放量倍数', value: formatMultiple(metrics.volumeMultiple ?? metrics.breakoutVolume, 2), variant: 'warning' as const }
  ], [metrics.breakoutVolume, metrics.distanceToHigh20d, metrics.relativeStrength, metrics.return20d, metrics.return20dEx3d, metrics.return63d, metrics.volumeMultiple, stock.return20d, stock.return63d, stock.rs20d]);

  const maAlignmentValue = metrics.maAlignment ?? 'N/A';
  const maAlignmentVariant = maAlignmentValue === 'N/A' ? 'muted' as const : undefined;
  
  const trendMetrics = useMemo(() => [
    { label: '均线排列', value: maAlignmentValue, variant: maAlignmentVariant },
    { label: '20DMA斜率', value: formatNumber(metrics.sma20Slope, 2, true), variant: 'highlight' as const },
    { label: '趋势持续度', value: formatPercent(metrics.trendPersistence, 0, false) }
  ], [maAlignmentValue, maAlignmentVariant, metrics.sma20Slope, metrics.trendPersistence]);

  const volumeMetrics = useMemo(() => [
    { label: '突破放量', value: formatMultiple(metrics.breakoutVolume, 2) },
    { label: '量比结构', value: formatNumber(metrics.volumeRatio ?? stock.volumeRatio, 2) },
    { label: 'OBV趋势', value: metrics.obvTrend ?? 'Neutral', variant: metrics.obvTrend ? undefined : 'muted' as const }
  ], [metrics.breakoutVolume, metrics.obvTrend, metrics.volumeRatio, stock.volumeRatio]);

  const overheatValue = metrics.overheat ?? 'Normal';
  const overheatVariant = overheatValue === 'Hot' ? 'warning' as const : undefined;
  const qualityMetrics = useMemo(() => [
    { label: '20D回撤', value: formatPercent(metrics.maxDrawdown20d, 1, true), variant: 'highlight' as const },
    { label: 'ATR%', value: formatPercent(metrics.atrPercent, 1, false), variant: 'highlight' as const },
    { label: '偏离20MA', value: formatPercent(metrics.deviationFrom20ma, 1, true), variant: 'highlight' as const },
    { label: '过热程度', value: overheatValue, variant: overheatVariant }
  ], [metrics.maxDrawdown20d, metrics.atrPercent, metrics.deviationFrom20ma, overheatValue, overheatVariant]);

  const optionsHeatValue = metrics.optionsHeat ?? 'Medium';
  const optionsHeatVariant = optionsHeatValue === 'High' ? 'warning' as const : undefined;
  const optionsMetrics = useMemo(() => [
    { label: '热度', value: optionsHeatValue, variant: optionsHeatVariant },
    { label: '相对成交', value: formatMultiple(metrics.optionsRelVolume, 2) },
    { label: 'IVR', value: formatNumber(metrics.ivr ?? stock.ivr, 0) },
    { label: 'IV30', value: formatNumber(metrics.iv30 ?? stock.impliedVolatility, 2) }
  ], [metrics.iv30, metrics.ivr, metrics.optionsRelVolume, optionsHeatValue, optionsHeatVariant, stock.impliedVolatility, stock.ivr]);

  const comparisonItems = useMemo(() => {
    if (stock.comparisons && stock.comparisons.length > 0) {
      return stock.comparisons;
    }

    const items = [];
    for (const symbol of industryEtfs) {
      items.push({ symbol, type: 'industry' as const });
    }
    if (stock.sector) {
      items.push({
        symbol: stock.sector,
        type: 'sector' as const,
        rs20d: metrics.relativeStrengthDiff ?? stock.rs20d ?? undefined
      });
    }
    items.push({ symbol: 'SPY', type: 'market' as const });
    items.push({ symbol: 'QQQ', type: 'market' as const });
    return items;
  }, [stock.comparisons, industryEtfs, stock.sector, metrics.relativeStrengthDiff, stock.rs20d]);

  return (
    <div 
      className={`bg-[var(--bg-primary)] border rounded-[var(--radius-lg)] p-6 mb-5 cursor-pointer hover:shadow-md transition-all relative ${
        isSelected 
          ? 'border-[var(--accent-blue)] bg-blue-50/20' 
          : 'border-[var(--border-light)]'
      }`}
      onClick={handleClick}
    >
      {/* Compare Mode Checkbox */}
      {isCompareMode && (
        <div 
          className={`absolute top-5 right-5 w-6 h-6 border-2 rounded-md flex items-center justify-center cursor-pointer transition-all ${
            isSelected
              ? 'bg-[var(--accent-blue)] border-[var(--accent-blue)]'
              : 'border-[var(--border-medium)] hover:border-[var(--accent-blue)]'
          }`}
          onClick={handleCheckboxClick}
        >
          {isSelected && (
            <span className="text-white text-sm font-bold">✓</span>
          )}
        </div>
      )}

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
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-[var(--text-secondary)]">
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">板块:</span>
                <span className="text-[var(--accent-blue)]">{stock.sector ?? '--'}</span>
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">行业:</span>
                <span className="text-[var(--accent-purple)]">
                  {industryEtfs.length > 0 ? industryEtfs.join(' | ') : '--'}
                </span>
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">BETA</span>
                <span className="text-[var(--accent-green)] font-medium">
                  {formatNumber(betaValue, 1)}
                </span>
              </span>
              <span className="flex items-center gap-1">
                <span className="text-[var(--text-muted)]">RSI</span>
                <span className="text-[var(--accent-green)] font-medium">
                  {formatNumber(rsiValue, 0, false)}
                </span>
              </span>
            </div>
          </div>
        </div>

        {/* Right: Score Box */}
        <div className="text-right">
          <div className="text-xs text-[var(--text-muted)] mb-1">综合得分</div>
          <div className="text-[40px] font-bold text-[var(--text-primary)] leading-none">
            {scoreTotal?.toFixed(1) ?? '--'}
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
          score={momentumScore}
          scoreColor={getScoreColor(momentumScore)}
          metrics={momentumMetrics}
        />

        {/* Trend Structure */}
        <DimensionCard
          title="趋势结构"
          score={trendScore}
          scoreColor={getScoreColor(trendScore)}
          metrics={trendMetrics}
        />

        {/* Volume Confirmation */}
        <DimensionCard
          title="量价确认"
          score={volumeScore}
          scoreColor={getScoreColor(volumeScore)}
          metrics={volumeMetrics}
        />

        {/* Quality Filter */}
        <DimensionCard
          title="质量过滤"
          score={qualityScore}
          scoreColor="blue"
          metrics={qualityMetrics}
        />

        {/* Options Coverage */}
        <DimensionCard
          title="期权覆盖"
          subtitle="20%权重"
          score={optionsScore}
          scoreColor="orange"
          metrics={optionsMetrics}
        />
      </div>

      {comparisonItems.length > 0 && (
        <div className="flex flex-nowrap gap-4 w-full overflow-x-auto pb-1">
          {comparisonItems.map((item, idx) => (
            <ComparisonCard
              key={`${item.symbol}-${item.type}-${idx}`}
              symbol={item.symbol}
              type={item.type}
              rs20d={item.rs20d}
              sma20Slope={item.sma20Slope}
              beta={item.beta ?? betaValue}
            />
          ))}
        </div>
      )}
    </div>
  );
})

interface ComparisonCardProps {
  symbol: string;
  type: 'industry' | 'sector' | 'market';
  rs20d?: number | null;
  sma20Slope?: number | null;
  beta?: number | null;
}

function ComparisonCard({ symbol, type, rs20d, sma20Slope, beta }: ComparisonCardProps) {
  const labelMap = {
    industry: '行业ETF',
    sector: '板块ETF',
    market: '大盘'
  };
  const badgeClass = {
    industry: 'bg-blue-50 text-[var(--accent-blue)]',
    sector: 'bg-purple-50 text-[var(--accent-purple)]',
    market: 'bg-emerald-50 text-[var(--accent-green)]'
  };

  const rsValue = rs20d === null || rs20d === undefined ? '--' : formatPercent(rs20d, 1, true);
  const rsValueClass = rs20d === null || rs20d === undefined
    ? 'text-[var(--text-muted)]'
    : rs20d >= 0
      ? 'text-[var(--accent-green)]'
      : 'text-[var(--accent-red)]';
  const rsStatus = rs20d === null || rs20d === undefined
    ? { text: '--', className: 'text-[var(--text-muted)]' }
    : rs20d > 0
      ? { text: `✓ 跑赢${type === 'industry' ? '行业' : type === 'sector' ? '板块' : '大盘'}`, className: 'text-[var(--accent-green)]' }
      : rs20d < 0
        ? { text: `✗ 跑输${type === 'industry' ? '行业' : type === 'sector' ? '板块' : '大盘'}`, className: 'text-[var(--accent-red)]' }
        : { text: `— 持平${type === 'industry' ? '行业' : type === 'sector' ? '板块' : '大盘'}`, className: 'text-[var(--text-muted)]' };

  const dmaStatus = sma20Slope === null || sma20Slope === undefined
    ? { text: '--', className: 'text-[var(--text-muted)]' }
    : sma20Slope > 0
      ? { text: '✓ 向上', className: 'text-[var(--accent-green)]' }
      : sma20Slope < 0
        ? { text: '↘ 向下', className: 'text-[var(--accent-red)]' }
        : { text: '— 走平', className: 'text-[var(--text-muted)]' };

  return (
    <div className="bg-[var(--bg-secondary)] rounded-xl p-4 border border-[var(--border-light)] min-w-[220px] flex-1 basis-0">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-[var(--text-primary)]">{symbol}</div>
        <span className={`text-xs px-2 py-1 rounded-full ${badgeClass[type]}`}>
          {labelMap[type]}
        </span>
      </div>
      <div className="space-y-2 text-xs text-[var(--text-secondary)]">
        <div className="flex items-center justify-between">
          <span>相对强度 (20D)</span>
          <span className={`font-semibold ${rsValueClass}`}>{rsValue}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>RS状态</span>
          <span className={`font-semibold ${rsStatus.className}`}>{rsStatus.text}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>20DMA</span>
          <span className={`font-semibold ${dmaStatus.className}`}>{dmaStatus.text}</span>
        </div>
        {type === 'market' && (
          <div className="flex items-center justify-between">
            <span>Beta相关</span>
            <span className="font-semibold text-[var(--text-primary)]">
              {beta === null || beta === undefined ? '--' : beta.toFixed(2)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
