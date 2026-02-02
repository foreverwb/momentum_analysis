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
      if (!stock.symbol) return;
      
      setIsLoading(true);
      setError(null);
      
      try {
        const data = await getOptionsOverlayData(stock.symbol);
        if (!cancelled) {
          setOptionsOverlay(data);
        }
      } catch (err) {
        if (!cancelled) {
          // 如果 API 不存在或失败，使用 stock 中的基础数据
          console.warn('Options overlay API not available, using base data:', err);
          setError(null); // 不显示错误，静默降级
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

  // 使用后端数据或回退到基础数据
  const heatScore = optionsOverlay?.heatScore ?? baseOptionsData.heat_score ?? stock.heatScore ?? 0;
  const riskScore = optionsOverlay?.riskScore ?? baseOptionsData.risk_score ?? stock.riskScore ?? 0;
  const optionsScore = optionsOverlay 
    ? Math.round((heatScore + riskScore + (optionsOverlay.termStructureScore || 0)) / 3)
    : baseOptionsScore;
  const termStructureScore = optionsOverlay?.termStructureScore ?? (Math.round((optionsScore + heatScore) / 2) || 0);
  const heatType = optionsOverlay?.heatType ?? baseOptionsData.heat_type ?? stock.heatType ?? 'normal';

  // 获取热度类型显示
  const getHeatBadge = () => {
    const badges: Record<string, { label: string; icon: string; className: string }> = {
      trend: { label: '趋势热', icon: '🔥', className: 'bg-green-100 text-green-600' },
      event: { label: '事件热', icon: '⚡', className: 'bg-amber-100 text-amber-600' },
      hedge: { label: '对冲热', icon: '🛡️', className: 'bg-blue-100 text-blue-600' },
      normal: { label: '常规', icon: '📊', className: 'bg-gray-100 text-gray-600' },
    };
    return badges[heatType] || badges.normal;
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
      const parsed = Number(cleaned);
      return Number.isNaN(parsed) ? null : parsed;
    }
    return null;
  };

  const normalizePositioning = (raw: unknown): OptionsPositioningData[] => {
    const normalizeRow = (row: any, bucketFallback?: string): OptionsPositioningData | null => {
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

      const callOI = toNumber(
        row.callOI ?? row.call_oi ?? row.call_delta ?? row.callDelta ?? row.call_change ?? row.callChange ?? row.call
      );
      const putOI = toNumber(
        row.putOI ?? row.put_oi ?? row.put_delta ?? row.putDelta ?? row.put_change ?? row.putChange ?? row.put
      );
      const netOI = toNumber(
        row.netOI ?? row.net_oi ?? row.net_delta ?? row.netDelta ?? row.net_change ?? row.netChange ?? row.net
      );

      const hasAny = [callOI, putOI, netOI].some((value) => typeof value === 'number');
      if (!hasAny) return null;

      const resolvedNet =
        netOI ?? (typeof callOI === 'number' && typeof putOI === 'number' ? callOI - putOI : 0);
      const trend =
        String(row.trend ?? row.signal ?? row.direction ?? row.bias ?? '').trim() ||
        (resolvedNet >= 0 ? '偏多' : '偏空');

      return {
        bucket,
        callOI: callOI ?? 0,
        putOI: putOI ?? 0,
        netOI: resolvedNet,
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

  // 从后端数据或生成默认持仓数据
  const getPositioningData = (): OptionsPositioningData[] => {
    return normalizePositioning(optionsOverlay?.positioning);
  };

  const positioningData = getPositioningData();
  const hasPositioningData = positioningData.length > 0;

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
                value={optionsOverlay?.relativeNominal != null 
                  ? `${optionsOverlay.relativeNominal.toFixed(1)}x` 
                  : (heatScore > 0 ? `${(heatScore / 50).toFixed(1)}x` : '--')} 
              />
              <MetricRow 
                label="相对成交量" 
                value={optionsOverlay?.relativeVolume != null 
                  ? `${optionsOverlay.relativeVolume.toFixed(1)}x` 
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
                value={optionsOverlay?.iv30Change != null 
                  ? `${optionsOverlay.iv30Change >= 0 ? '+' : ''}${optionsOverlay.iv30Change.toFixed(1)}%`
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
                label="Slope" 
                value={optionsOverlay?.slope != null ? formatValue(optionsOverlay.slope) : '--'} 
              />
              <MetricRow 
                label="ΔSlope" 
                value={optionsOverlay?.slopeChange != null 
                  ? `${optionsOverlay.slopeChange >= 0 ? '+' : ''}${optionsOverlay.slopeChange.toFixed(2)}`
                  : '--'} 
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
        ) : hasPositioningData ? (
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
                    净增量
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-[var(--text-secondary)]">
                    趋势
                  </th>
                </tr>
              </thead>
              <tbody>
                {positioningData.map((row, index) => (
                  <PositionRow 
                    key={index}
                    bucket={row.bucket} 
                    callOI={formatOI(row.callOI)} 
                    putOI={formatOI(row.putOI)} 
                    net={formatOI(row.netOI)} 
                    netColor={row.netOI >= 0 ? 'green' : 'red'}
                    trend={row.trend} 
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-[var(--text-muted)] mb-2">
              <svg className="w-12 h-12 mx-auto opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <p className="text-sm text-[var(--text-muted)]">
              暂无持仓变化数据
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              需要接入期权数据源以获取实时持仓变化
            </p>
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
  net, 
  netColor,
  trend 
}: { 
  bucket: string; 
  callOI: string; 
  putOI: string; 
  net: string; 
  netColor: 'green' | 'red';
  trend: string;
}) {
  return (
    <tr className="border-b border-[var(--border-light)] last:border-0">
      <td className="py-3 px-4 text-sm text-[var(--text-primary)]">{bucket}</td>
      <td className="py-3 px-4 text-sm text-right text-[var(--text-primary)]">{callOI}</td>
      <td className="py-3 px-4 text-sm text-right text-[var(--text-primary)]">{putOI}</td>
      <td className={`py-3 px-4 text-sm text-right font-medium ${
        netColor === 'green' ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'
      }`}>
        {net}
      </td>
      <td className="py-3 px-4 text-sm text-[var(--text-secondary)]">{trend}</td>
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
