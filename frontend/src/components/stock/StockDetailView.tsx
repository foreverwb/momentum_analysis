import React, { useEffect, useMemo, useState } from 'react';
import { useStockDetail } from '../../hooks/useData';
import type { StockDetail } from '../../types';
import { ThresholdCard } from './ThresholdCard';
import { ScoreBreakdownPanel } from './ScoreBreakdownPanel';
import { OptionsOverlayTab } from './OptionsOverlayTab';
import { RelativeTrendChart, type RelativeTrendSeries } from '../chart';
import * as api from '../../services/api';

interface StockDetailViewProps {
  symbol: string;
  onBack: () => void;
}

const TREND_COLORS = ['#22c55e', '#3b82f6', '#8b5cf6', '#f59e0b', '#14b8a6', '#e11d48'];
const TREND_METRIC_OPTIONS = [
  { value: 'relative', label: '相对走势' },
  { value: 'sma20', label: '20DMA' },
  { value: 'return20d', label: '20D收益' },
  { value: 'score', label: '综合评分' },
];

const STOCK_TREND_CACHE_TTL_MS = 60 * 1000;
const stockTrendCache = new Map<string, {
  cachedAt: number;
  dates: string[];
  series: RelativeTrendSeries[];
  priceSeries: RelativeTrendSeries[];
  sma20Series: RelativeTrendSeries[];
}>();

const toTrendCacheKey = (
  symbol: string,
  period: '5d' | '20d' | '63d',
  metric: 'relative' | 'sma20' | 'return20d' | 'score'
): string => `${symbol.trim().toUpperCase()}|${period}|${metric}`;

const hasValidSeriesValues = (values: Array<number | null> | undefined): boolean => {
  return Array.isArray(values) && values.some((value) => typeof value === 'number' && Number.isFinite(value));
};

const hasRequiredSymbolsData = (
  rawSeries: Array<{ symbol: string; values: Array<number | null> }> | undefined,
  requiredSymbols: string[]
): boolean => {
  if (requiredSymbols.length === 0) {
    return true;
  }
  if (!Array.isArray(rawSeries)) {
    return false;
  }
  return requiredSymbols.every((symbol) => {
    const matched = rawSeries.find((item) => item.symbol?.toUpperCase?.() === symbol);
    return matched ? hasValidSeriesValues(matched.values) : false;
  });
};

export function StockDetailView({ symbol, onBack }: StockDetailViewProps) {
  const { data: stock, isLoading, error } = useStockDetail(symbol);
  // 修复：添加 'options' 作为第三个Tab选项
  const [activeTab, setActiveTab] = useState<'overview' | 'breakdown' | 'options'>('overview');
  const [trendPeriod, setTrendPeriod] = useState<'5d' | '20d' | '63d'>('20d');
  const [trendMetric, setTrendMetric] = useState<'relative' | 'sma20' | 'return20d' | 'score'>('relative');
  const [trendDates, setTrendDates] = useState<string[]>([]);
  const [trendSeries, setTrendSeries] = useState<RelativeTrendSeries[]>([]);
  const [trendPriceSeries, setTrendPriceSeries] = useState<RelativeTrendSeries[]>([]);
  const [trendSma20Series, setTrendSma20Series] = useState<RelativeTrendSeries[]>([]);
  const [isTrendLoading, setIsTrendLoading] = useState(false);
  const [trendError, setTrendError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol || symbol.trim() === '') {
      return;
    }
    let cancelled = false;
    const normalizedSymbol = symbol.trim().toUpperCase();
    const periodValue = trendPeriod === '5d' ? 5 : trendPeriod === '20d' ? 20 : 63;
    const reservedColors: Record<string, string> = {
      [normalizedSymbol]: '#22c55e',
      SPY: '#94a3b8',
      QQQ: '#64748b',
    };
    const cacheKey = toTrendCacheKey(normalizedSymbol, trendPeriod, trendMetric);
    const cached = stockTrendCache.get(cacheKey);
    if (cached && Date.now() - cached.cachedAt < STOCK_TREND_CACHE_TTL_MS) {
      setTrendDates(cached.dates);
      setTrendSeries(cached.series);
      setTrendPriceSeries(cached.priceSeries);
      setTrendSma20Series(cached.sma20Series);
      setTrendError(null);
      setIsTrendLoading(false);
      return;
    }
    if (cached) {
      setTrendDates(cached.dates);
      setTrendSeries(cached.series);
      setTrendPriceSeries(cached.priceSeries);
      setTrendSma20Series(cached.sma20Series);
    }

    setIsTrendLoading(true);
    setTrendError(null);

    const loadTrendData = async () => {
      try {
        const marketSymbols = ['SPY', 'QQQ'];
        const warmupPromise =
          trendMetric === 'score'
            ? null
            : api.syncPriceDataForSymbols(marketSymbols).catch((syncError) => {
                console.warn('Market trend data warmup failed:', syncError);
                return null;
              });

        const withSeriesColors = (
          seriesItems: Array<{ symbol: string; values: Array<number | null> }> | undefined
        ): RelativeTrendSeries[] => {
          let paletteIndex = 0;
          const usedColors = new Set(Object.values(reservedColors));
          return (seriesItems || []).map((item) => {
            const key = item.symbol?.toUpperCase?.() ?? '';
            if (reservedColors[key]) {
              return {
                symbol: item.symbol,
                values: item.values,
                color: reservedColors[key],
              };
            }
            let attempts = 0;
            while (
              usedColors.has(TREND_COLORS[paletteIndex % TREND_COLORS.length]) &&
              attempts < TREND_COLORS.length
            ) {
              paletteIndex += 1;
              attempts += 1;
            }
            const color = TREND_COLORS[paletteIndex % TREND_COLORS.length];
            usedColors.add(color);
            paletteIndex += 1;
            return {
              symbol: item.symbol,
              values: item.values,
              color,
            };
          });
        };

        let resp = await api.getStockTrendComparison(normalizedSymbol, periodValue, trendMetric);
        if (
          trendMetric !== 'score' &&
          !hasRequiredSymbolsData(resp.price_series || resp.series, marketSymbols) &&
          warmupPromise
        ) {
          await warmupPromise;
          if (cancelled) return;
          resp = await api.getStockTrendComparison(normalizedSymbol, periodValue, trendMetric);
        }
        if (cancelled) return;
        const baseSeriesRaw =
          trendMetric === 'sma20' && Array.isArray(resp.deviation_series)
            ? resp.deviation_series
            : resp.series;
        const seriesWithColors = withSeriesColors(baseSeriesRaw);
        const priceSeriesWithColors =
          trendMetric === 'sma20' ? withSeriesColors(resp.price_series) : [];
        const sma20SeriesWithColors =
          trendMetric === 'sma20' ? withSeriesColors(resp.sma20_series) : [];
        setTrendDates(resp.dates || []);
        setTrendSeries(seriesWithColors);
        setTrendPriceSeries(priceSeriesWithColors);
        setTrendSma20Series(sma20SeriesWithColors);
        stockTrendCache.set(cacheKey, {
          cachedAt: Date.now(),
          dates: resp.dates || [],
          series: seriesWithColors,
          priceSeries: priceSeriesWithColors,
          sma20Series: sma20SeriesWithColors,
        });
      } catch (e) {
        if (cancelled) return;
        setTrendDates([]);
        setTrendSeries([]);
        setTrendPriceSeries([]);
        setTrendSma20Series([]);
        setTrendError(e instanceof Error ? e.message : '走势数据加载失败');
      } finally {
        if (cancelled) return;
        setIsTrendLoading(false);
      }
    };

    void loadTrendData();

    return () => {
      cancelled = true;
    };
  }, [symbol, trendPeriod, trendMetric]);

  const trendValueFormatter = React.useMemo(() => {
    if (trendMetric === 'sma20') {
      return (value: number) => `${value.toFixed(2)}%`;
    }
    if (trendMetric === 'score') {
      return (value: number) => value.toFixed(1);
    }
    return (value: number) => `${value.toFixed(1)}%`;
  }, [trendMetric]);

  const trendSymbolRoleMap = useMemo(() => {
    const map: Record<string, 'market' | 'sector' | 'industry' | 'stock' | 'other'> = {
      SPY: 'market',
      QQQ: 'market',
      IWM: 'market',
      DIA: 'market',
      [symbol.trim().toUpperCase()]: 'stock',
    };
    if (stock?.sector) {
      map[stock.sector.toUpperCase()] = 'sector';
    }
    (stock?.industryEtfs || []).forEach((etfSymbol) => {
      if (!etfSymbol) return;
      map[etfSymbol.toUpperCase()] = 'industry';
    });
    return map;
  }, [stock?.industryEtfs, stock?.sector, symbol]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[var(--accent-blue)] mx-auto mb-4" />
          <p className="text-[var(--text-muted)]">加载中...</p>
        </div>
      </div>
    );
  }

  if (error || !stock) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <p className="text-[var(--accent-red)] text-lg mb-2">加载失败</p>
          <p className="text-[var(--text-muted)] mb-4">
            {error instanceof Error ? error.message : '无法加载股票详情'}
          </p>
          <button
            onClick={onBack}
            className="px-4 py-2 bg-[var(--accent-blue)] text-white rounded-lg hover:opacity-90 transition-opacity"
          >
            返回列表
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto">

      {/* Stock Header */}
      <StockHeader stock={stock} />

      {/* Quick Stats Bar */}
      <QuickStatsBar stock={stock} />

      {/* Relative Trend Comparison */}
      <div className="mb-6">
        {trendError && (
          <div className="text-sm text-[var(--accent-red)] mb-2">
            走势对比加载失败：{trendError}
          </div>
        )}
        <RelativeTrendChart
          title="走势对比"
          dates={trendDates}
          series={trendSeries}
          comparisonPriceSeries={trendPriceSeries}
          comparisonSma20Series={trendSma20Series}
          period={trendPeriod}
          onPeriodChange={setTrendPeriod}
          metric={trendMetric}
          metricOptions={TREND_METRIC_OPTIONS}
          onMetricChange={(value) => setTrendMetric(value as typeof trendMetric)}
          valueFormatter={trendValueFormatter}
          baseSymbol="SPY"
          symbolRoleMap={trendSymbolRoleMap}
        />
        {isTrendLoading && (
          <div className="text-xs text-[var(--text-muted)] mt-2">走势数据加载中...</div>
        )}
      </div>

      {/* Threshold Check */}
      {stock.thresholds && (
        <ThresholdCard
          thresholds={stock.thresholds}
          allPass={stock.thresholdsPass ?? false}
        />
      )}

      {/* Tabs - 修复：添加期权覆盖Tab */}
      <div className="mb-6">
        <div className="flex gap-2 border-b border-[var(--border-light)]">
          <button
            className={`px-6 py-3 text-sm font-medium transition-colors ${
              activeTab === 'overview'
                ? 'text-[var(--accent-blue)] border-b-2 border-[var(--accent-blue)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            onClick={() => setActiveTab('overview')}
          >
            综合概览
          </button>
          <button
            className={`px-6 py-3 text-sm font-medium transition-colors ${
              activeTab === 'breakdown'
                ? 'text-[var(--accent-blue)] border-b-2 border-[var(--accent-blue)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            onClick={() => setActiveTab('breakdown')}
          >
            四维评分详情
          </button>
          <button
            className={`px-6 py-3 text-sm font-medium transition-colors ${
              activeTab === 'options'
                ? 'text-[var(--accent-blue)] border-b-2 border-[var(--accent-blue)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            onClick={() => setActiveTab('options')}
          >
            期权覆盖
          </button>
        </div>
      </div>

      {/* Tab Content - 修复：添加期权覆盖Tab内容 */}
      {activeTab === 'overview' ? (
        <OverviewTab stock={stock} />
      ) : activeTab === 'breakdown' ? (
        <BreakdownTab stock={stock} />
      ) : (
        <OptionsOverlayTab stock={stock} />
      )}
    </div>
  );
}

// Stock Header Component
function StockHeader({ stock }: { stock: StockDetail }) {
  const formatPrice = (price?: number) => {
    if (price === null || price === undefined) return '--';
    return `$${price.toFixed(2)}`;
  };

  const formatChange = (change?: number, changePercent?: number) => {
    if (change === null || change === undefined) return '--';
    const sign = change >= 0 ? '+' : '';
    const percentText = changePercent !== null && changePercent !== undefined
      ? ` (${sign}${changePercent.toFixed(2)}%)`
      : '';
    return `${sign}${change.toFixed(2)}${percentText}`;
  };

  const getChangeColor = (change?: number) => {
    if (change === null || change === undefined) return 'var(--text-muted)';
    return change >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  };

  const totalScoreValue = stock.scoreTotal ?? stock.totalScore;
  const displayRank = (stock as StockDetail & { rank?: number }).rank;

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6 mb-6">
      <div className="flex items-start justify-between">
        {/* Left: Stock Info */}
        <div className="flex items-center gap-4">
          {/* Rank Badge */}
          <div 
            className="w-16 h-16 rounded-full flex items-center justify-center text-white text-2xl font-bold"
            style={{ background: 'linear-gradient(135deg, var(--accent-purple), #a855f7)' }}
          >
            {displayRank || '?'}
          </div>

          {/* Stock Title */}
          <div>
            <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">
              {stock.symbol}
            </h1>
            <p className="text-lg text-[var(--text-secondary)] mb-3">
              {stock.name || '--'}
            </p>
            <div className="flex items-center gap-3 text-sm">
              <span className="px-3 py-1 bg-blue-100 text-[var(--accent-blue)] rounded-full">
                板块: {stock.sector || '--'}
              </span>
              <span className="px-3 py-1 bg-purple-100 text-[var(--accent-purple)] rounded-full">
                行业: {stock.industry || '--'}
              </span>
              {stock.marketCap && (
                <span className="px-3 py-1 bg-gray-100 text-[var(--text-secondary)] rounded-full">
                  市值: ${(stock.marketCap / 1e9).toFixed(1)}B
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right: Price Info */}
        <div className="text-right">
          <div className="text-4xl font-bold text-[var(--text-primary)] mb-2">
            {formatPrice(stock.price)}
          </div>
          <div 
            className="text-lg font-semibold"
            style={{ color: getChangeColor(stock.change) }}
          >
            {formatChange(stock.change, stock.changePercent)}
          </div>
        </div>
      </div>

      {/* Score Row */}
      <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-[var(--border-light)]">
        <ScoreItem
          label="综合得分"
          value={totalScoreValue}
          isPrimary
        />
        <ScoreItem
          label="价格动能"
          value={stock.momentumScore}
          subtext="42.25% 权重"
        />
        <ScoreItem
          label="趋势结构"
          value={stock.technicalScore}
          subtext="22.75% 权重"
        />
        <ScoreItem
          label="期权覆盖"
          value={stock.optionsScore}
          subtext="20% 权重"
        />
      </div>
    </div>
  );
}

function ScoreItem({ 
  label, 
  value, 
  subtext, 
  isPrimary 
}: { 
  label: string; 
  value?: number; 
  subtext?: string; 
  isPrimary?: boolean;
}) {
  const getScoreColor = (score?: number) => {
    if (score === null || score === undefined) return 'var(--text-muted)';
    if (score >= 60) return 'var(--accent-green)';
    if (score >= 40) return 'var(--accent-amber)';
    return 'var(--accent-blue)';
  };

  return (
    <div className="text-center">
      <div className="text-xs text-[var(--text-muted)] mb-1">{label}</div>
      <div 
        className={`${isPrimary ? 'text-3xl' : 'text-2xl'} font-bold`}
        style={{ color: getScoreColor(value) }}
      >
        {value?.toFixed(1) ?? '--'}
      </div>
      {subtext && (
        <div className="text-xs text-[var(--text-muted)] mt-1">{subtext}</div>
      )}
    </div>
  );
}

// Quick Stats Bar Component - 修复：改进数据显示
function QuickStatsBar({ stock }: { stock: StockDetail }) {
  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined) return '--';
    return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
  };

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined) return '--';
    return value.toFixed(2);
  };

  // 修复：获取scoreBreakdown中的数据
  const momentumData = stock.scoreBreakdown?.momentum?.data;
  const optionsData = stock.scoreBreakdown?.options?.data;

  const stats = [
    { label: '20日收益', value: formatPercent(momentumData?.return_20d ?? stock.return20d) },
    { label: '63日收益', value: formatPercent(momentumData?.return_63d ?? stock.return63d) },
    { label: '相对强度', value: formatNumber(momentumData?.rs_20d ?? stock.rs20d) },
    { label: 'RSI', value: formatNumber(stock.rsi) },
    { label: 'IVR', value: formatNumber(optionsData?.ivr ?? stock.ivr) },
    { label: '量比', value: formatNumber(stock.volumeRatio) },
  ];

  return (
    <div className="grid grid-cols-6 gap-4 mb-6">
      {stats.map((stat, index) => (
        <div 
          key={index}
          className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-lg p-4 text-center"
        >
          <div className="text-xs text-[var(--text-muted)] mb-1">
            {stat.label}
          </div>
          <div className="text-lg font-bold text-[var(--text-primary)]">
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  );
}

// Overview Tab Component - 修复：改进数据显示逻辑
function OverviewTab({ stock }: { stock: StockDetail }) {
  // 修复：从scoreBreakdown获取数据
  const technicalData = stock.scoreBreakdown?.technical?.data;
  const volumeData = stock.scoreBreakdown?.volume?.data;
  const optionsData = stock.scoreBreakdown?.options?.data;

  const formatPrice = (value?: number | null) => {
    if (value === null || value === undefined || value === 0) return '$--';
    return `$${value.toFixed(2)}`;
  };

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return value.toLocaleString();
  };
  const toMetricNumber = (value: unknown): number | undefined => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    return undefined;
  };
  const metricsRaw = (stock.metrics ?? {}) as Record<string, unknown>;

  const latestVolume =
    stock.volume ??
    (typeof volumeData?.volume === 'number' ? volumeData.volume : undefined);
  const avgVolume =
    stock.avgVolume ??
    (typeof volumeData?.avg_volume === 'number' ? volumeData.avg_volume : undefined);
  const impliedVolatility =
    optionsData?.implied_volatility ??
    stock.impliedVolatility ??
    toMetricNumber(metricsRaw.iv30);
  const openInterest =
    optionsData?.open_interest ??
    stock.openInterest ??
    toMetricNumber(metricsRaw.openInterest) ??
    toMetricNumber(metricsRaw.open_interest) ??
    null;

  const metrics = [
    { label: '当前价格', value: formatPrice(technicalData?.price ?? stock.price) },
    { label: '20日均线', value: formatPrice(technicalData?.sma20 ?? stock.sma20) },
    { label: '50日均线', value: formatPrice(technicalData?.sma50 ?? stock.sma50) },
    { label: '200日均线', value: formatPrice(technicalData?.sma200 ?? stock.sma200) },
    { label: '成交量', value: formatNumber(latestVolume) },
    { label: '平均成交量', value: formatNumber(avgVolume) },
    { label: '隐含波动率', value: impliedVolatility != null ? impliedVolatility.toFixed(2) : '--' },
    { label: '持仓量', value: formatNumber(openInterest) },
  ];

  return (
    <div>
      <h3 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
        关键指标数据
      </h3>
      <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6">
        <div className="grid grid-cols-4 gap-4">
          {metrics.map((metric, index) => (
            <div 
              key={index}
              className="flex flex-col py-3 px-4 bg-[var(--bg-secondary)] rounded-lg"
            >
              <span className="text-xs text-[var(--text-muted)] mb-1">
                {metric.label}
              </span>
              <span className="text-base font-semibold text-[var(--text-primary)]">
                {metric.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Breakdown Tab Component
function BreakdownTab({ stock }: { stock: StockDetail }) {
  if (!stock.scoreBreakdown) {
    return (
      <div className="text-center py-12">
        <p className="text-[var(--text-muted)]">暂无评分细分数据</p>
      </div>
    );
  }

  const { momentum, technical, volume, options } = stock.scoreBreakdown;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {/* Price Momentum */}
      {momentum && (
        <ScoreBreakdownPanel
          title="价格动能"
          icon="🔥"
          score={momentum.score}
          weight="42.25%"
          breakdown={momentum.data.score_breakdown || {}}
          data={{
            return_20d: momentum.data.return_20d,
            return_63d: momentum.data.return_63d,
            rs_20d: momentum.data.rs_20d,
          }}
          description="基于短期和中期价格表现的动能评估"
          compact
        />
      )}

      {/* Trend Structure */}
      {technical && (
        <ScoreBreakdownPanel
          title="趋势结构"
          icon="📈"
          score={technical.score}
          weight="22.75%"
          breakdown={technical.data.score_breakdown || {}}
          data={{
            price: technical.data.price,
            sma20: technical.data.sma20,
            sma50: technical.data.sma50,
            sma200: technical.data.sma200,
            rsi: technical.data.rsi,
            dist_from_52w_high: technical.data.dist_from_52w_high,
          }}
          description="基于技术指标和均线系统的趋势评估"
          compact
        />
      )}

      {/* Volume Confirmation */}
      {volume && (
        <ScoreBreakdownPanel
          title="量价确认"
          icon="📊"
          score={volume.score}
          weight="15%"
          breakdown={{}}
          data={{
            volume: volume.data.volume,
            avg_volume: volume.data.avg_volume,
            volume_ratio: volume.data.volume_ratio,
          }}
          description="基于成交量变化的确认信号"
          compact
        />
      )}

      {/* Options Coverage */}
      {options && (
        <ScoreBreakdownPanel
          title="期权覆盖"
          icon="🧭"
          score={options.score}
          weight="20%"
          breakdown={{}}
          data={{
            heat_type: options.data.heat_type,
            heat_score: options.data.heat_score,
            risk_score: options.data.risk_score,
            ivr: options.data.ivr,
            implied_volatility: options.data.implied_volatility,
            open_interest: options.data.open_interest,
          }}
          description="基于期权市场活动和波动率的风险评估"
          compact
        />
      )}
    </div>
  );
}
