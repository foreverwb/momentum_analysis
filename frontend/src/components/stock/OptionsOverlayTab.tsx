// ============================================================================
// 文件: frontend/src/components/stock/OptionsOverlayTab.tsx
// 功能: 期权覆盖Tab组件，从后端获取实际期权数据
// 修复: 移除 mock 数据，实现从后端获取实时期权数据
// ============================================================================

import React, { useEffect, useState } from 'react';
import type { StockDetail, OptionsScoreData } from '../../types';
import { getOptionsOverlayData, type OptionsOverlayData, type OptionsPositioningData } from '../../services/api';

interface OptionsOverlayTabProps {
  stock: StockDetail;
}

export function OptionsOverlayTab({ stock }: OptionsOverlayTabProps) {
  const [optionsOverlay, setOptionsOverlay] = useState<OptionsOverlayData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 从 stock 对象中获取基础期权数据作为回退
  const baseOptionsData = stock.scoreBreakdown?.options?.data || {} as OptionsScoreData;
  const baseOptionsScore = stock.scoreBreakdown?.options?.score || stock.optionsScore || 0;

  // 从后端获取期权详细数据
  useEffect(() => {
    let cancelled = false;
    
    async function fetchOptionsData() {
      if (!stock.symbol) {
        setIsLoading(false);
        setOptionsOverlay(null);
        return;
      }
      
      setIsLoading(true);
      setError(null);
      setOptionsOverlay(null);
      
      try {
        const data = await getOptionsOverlayData(stock.symbol);
        if (!cancelled) {
          setOptionsOverlay(data);
        }
      } catch (err) {
        if (!cancelled) {
          // 如果 API 不存在或失败，使用 stock 中的基础数据
          console.warn('Options overlay API not available, using base data:', err);
          setError(err instanceof Error ? err.message : '期权覆盖数据加载失败');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }
    
    fetchOptionsData();
    
    return () => {
      cancelled = true;
    };
  }, [stock.symbol]);

  const metricsRaw = (stock.metrics ?? {}) as Record<string, unknown>;
  const toMetricNumber = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim() !== '') {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  };
  const normalizeHeatLabelToScore = (value: unknown): number | null => {
    if (typeof value !== 'string') return null;
    const normalized = value.trim().toLowerCase();
    if (!normalized) return null;
    if (normalized.includes('high') || normalized.includes('高')) return 85;
    if (normalized.includes('medium') || normalized.includes('中')) return 60;
    if (normalized.includes('low') || normalized.includes('低')) return 35;
    return null;
  };
  const normalizeHeatType = (value: unknown): string | null => {
    if (typeof value !== 'string') return null;
    const normalized = value.trim().toLowerCase();
    if (!normalized) return null;
    if (normalized.includes('trend')) return 'trend';
    if (normalized.includes('event')) return 'event';
    if (normalized.includes('hedge')) return 'hedge';
    return 'normal';
  };

  // 使用后端数据或回退到基础数据
  const heatScore =
    optionsOverlay?.heatScore ??
    baseOptionsData.heat_score ??
    stock.heatScore ??
    toMetricNumber(metricsRaw.heat_score) ??
    normalizeHeatLabelToScore(metricsRaw.optionsHeat) ??
    baseOptionsScore;
  const riskScore =
    optionsOverlay?.riskScore ??
    baseOptionsData.risk_score ??
    stock.riskScore ??
    toMetricNumber(metricsRaw.risk_score) ??
    (() => {
      const ivr = toMetricNumber(metricsRaw.ivr);
      return ivr == null ? null : Math.max(0, Math.min(100, 100 - ivr));
    })() ??
    baseOptionsScore;
  const optionsScore = optionsOverlay
    ? Math.round((heatScore + riskScore + (optionsOverlay.termStructureScore || 0)) / 3)
    : (baseOptionsScore > 0 ? baseOptionsScore : Math.round((heatScore + riskScore) / 2));
  const termStructureScore = optionsOverlay?.termStructureScore ?? (Math.round((optionsScore + heatScore) / 2) || 0);
  const heatType =
    optionsOverlay?.heatType ??
    baseOptionsData.heat_type ??
    stock.heatType ??
    normalizeHeatType(metricsRaw.heat_type) ??
    'normal';
  const normalizedHeatType = heatType.toLowerCase();

  // 获取热度类型显示
  const getHeatBadge = () => {
    const badges: Record<string, { label: string; icon: string; className: string }> = {
      trend: { label: '趋势热', icon: '🔥', className: 'bg-green-100 text-green-600' },
      event: { label: '事件热', icon: '⚡', className: 'bg-amber-100 text-amber-600' },
      hedge: { label: '对冲热', icon: '🛡️', className: 'bg-blue-100 text-blue-600' },
      normal: { label: '常规', icon: '📊', className: 'bg-gray-100 text-gray-600' },
    };
    return badges[normalizedHeatType] || badges.normal;
  };

  const badge = getHeatBadge();

  // 获取评分颜色
  const getScoreClass = (score: number): string => {
    if (score >= 80) return 'text-[var(--accent-green)]';
    if (score >= 60) return 'text-[var(--accent-blue)]';
    if (score >= 40) return 'text-[var(--accent-amber)]';
    return 'text-[var(--accent-red)]';
  };

  const formatValue = (value: any, fallback = '--') => {
    if (value === null || value === undefined) return fallback;
    if (typeof value === 'number') return value.toFixed(2);
    return String(value);
  };

  const formatOI = (value: number | null | undefined): string => {
    if (value === null || value === undefined) return '--';
    const absValue = Math.abs(value);
    if (absValue >= 1000000) {
      return `${value >= 0 ? '+' : ''}${(value / 1000000).toFixed(1)}M`;
    }
    if (absValue >= 1000) {
      return `${value >= 0 ? '+' : ''}${(value / 1000).toFixed(0)}K`;
    }
    return `${value >= 0 ? '+' : ''}${value}`;
  };

  const toNumber = (value: unknown): number | null => {
    if (value === null || value === undefined) return null;
    if (typeof value === 'number') {
      return Number.isNaN(value) ? null : value;
    }
    if (typeof value === 'string') {
      const cleaned = value.replace(/,/g, '').trim();
      if (!cleaned) return null;
      const normalized = cleaned.endsWith('%') ? cleaned.slice(0, -1).trim() : cleaned;
      const parsed = Number(normalized);
      return Number.isNaN(parsed) ? null : parsed;
    }
    return null;
  };
  const relativeNominalValue =
    toNumber(optionsOverlay?.relativeNominal) ??
    toNumber(metricsRaw.rel_notional) ??
    toNumber(metricsRaw.rel_notional_to_90d);
  const relativeVolumeValue =
    toNumber(optionsOverlay?.relativeVolume) ??
    toNumber(metricsRaw.rel_vol) ??
    toNumber(metricsRaw.rel_vol_to_90d) ??
    toNumber(metricsRaw.optionsRelVolume);
  const iv30ChangeValue =
    toNumber(optionsOverlay?.iv30Change) ??
    toNumber(metricsRaw.iv30_chg_pct ?? metricsRaw.iv30Change ?? metricsRaw.iv_change);
  const iv30ForSlope = toNumber(optionsOverlay?.iv30 ?? metricsRaw.iv30);
  const iv90ForSlope = toNumber(optionsOverlay?.iv90 ?? metricsRaw.iv90 ?? metricsRaw.iv90_futu);
  const slopeValue = (() => {
    const slopeFromApi = toNumber(optionsOverlay?.slope);
    if (slopeFromApi != null) return slopeFromApi;
    if (iv30ForSlope == null || iv90ForSlope == null || iv90ForSlope === 0) return null;
    return iv30ForSlope / iv90ForSlope;
  })();

  const normalizeBucketLabel = (value: string): string => {
    const trimmed = value.replace(/\s+/g, '');
    const normalized = trimmed
      .replace(/[天日]/gi, '')
      .replace(/[–—]/g, '-')
      .replace(/[~～]/g, '-')
      .replace(/[dD]/g, '')
      .replace(/至/g, '-');

    if (/^(0|1)-?7/.test(normalized)) return '0-7';
    if (/^8-?30/.test(normalized)) return '8-30';
    if (/^31-?90/.test(normalized)) return '31-90';
    return value;
  };

  const normalizePositioning = (raw: unknown): OptionsPositioningData[] => {
    const normalizeRow = (row: any, bucketFallback?: string): OptionsPositioningData | null => {
      if (typeof row === 'number') {
        if (!bucketFallback) return null;
        const bucket = normalizeBucketLabel(String(bucketFallback));
        return {
          bucket,
          callOI: null,
          putOI: null,
          netOI: row,
          delta3d: row,
          delta5d: null,
          trend: row >= 0 ? '偏多' : '偏空',
        };
      }
      if (!row || typeof row !== 'object') return null;
      const bucket = String(
        row.bucket ??
          row.term ??
          row.tenor ??
          row.term_bucket ??
          row.range ??
          row.label ??
          bucketFallback ??
          ''
      ).trim();
      if (!bucket) return null;
      const normalizedBucket = normalizeBucketLabel(bucket);

      const callOI = toNumber(
        row.callOI ?? row.call_oi ?? row.call_delta ?? row.callDelta ?? row.call_change ?? row.callChange ?? row.call
      );
      const putOI = toNumber(
        row.putOI ?? row.put_oi ?? row.put_delta ?? row.putDelta ?? row.put_change ?? row.putChange ?? row.put
      );
      const netOI = toNumber(
        row.netOI ?? row.net_oi ?? row.net_delta ?? row.netDelta ?? row.net_change ?? row.netChange ?? row.net
      );
      const delta3d = toNumber(row.delta3d ?? row.delta_3d ?? row.delta3D ?? row.delta_oi_3d);
      const delta5d = toNumber(row.delta5d ?? row.delta_5d ?? row.delta5D ?? row.delta_oi_5d);
      // Compatibility fix: old payload used 0/0 as placeholder when call/put split was unavailable.
      const placeholderSplit =
        callOI === 0 &&
        putOI === 0 &&
        [netOI, delta3d, delta5d].some((value) => typeof value === 'number' && value !== 0);
      const normalizedCallOI = placeholderSplit ? null : callOI;
      const normalizedPutOI = placeholderSplit ? null : putOI;
      const hasAny = [normalizedCallOI, normalizedPutOI, netOI, delta3d, delta5d].some((value) => typeof value === 'number');
      if (!hasAny) return null;

      const resolvedNet =
        netOI ??
        (typeof normalizedCallOI === 'number' && typeof normalizedPutOI === 'number'
          ? normalizedCallOI - normalizedPutOI
          : null);
      const trend =
        String(row.trend ?? row.signal ?? row.direction ?? row.bias ?? '').trim() ||
        (typeof resolvedNet === 'number'
          ? (resolvedNet >= 0 ? '偏多' : '偏空')
          : '中性');

      return {
        bucket: normalizedBucket,
        callOI: normalizedCallOI ?? null,
        putOI: normalizedPutOI ?? null,
        netOI: resolvedNet,
        delta3d: delta3d ?? resolvedNet,
        delta5d: delta5d ?? null,
        trend,
      };
    };

    if (!raw) return [];
    if (Array.isArray(raw)) {
      return raw.map((row) => normalizeRow(row)).filter(Boolean) as OptionsPositioningData[];
    }
    if (typeof raw === 'string') {
      try {
        return normalizePositioning(JSON.parse(raw));
      } catch {
        return [];
      }
    }
    if (typeof raw === 'object') {
      const maybeRow = normalizeRow(raw);
      if (maybeRow) return [maybeRow];
      return Object.entries(raw as Record<string, unknown>)
        .map(([bucket, row]) => normalizeRow(row, bucket))
        .filter(Boolean) as OptionsPositioningData[];
    }
    return [];
  };

  const metrics = (stock.metrics ?? {}) as Record<string, unknown>;
  const bucketFallbackList = () => {
    const bucketSources: Array<{ bucket: string; value: number | null }> = [
      { bucket: '0-7', value: toNumber(metrics.oi_bucket_0_7 ?? metrics.oiBucket0_7 ?? metrics.oi_0_7 ?? metrics.delta_oi_0_7) },
      { bucket: '8-30', value: toNumber(metrics.oi_bucket_8_30 ?? metrics.oiBucket8_30 ?? metrics.oi_8_30 ?? metrics.delta_oi_8_30) },
      { bucket: '31-90', value: toNumber(metrics.oi_bucket_31_90 ?? metrics.oiBucket31_90 ?? metrics.oi_31_90 ?? metrics.delta_oi_31_90) },
    ];
    return bucketSources
      .filter((item) => item.value !== null)
      .map((item) => ({
        bucket: item.bucket,
        callOI: null,
        putOI: null,
        netOI: item.value ?? 0,
        delta3d: item.value ?? 0,
        delta5d: null,
        trend: (item.value ?? 0) >= 0 ? '偏多' : '偏空',
      }));
  };

  // 从后端数据或生成默认持仓数据
  const getPositioningData = (): OptionsPositioningData[] => {
    const sources: OptionsPositioningData[] = [];
    sources.push(...normalizePositioning(optionsOverlay?.positioning));
    sources.push(...normalizePositioning(metrics.optionsPositioning));
    sources.push(...normalizePositioning(metrics.positioning));
    sources.push(...bucketFallbackList());

    if (!sources.length) {
      return [];
    }

    const completenessScore = (row: OptionsPositioningData): number => {
      let score = 0;
      if (typeof row.callOI === 'number') score += 1;
      if (typeof row.putOI === 'number') score += 1;
      if (typeof row.netOI === 'number') score += 1;
      if (typeof row.delta3d === 'number') score += 1;
      if (typeof row.delta5d === 'number') score += 1;
      return score;
    };

    const aggregated: Record<string, OptionsPositioningData> = {};
    sources.forEach((row) => {
      const bucketKey = normalizeBucketLabel(row.bucket);
      if (!aggregated[bucketKey]) {
        aggregated[bucketKey] = {
          bucket: bucketKey,
          callOI: null,
          putOI: null,
          netOI: null,
          delta3d: null,
          delta5d: null,
          trend: '中性',
        };
      }
      const current = aggregated[bucketKey];
      if (completenessScore(row) > completenessScore(current)) {
        aggregated[bucketKey] = {
          ...current,
          ...row,
          bucket: bucketKey,
          trend: row.trend || current.trend || '中性',
        };
        return;
      }
      if (current.callOI == null && row.callOI != null) current.callOI = row.callOI;
      if (current.putOI == null && row.putOI != null) current.putOI = row.putOI;
      if (current.netOI == null && row.netOI != null) current.netOI = row.netOI;
      if (current.delta3d == null && row.delta3d != null) current.delta3d = row.delta3d;
      if (current.delta5d == null && row.delta5d != null) current.delta5d = row.delta5d;
      if (!current.trend && row.trend) current.trend = row.trend;
    });

    return Object.values(aggregated).map((row) => ({
      ...row,
      trend: row.trend || (
        typeof row.netOI === 'number'
          ? row.netOI >= 0 ? '偏多' : '偏空'
          : '中性'
      ),
    }));
  };

  const positioningData = getPositioningData();
  const bucketOrder = ['0-7', '8-30', '31-90'];
  const bucketLabels: Record<string, string> = {
    '0-7': '0-7天',
    '8-30': '8-30天',
    '31-90': '31-90天',
  };
  const orderedPositioning = [
    ...bucketOrder.map((bucket) => {
      const existing = positioningData.find((row) => row.bucket === bucket);
      if (existing) return existing;
      return {
        bucket,
        callOI: null,
        putOI: null,
        netOI: null,
        delta3d: null,
        delta5d: null,
        trend: '--',
      } as OptionsPositioningData;
    }),
    ...positioningData.filter((row) => !bucketOrder.includes(row.bucket)),
  ];

  const hasPositioningData = orderedPositioning.some((row) => (
    typeof row.callOI === 'number' ||
    typeof row.putOI === 'number' ||
    typeof row.netOI === 'number' ||
    typeof row.delta3d === 'number' ||
    typeof row.delta5d === 'number'
  ));
  const termStructureInterpretation = optionsOverlay?.termStructureInterpretation ?? (() => {
    if (typeof slopeValue !== 'number') {
      if (iv30ForSlope != null && (iv90ForSlope == null || iv90ForSlope === 0)) {
        return 'IV90缺失（90天期限样本不足）';
      }
      return '--';
    }
    const slope = slopeValue;
    if (slope >= 1.1) return '短端昂贵（倒挂/恐慌）';
    if (slope < 0.9) return '正常陡峭结构';
    return '正常';
  })();

  return (
    <div className="space-y-6">
      {/* 期权覆盖概述 */}
      <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h3 className="text-xl font-semibold text-[var(--text-primary)] mb-2">
              期权/波动率确认
            </h3>
            <div className="flex gap-2 mt-3">
              <span className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium ${badge.className}`}>
                {badge.icon} {badge.label}
              </span>
              {optionsOverlay?.dataSource && (
                <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium bg-blue-50 text-blue-600">
                  📡 {optionsOverlay.dataSource}
                </span>
              )}
              {error && (
                <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium bg-red-50 text-red-600">
                  ⚠️ {error}
                </span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className={`text-5xl font-bold ${getScoreClass(optionsScore)}`}>
              {optionsScore.toFixed(0)}
            </div>
            {isLoading && (
              <div className="text-xs text-[var(--text-muted)] mt-1">加载中...</div>
            )}
          </div>
        </div>

        {/* 三列卡片 */}
        <div className="grid grid-cols-3 gap-4">
          {/* 热度卡片 */}
          <div className="bg-[var(--bg-secondary)] rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-medium text-[var(--text-secondary)]">
                热度 (Attention/Flow)
              </span>
              <span className={`text-2xl font-bold ${getScoreClass(heatScore)}`}>
                {heatScore.toFixed(0)}
              </span>
            </div>
            <div className="space-y-3">
              <MetricRow 
                label="相对名义成交" 
                value={relativeNominalValue != null 
                  ? `${relativeNominalValue.toFixed(1)}x` 
                  : (heatScore > 0 ? `${(heatScore / 50).toFixed(1)}x` : '--')} 
              />
              <MetricRow 
                label="相对成交量" 
                value={relativeVolumeValue != null 
                  ? `${relativeVolumeValue.toFixed(1)}x` 
                  : (heatScore > 0 ? `${(heatScore / 50).toFixed(1)}x` : '--')} 
              />
              <MetricRow 
                label="交易笔数" 
                value={optionsOverlay?.tradeCount ?? (heatScore >= 70 ? '高' : heatScore >= 40 ? '中' : '低')} 
              />
            </div>
          </div>

          {/* 风险定价卡片 */}
          <div className="bg-[var(--bg-secondary)] rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-medium text-[var(--text-secondary)]">
                风险定价
              </span>
              <span className={`text-2xl font-bold ${getScoreClass(riskScore)}`}>
                {riskScore.toFixed(0)}
              </span>
            </div>
            <div className="space-y-3">
              <MetricRow 
                label="IVR" 
                value={formatValue(optionsOverlay?.ivr ?? baseOptionsData.ivr)} 
              />
              <MetricRow 
                label="IV30" 
                value={formatValue(optionsOverlay?.iv30 ?? baseOptionsData.implied_volatility)} 
              />
              <MetricRow 
                label="IV30变化" 
                value={iv30ChangeValue != null
                  ? `${iv30ChangeValue >= 0 ? '+' : ''}${iv30ChangeValue.toFixed(1)}%`
                  : '--'} 
              />
            </div>
          </div>

          {/* 期限结构卡片 */}
          <div className="bg-[var(--bg-secondary)] rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-medium text-[var(--text-secondary)]">
                期限结构
              </span>
              <span className={`text-2xl font-bold ${getScoreClass(termStructureScore)}`}>
                {termStructureScore}
              </span>
            </div>
            <div className="space-y-3">
              <MetricRow 
                label="Slope (IV30/IV90)" 
                value={slopeValue != null ? formatValue(slopeValue) : '--'} 
              />
              <MetricRow 
                label="结构解读" 
                value={termStructureInterpretation}
              />
              <MetricRow 
                label="财报事件" 
                value={optionsOverlay?.earningsEvent ?? '--'} 
              />
            </div>
          </div>
        </div>
      </div>

      {/* 持仓变化表格 */}
      <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6">
        <h4 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
          持仓变化 (Positioning Score)
        </h4>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="flex items-center gap-2 text-[var(--text-muted)]">
              <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>正在加载期权持仓数据...</span>
            </div>
          </div>
        ) : (
          <div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[var(--border-light)]">
                    <th className="text-left py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                      期限桶
                    </th>
                    <th className="text-right py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                      Call ΔOI
                    </th>
                    <th className="text-right py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                      Put ΔOI
                    </th>
                    <th className="text-right py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                      Δ_3D
                    </th>
                    <th className="text-right py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                      Δ_5D
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                      趋势
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {orderedPositioning.map((row, index) => {
                    const muted = (
                      row.callOI == null &&
                      row.putOI == null &&
                      row.netOI == null &&
                      row.delta3d == null &&
                      row.delta5d == null
                    );
                    return (
                      <PositionRow 
                        key={`${row.bucket}-${index}`}
                        bucket={bucketLabels[row.bucket] ?? row.bucket}
                        callOI={row.callOI}
                        putOI={row.putOI}
                        delta3d={row.delta3d ?? row.netOI ?? null}
                        delta5d={row.delta5d ?? null}
                        trend={row.trend || '--'}
                        muted={muted}
                        formatOI={formatOI}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!hasPositioningData && (
              <p className="text-xs text-[var(--text-muted)] mt-3">
                暂无可用的持仓变化分桶数据
              </p>
            )}
          </div>
        )}

        {optionsOverlay?.updatedAt && (
          <p className="mt-4 text-xs text-[var(--text-muted)]">
            数据更新时间: {new Date(optionsOverlay.updatedAt).toLocaleString('zh-CN')}
          </p>
        )}
      </div>
    </div>
  );
}

// 辅助组件：指标行
function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-[var(--text-muted)]">{label}</span>
      <span className="font-medium text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

// 辅助组件：持仓表格行
function PositionRow({ 
  bucket, 
  callOI, 
  putOI, 
  delta3d,
  delta5d,
  trend,
  formatOI,
  muted = false
}: { 
  bucket: string; 
  callOI: number | null;
  putOI: number | null;
  delta3d: number | null;
  delta5d: number | null;
  trend: string;
  formatOI: (value: number | null | undefined) => string;
  muted?: boolean;
}) {
  const getDeltaClass = (value: number | null): string => {
    if (muted || value == null) return 'text-[var(--text-muted)]';
    if (value > 0) return 'text-[var(--accent-green)]';
    if (value < 0) return 'text-[var(--accent-red)]';
    return 'text-[var(--text-secondary)]';
  };

  return (
    <tr className="border-b border-[var(--border-light)] last:border-0">
      <td className={`py-3 px-4 text-sm ${muted ? 'text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}`}>
        {bucket}
      </td>
      <td className={`py-3 px-4 text-sm text-right ${muted ? 'text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}`}>
        {formatOI(callOI)}
      </td>
      <td className={`py-3 px-4 text-sm text-right ${muted ? 'text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}`}>
        {formatOI(putOI)}
      </td>
      <td className={`py-3 px-4 text-sm text-right font-medium ${getDeltaClass(delta3d)}`}>
        {formatOI(delta3d)}
      </td>
      <td className={`py-3 px-4 text-sm text-right font-medium ${getDeltaClass(delta5d)}`}>
        {formatOI(delta5d)}
      </td>
      <td className={`py-3 px-4 text-sm ${muted ? 'text-[var(--text-muted)]' : 'text-[var(--text-secondary)]'}`}>
        {trend}
      </td>
    </tr>
  );
}

// 辅助函数：热度类型描述
function getHeatDescription(heatType?: string): string {
  const descriptions: Record<string, string> = {
    trend: '市场关注度高，期权成交活跃，看涨情绪主导',
    event: '近期有重大事件（如财报、并购），波动率显著上升',
    hedge: '机构对冲需求增加，可能暗示市场风险上升',
    normal: '期权市场活动正常，无明显异常信号',
  };
  return descriptions[heatType || 'normal'] || descriptions.normal;
}

// 辅助函数：IVR描述
function getIVRDescription(ivr?: number | null): string {
  if (ivr === null || ivr === undefined) return '数据暂无';
  if (ivr >= 80) return `IVR ${ivr} - 极高水平，期权价格昂贵，谨慎买入期权`;
  if (ivr >= 60) return `IVR ${ivr} - 偏高水平，期权卖方可能有优势`;
  if (ivr >= 40) return `IVR ${ivr} - 中等水平，期权定价合理`;
  if (ivr >= 20) return `IVR ${ivr} - 偏低水平，期权买方可能有优势`;
  return `IVR ${ivr} - 极低水平，期权价格便宜，考虑买入期权`;
}

export default OptionsOverlayTab;
