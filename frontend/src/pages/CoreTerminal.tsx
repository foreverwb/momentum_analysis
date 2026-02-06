import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { ETF } from '../types';
import * as api from '../services/api';

// ============ 类型定义 ============
type MarketRegimeStatus = 'A' | 'B' | 'C' | 'UNKNOWN' | 'DISCONNECTED' | 'NO_DATA' | 'ERROR';

interface MarketStatus {
  status?: MarketRegimeStatus;
  spy?: {
    price?: number;
    sma20?: number;
    sma50?: number;
    return20d?: number;
    sma20Slope?: number;
    distToSma20?: number | null;
    distToSma50?: number | null;
  };
  vix?: number | null;
  breadth?: number;
}

interface MarketSnapshot {
  data: MarketStatus | null;
  source: 'live' | 'cache' | 'none';
  savedAt?: string | null;
}

interface StoredMarketSnapshot {
  savedAt: string;
  data: MarketStatus;
}

interface Sector {
  code: string;
  name: string;
  score: number;
  delta: number | null;
  heat: 'high' | 'medium' | 'low';
}

interface IndustryRow {
  symbol: string;
  name: string;
  score: number;
  completeness: number;
  delta: number | null;
  rank: number;
}

// ============ SVG 图标组件 ============
const FlameIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"></path>
  </svg>
);

const BarChartIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <line x1="18" y1="20" x2="18" y2="10"></line>
    <line x1="12" y1="20" x2="12" y2="4"></line>
    <line x1="6" y1="20" x2="6" y2="14"></line>
  </svg>
);

const RefreshIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <polyline points="23 4 23 10 17 10"></polyline>
    <polyline points="1 20 1 14 7 14"></polyline>
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
  </svg>
);

const EditIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
  </svg>
);

// ============ 可编辑数字组件 - FIXED VERSION ============
interface EditableNumberProps {
  value: number | undefined;
  onChange: (value: string) => void;
  suffix?: string;
  className?: string;
}

function EditableNumber({ value, onChange, suffix = '%', className = '' }: EditableNumberProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [localValue, setLocalValue] = useState('');

  const displayValue = value !== undefined ? `${value}${suffix}` : 'N/A';

  const handleFocus = () => {
    setIsEditing(true);
    setLocalValue(value !== undefined ? String(value) : '');
  };

  const handleBlur = () => {
    setIsEditing(false);
    onChange(localValue);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      (e.target as HTMLInputElement).blur();
    } else if (e.key === 'Escape') {
      setLocalValue(value !== undefined ? String(value) : '');
      (e.target as HTMLInputElement).blur();
    }
  };

  return (
    <div className={`group relative inline-flex items-center justify-center ${className}`}>
      {isEditing ? (
        // Input with fixed dimensions to prevent layout shift
        <input
          type="text"
          value={localValue}
          onChange={(e) => setLocalValue(e.target.value)}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          autoFocus
          className="
            w-20 h-10 text-2xl font-bold text-center 
            bg-white/10 border-2 border-white/50 rounded-md
            outline-none cursor-text
            focus:border-white/70 focus:bg-white/15
            transition-colors duration-200
          "
          style={{
            appearance: 'none',
            WebkitAppearance: 'none',
            MozAppearance: 'textfield',
          }}
        />
      ) : (
        // Display with same fixed dimensions - prevents shift on focus
        <div 
          onClick={handleFocus}
          className="
            w-20 h-10 text-2xl font-bold cursor-pointer
            flex items-center justify-center
            hover:bg-white/10 border-2 border-transparent hover:border-white/30
            rounded-md transition-colors duration-200
            relative
          "
        >
          {displayValue}
          <EditIcon className="absolute -top-1 -right-1 text-white/60 opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      )}
    </div>
  );
}


// ============ 本地快照缓存 ============
const MARKET_SNAPSHOT_STORAGE_KEY = 'coreTerminal.marketRegimeSnapshot.v1';

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const normalizeStatus = (value?: string): MarketRegimeStatus | undefined => {
  if (!value) return undefined;
  const upper = value.toUpperCase();
  if (upper === 'A' || upper === 'B' || upper === 'C') return upper as MarketRegimeStatus;
  if (upper === 'DISCONNECTED') return 'DISCONNECTED';
  if (upper === 'NO_DATA') return 'NO_DATA';
  if (upper === 'ERROR') return 'ERROR';
  if (upper === 'UNKNOWN') return 'UNKNOWN';
  return 'UNKNOWN';
};

const hasUsableSpyData = (spy?: MarketStatus['spy']): boolean =>
  isFiniteNumber(spy?.price) && isFiniteNumber(spy?.sma50);

const loadStoredSnapshot = (): StoredMarketSnapshot | null => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(MARKET_SNAPSHOT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const savedAt = typeof parsed.savedAt === 'string' ? parsed.savedAt : null;
    const data = parsed.data as MarketStatus | undefined;
    if (!savedAt || !data) return null;
    const normalizedData: MarketStatus = {
      ...data,
      status: normalizeStatus(data.status),
    };
    if (!hasUsableSpyData(normalizedData.spy)) return null;
    return { savedAt, data: normalizedData };
  } catch {
    return null;
  }
};

const saveStoredSnapshot = (data: MarketStatus, savedAt: string) => {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(MARKET_SNAPSHOT_STORAGE_KEY, JSON.stringify({ savedAt, data }));
  } catch {
    // Ignore storage errors
  }
};

// ============ 辅助函数 ============
function getRegimeColor(status: MarketRegimeStatus): string {
  if (status === 'A') return 'from-emerald-400 to-green-500';
  if (status === 'B') return 'from-amber-400 to-orange-500';
  if (status === 'C') return 'from-red-400 to-rose-500';
  if (status === 'ERROR') return 'from-rose-400 to-red-500';
  return 'from-slate-400 to-slate-500';
}

function getRegimeText(status: MarketRegimeStatus): string {
  if (status === 'A') return 'Risk-On 满火力';
  if (status === 'B') return 'Neutral 半火力';
  if (status === 'C') return 'Risk-Off 低火力';
  if (status === 'DISCONNECTED') return 'IBKR 未连接';
  if (status === 'NO_DATA') return '暂无快照';
  if (status === 'ERROR') return '数据异常';
  return '数据不足';
}

function getHeatColor(heat: 'high' | 'medium' | 'low'): string {
  if (heat === 'high') return 'text-red-500';
  if (heat === 'medium') return 'text-amber-500';
  return 'text-slate-400';
}

function getScoreColor(score: number): string {
  if (score >= 85) return 'text-emerald-600';
  if (score >= 70) return 'text-blue-600';
  if (score >= 60) return 'text-amber-600';
  return 'text-slate-500';
}

function getTrendLevelColor(level: string): string {
  if (level === 'Strong') return 'bg-emerald-50 border-emerald-200 text-emerald-600';
  if (level === 'Stable') return 'bg-blue-50 border-blue-200 text-blue-600';
  return 'bg-amber-50 border-amber-200 text-amber-600';
}

function clampScore(score?: number | null): number {
  if (score === null || score === undefined || Number.isNaN(score)) return 0;
  return Math.max(0, Math.min(100, Number(score.toFixed(1))));
}

function getHeatLevel(score: number): 'high' | 'medium' | 'low' {
  if (score >= 85) return 'high';
  if (score >= 70) return 'medium';
  return 'low';
}

function getTrendLevel(delta: number | null, score?: number | null): 'Strong' | 'Stable' | 'Weak' {
  if (delta !== null && delta !== undefined && !Number.isNaN(delta)) {
    if (delta >= 1) return 'Strong';
    if (delta <= -1) return 'Weak';
    return 'Stable';
  }
  if (score !== null && score !== undefined && !Number.isNaN(score)) {
    if (score >= 80) return 'Strong';
    if (score >= 60) return 'Stable';
    return 'Weak';
  }
  return 'Stable';
}

function formatDelta(value: number | null | undefined, digits = 1, suffix = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

function formatScoreValue(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value) || value <= 0) return '--';
  return value.toFixed(digits);
}

function formatPercentValue(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value) || value <= 0) return '--';
  return `${value.toFixed(digits)}%`;
}

function formatRankValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value <= 0) return '--';
  return `#${value}`;
}

function getDeltaColor(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-slate-500';
  if (value > 0) return 'text-emerald-600';
  if (value < 0) return 'text-red-600';
  return 'text-slate-600';
}

// ============ Regime 计算辅助 ============
const percentDiff = (price?: number, base?: number): number | null => {
  if (price === undefined || base === undefined || base === 0) return null;
  return (price - base) / base;
};

const formatPercent = (value: number | null | undefined, digits = 1): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  const pct = value * 100;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(digits)}%`;
};

const formatNumber = (value: number | null | undefined, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
};

function computeRegime(inputs: { price?: number; sma50?: number; return20d?: number; sma20Slope?: number; breadth?: number; dist50?: number | null }): 'A' | 'B' | 'C' {
  const { price, sma50, return20d, sma20Slope, breadth, dist50 } = inputs;
  if (price === undefined || sma50 === undefined) return 'B';

  const diff50 = dist50 !== null && dist50 !== undefined ? dist50 : percentDiff(price, sma50);
  const near50 = diff50 !== null && Math.abs(diff50) < 0.02; // ±2%

  const slopeUp = (sma20Slope ?? 0) > 0;
  const returnUp = (return20d ?? 0) > 0;
  const priceAbove50 = price > sma50;
  const priceBelow50 = price < sma50;

  const breadthGood = breadth === undefined ? true : breadth >= 50;
  const breadthCollapse = breadth !== undefined && breadth > 0 && breadth < 30;

  if ((priceBelow50 && (return20d ?? 0) < 0) || breadthCollapse) return 'C';
  if (near50) return 'B';
  if (priceAbove50 && (slopeUp || returnUp) && breadthGood) return 'A';
  return 'B';
}

// ============ 主组件 ============
export function CoreTerminal() {
  const [selectedSector, setSelectedSector] = useState<string>('');
  const [sectorEtfs, setSectorEtfs] = useState<ETF[]>([]);
  const [industryEtfs, setIndustryEtfs] = useState<ETF[]>([]);
  const [sectorLoading, setSectorLoading] = useState(false);
  const [sectorError, setSectorError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [marketSnapshot, setMarketSnapshot] = useState<MarketSnapshot>({
    data: null,
    source: 'none',
    savedAt: null,
  });
  const [marketStatusError, setMarketStatusError] = useState<string | null>(null);
  const [manualInputs, setManualInputs] = useState<{
    price?: string;
    sma20?: string;
    sma50?: string;
    return20d?: string; // 百分比
    breadth?: string;
  }>({});
  const marketStatus = marketSnapshot.data;

  useEffect(() => {
    const cachedSnapshot = loadStoredSnapshot();
    if (cachedSnapshot) {
      setMarketSnapshot({
        data: cachedSnapshot.data,
        source: 'cache',
        savedAt: cachedSnapshot.savedAt,
      });
    }
  }, []);

  const fetchSectorData = useCallback(async () => {
    setSectorLoading(true);
    setSectorError(null);
    try {
      const [sectorsResponse, industriesResponse] = await Promise.all([
        api.getETFs('sector', false),
        api.getETFs('industry', false),
      ]);

      setSectorEtfs(sectorsResponse || []);
      setIndustryEtfs(industriesResponse || []);
      setSelectedSector((prev) => {
        if (!sectorsResponse || sectorsResponse.length === 0) return prev;
        const normalized = prev ? prev.toUpperCase() : '';
        if (normalized && sectorsResponse.some((etf) => etf.symbol === normalized)) {
          return normalized;
        }
        return sectorsResponse[0].symbol;
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '加载板块数据失败';
      setSectorError(message);
    } finally {
      setSectorLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSectorData();
  }, [fetchSectorData]);

  const sectorList = useMemo<Sector[]>(() => {
    if (!sectorEtfs || sectorEtfs.length === 0) return [];
    const sorted = [...sectorEtfs].sort((a, b) => {
      const rankA = a.rank ?? 0;
      const rankB = b.rank ?? 0;
      if (rankA > 0 && rankB > 0) return rankA - rankB;
      return (b.score ?? 0) - (a.score ?? 0);
    });
    return sorted.map((etf) => {
      const score = clampScore(etf.score);
      const delta = etf.delta?.delta5d ?? etf.delta?.delta3d ?? null;
      return {
        code: etf.symbol,
        name: etf.name || etf.symbol,
        score,
        delta,
        heat: getHeatLevel(score),
      };
    });
  }, [sectorEtfs]);

  const selectedSectorETF = useMemo(() => {
    if (!selectedSector) return undefined;
    return sectorEtfs.find((etf) => etf.symbol === selectedSector);
  }, [sectorEtfs, selectedSector]);

  const industryRows = useMemo<IndustryRow[]>(() => {
    if (!selectedSector) return [];
    const normalized = selectedSector.toUpperCase();
    return industryEtfs
      .filter((etf) => (etf.parentSector || '').toUpperCase() === normalized)
      .sort((a, b) => {
        const rankA = a.rank ?? 0;
        const rankB = b.rank ?? 0;
        if (rankA > 0 && rankB > 0) return rankA - rankB;
        return (b.score ?? 0) - (a.score ?? 0);
      })
      .map((etf) => ({
        symbol: etf.symbol,
        name: etf.name || etf.symbol,
        score: etf.score ?? 0,
        completeness: etf.completeness ?? 0,
        delta: etf.delta?.delta5d ?? etf.delta?.delta3d ?? null,
        rank: etf.rank ?? 0,
      }));
  }, [industryEtfs, selectedSector]);

  const handleBreadthChange = useCallback((value: string) => {
    const trimmed = value.trim();
    if (trimmed === '') {
      setManualInputs((prev) => ({ ...prev, breadth: '' }));
      return;
    }

    const normalized = trimmed.replace(/[^\d.-]/g, '');
    const parsed = Number(normalized);
    if (Number.isNaN(parsed)) {
      setManualInputs((prev) => ({ ...prev, breadth: '' }));
      return;
    }

    const clamped = Math.max(0, Math.min(100, parsed));
    setManualInputs((prev) => ({ ...prev, breadth: clamped.toString() }));
  }, []);

  const numberFromManual = (value?: string) => {
    if (value === undefined || value === '') return undefined;
    const parsed = Number(value);
    return Number.isNaN(parsed) ? undefined : parsed;
  };

  const baseSpy = marketStatus?.spy;
  const priceVal = numberFromManual(manualInputs.price) ?? baseSpy?.price;
  const sma20Val = numberFromManual(manualInputs.sma20) ?? baseSpy?.sma20;
  const sma50Val = numberFromManual(manualInputs.sma50) ?? baseSpy?.sma50;
  const return20Val = numberFromManual(manualInputs.return20d) !== undefined
    ? Number(manualInputs.return20d) / 100
    : baseSpy?.return20d;
  const dist50Val = percentDiff(priceVal, sma50Val);
  const canComputeRegime = isFiniteNumber(priceVal) && isFiniteNumber(sma50Val);

  const effectiveSpy = {
    price: priceVal,
    sma20: sma20Val,
    sma50: sma50Val,
    return20d: return20Val,
    sma20Slope: baseSpy?.sma20Slope,
    distToSma50: dist50Val,
  };

  const effectiveBreadth = numberFromManual(manualInputs.breadth) ?? marketStatus?.breadth;

  const computedStatus: MarketRegimeStatus = canComputeRegime
    ? computeRegime({
        price: effectiveSpy.price,
        sma50: effectiveSpy.sma50,
        return20d: effectiveSpy.return20d,
        sma20Slope: effectiveSpy.sma20Slope,
        breadth: effectiveBreadth,
        dist50: effectiveSpy.distToSma50 ?? percentDiff(effectiveSpy.price, effectiveSpy.sma50),
      })
    : 'UNKNOWN';

  const displayRegime = {
    status: canComputeRegime ? computedStatus : (marketStatus?.status ?? 'UNKNOWN'),
    spy: effectiveSpy,
    vix: marketStatus?.vix ?? null,
    breadth: effectiveBreadth,
  };

  const dist20 = percentDiff(effectiveSpy.price, effectiveSpy.sma20);
  const dist50 = effectiveSpy.distToSma50 ?? percentDiff(effectiveSpy.price, effectiveSpy.sma50);
  const hasMarketData = hasUsableSpyData(marketStatus?.spy);
  const regimeBadge =
    displayRegime.status === 'A' || displayRegime.status === 'B' || displayRegime.status === 'C'
      ? displayRegime.status
      : '--';
  const marketSnapshotLabel =
    hasMarketData
      ? marketSnapshot.source === 'live'
        ? '实时更新'
        : marketSnapshot.source === 'cache'
          ? '缓存快照'
          : '暂无数据'
      : canComputeRegime
        ? '手动输入'
        : '暂无数据';

  const sectorDelta = selectedSectorETF?.delta?.delta5d ?? selectedSectorETF?.delta?.delta3d ?? null;
  const sectorTrendLevel = getTrendLevel(sectorDelta, selectedSectorETF?.score);
  const hasSectorData = Boolean(selectedSectorETF);
  const sectorTrendDisplay = hasSectorData ? sectorTrendLevel : '--';
  const sectorTrendColor = hasSectorData ? getTrendLevelColor(sectorTrendLevel) : 'bg-slate-50 border-slate-200 text-slate-500';
  const sectorName = selectedSectorETF?.name || selectedSector || '—';
  const sectorSymbol = selectedSectorETF?.symbol || selectedSector || '—';
  const sectorSubtitle = selectedSectorETF
    ? `${sectorName} · ${sectorName.replace('板块', '')} Sector`
    : '暂无板块数据';

  const fetchMarketRegime = useCallback(async (refresh = false, showSpinner = false) => {
    if (showSpinner) {
      setIsRefreshing(true);
    }
    setMarketStatusError(null);
    if (refresh) {
      fetchSectorData();
    }
    try {
      const response = await api.getMarketRegime(refresh);
      const spy = response?.spy ?? null;
      const indicators = (response?.indicators || {}) as any;
      const nextSnapshot: MarketStatus = {
        status: normalizeStatus(response?.status),
        spy: spy
          ? {
              price: spy.price,
              sma20: spy.sma20,
              sma50: spy.sma50,
              distToSma20: spy.dist_to_sma20 ?? indicators.dist_to_sma20 ?? percentDiff(spy.price, spy.sma20),
              distToSma50: spy.dist_to_sma50 ?? indicators.dist_to_sma50 ?? percentDiff(spy.price, spy.sma50),
              return20d: spy.return_20d ?? indicators.return_20d,
              sma20Slope: spy.sma20_slope ?? indicators.sma20_slope,
            }
          : undefined,
        vix: response?.vix ?? null,
        breadth: (response as any)?.breadth,
      };

      if (hasUsableSpyData(nextSnapshot.spy)) {
        const savedAt = new Date().toISOString();
        setMarketSnapshot({
          data: nextSnapshot,
          source: 'live',
          savedAt,
        });
        saveStoredSnapshot(nextSnapshot, savedAt);
      } else {
        const statusText = normalizeStatus(response?.status);
        const cachedSnapshot = loadStoredSnapshot();
        const fallbackMessage = response?.error
          ?? (statusText === 'DISCONNECTED'
            ? cachedSnapshot
              ? 'IBKR 未连接，已显示缓存快照'
              : 'IBKR 未连接，暂无可用快照'
            : statusText === 'NO_DATA'
              ? '今日暂无快照'
              : 'Regime 数据不可用');
        setMarketStatusError(fallbackMessage);
        setMarketSnapshot((prev) => {
          if (prev.data && hasUsableSpyData(prev.data.spy)) {
            return prev;
          }
          if (cachedSnapshot) {
            return {
              data: cachedSnapshot.data,
              source: 'cache',
              savedAt: cachedSnapshot.savedAt,
            };
          }
          return {
            data: nextSnapshot,
            source: 'live',
            savedAt: prev.savedAt ?? null,
          };
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '刷新失败';
      const cachedSnapshot = loadStoredSnapshot();
      setMarketStatusError(cachedSnapshot ? `${message}，已显示缓存快照` : message);
      setMarketSnapshot((prev) => {
        if (prev.data && hasUsableSpyData(prev.data.spy)) {
          return prev;
        }
        if (cachedSnapshot) {
          return {
            data: cachedSnapshot.data,
            source: 'cache',
            savedAt: cachedSnapshot.savedAt,
          };
        }
        return prev;
      });
    } finally {
      if (showSpinner) {
        setIsRefreshing(false);
      }
    }
  }, [fetchSectorData]);

  useEffect(() => {
    fetchMarketRegime(false, false);
  }, [fetchMarketRegime]);

  return (
    <div>
      {/* 页面标题和刷新按钮 */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => fetchMarketRegime(true, true)}
          className="px-4 py-2 text-sm font-medium rounded-sm bg-blue-600 text-white hover:bg-blue-700 transition-colors flex items-center gap-2"
        >
          {isRefreshing ? <RefreshIcon className="animate" /> : ''}
          Refresh
        </button>
      </div>
      {/* 显示错误信息 */}
      {marketStatusError && (
        <div className="mb-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700">
          <p className="text-sm font-medium">❌ 数据刷新失败: {marketStatusError}</p>
        </div>
      )}

      {/* Regime Gate 状态卡 - 渐变背景大卡片 - FIXED GRID */}
      <div className={`mb-6 p-6 rounded-2xl bg-gradient-to-r ${getRegimeColor(displayRegime.status)} shadow-xl text-white`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 bg-white/30 rounded-xl flex items-center justify-center backdrop-blur-sm">
              <span className="text-3xl font-bold">{regimeBadge}</span>
            </div>
            <div>
              <h2 className="text-2xl font-bold mb-1">{getRegimeText(displayRegime.status)}</h2>
              <p className="text-white/90 text-sm">市场环境评估 · {marketSnapshotLabel}</p>
            </div>
          </div>
          {/* FIXED: Better horizontal alignment with consistent spacing */}
          <div className="grid grid-cols-6 gap-6 items-center">
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">$SPY</div>
              <div className="text-2xl font-bold">${displayRegime.spy?.price !== undefined ? displayRegime.spy.price.toFixed(2) : 'N/A'}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">20DMA</div>
              <div className="text-2xl font-bold">{formatPercent(dist20)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">50DMA</div>
              <div className={`text-2xl font-bold ${Math.abs(dist50 ?? 0) < 0.02 ? 'text-amber-200' : ''}`}>{formatPercent(dist50)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">20日收益率</div>
              <div className="text-2xl font-bold">{formatPercent(displayRegime.spy?.return20d ?? null, 2)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">20DMA Slope</div>
              <div className="text-2xl font-bold">{formatNumber(displayRegime.spy?.sma20Slope ?? null, 3)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">市场广度</div>
              <EditableNumber
                value={displayRegime.breadth}
                onChange={handleBreadthChange}
                suffix="%"
              />
            </div>
          </div>
        </div>
      </div>

      {/* 三栏布局：左侧板块热力榜 + 右侧板块详情 */}
      <div className="grid grid-cols-3 gap-6">
        {/* 左侧：板块热力榜 */}
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-lg">
          <div className="flex items-center gap-2 mb-6">
            <h3 className="text-lg font-bold text-slate-900">板块热力榜</h3>
          </div>
          {sectorError && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 flex items-center justify-between">
              <span>板块数据加载失败：{sectorError}</span>
              <button
                onClick={fetchSectorData}
                className="text-xs font-medium text-red-600 hover:text-red-700"
              >
                重试
              </button>
            </div>
          )}
          {sectorLoading && sectorList.length > 0 && (
            <div className="mb-2 text-xs text-slate-400">正在更新...</div>
          )}
          {sectorLoading && sectorList.length === 0 ? (
            <div className="text-sm text-slate-500">正在加载板块数据...</div>
          ) : sectorList.length === 0 ? (
            <div className="text-sm text-slate-500">暂无板块数据</div>
          ) : (
            <div className="space-y-3">
              {sectorList.map((sector) => {
                const scoreText = formatScoreValue(sector.score);
                return (
                  <div
                    key={sector.code}
                    onClick={() => setSelectedSector(sector.code)}
                    className={`p-4 rounded-xl cursor-pointer transition-all ${
                      selectedSector === sector.code
                        ? 'bg-gradient-to-r from-blue-100 to-purple-100 border border-blue-300 shadow-md'
                        : 'bg-slate-50 hover:bg-slate-100 border border-slate-200'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <div className="font-bold text-sm text-slate-900">{sector.code}</div>
                        <div className="text-xs text-slate-600">{sector.name}</div>
                      </div>
                      <div className="text-right">
                        <div className={`text-lg font-bold ${getScoreColor(sector.score)}`}>{scoreText}</div>
                        <div className="text-xs text-slate-600">综合分</div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between text-xs">
                      <span className={`${getDeltaColor(sector.delta)} font-medium`}>
                        {formatDelta(sector.delta, 1, '分')}
                      </span>
                      <FlameIcon className={`w-4 h-4 ${getHeatColor(sector.heat)}`} />
                    </div>
                    <div className="mt-2 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-emerald-500 to-blue-500 transition-all duration-500"
                        style={{ width: `${clampScore(sector.score)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 右侧：板块详情面板 (占2列) */}
        <div className="col-span-2 bg-white rounded-2xl p-6 border border-slate-200 shadow-lg">
          <div className="flex items-start justify-between mb-6">
            <div>
              <h2 className="text-3xl font-bold text-slate-900 mb-2">{sectorSymbol}</h2>
              <p className="text-slate-600">{sectorSubtitle}</p>
            </div>
            <div className="flex items-center gap-3">
              <div className={`px-4 py-2 rounded-sm border ${sectorTrendColor}`}>
                <div className="text-xs mb-1">趋势等级</div>
                <div className="text-xl font-bold">{sectorTrendDisplay}</div>
              </div>
            </div>
          </div>

          {/* 四个关键指标卡片 */}
          <div className="grid grid-cols-4 gap-4 mb-6">
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">综合评分</div>
              <div className={`text-2xl font-bold ${getScoreColor(selectedSectorETF?.score ?? 0)}`}>
                {formatScoreValue(selectedSectorETF?.score)}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">5D评分变化</div>
              <div className={`text-2xl font-bold ${getDeltaColor(sectorDelta)}`}>
                {formatDelta(sectorDelta, 1, '分')}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">数据完整度</div>
              <div className="text-2xl font-bold text-purple-600">
                {formatPercentValue(selectedSectorETF?.completeness)}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">排名</div>
              <div className="text-2xl font-bold text-amber-600">
                {formatRankValue(selectedSectorETF?.rank)}
              </div>
            </div>
          </div>

          {/* 子行业强度排名 */}
          <div>
            <h4 className="text-sm font-bold text-slate-700 mb-3 flex items-center gap-2">
              <BarChartIcon className="text-blue-600" />
              子行业强度排名
              <span className="text-xs font-normal text-slate-500">({industryRows.length})</span>
            </h4>
            {industryRows.length === 0 ? (
              <div className="text-sm text-slate-500">暂无子行业 ETF 数据</div>
            ) : (
              <div className="space-y-2">
                {industryRows.map((ind, idx) => (
                  <div
                    key={ind.symbol}
                    className="flex items-center gap-3 p-3 bg-slate-50 rounded-sm hover:bg-slate-100 border border-slate-200 transition-colors"
                  >
                    <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-sm flex items-center justify-center font-bold text-sm text-white">
                      {idx + 1}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-900">{ind.symbol}</span>
                        <span className="text-xs text-slate-600">{ind.name}</span>
                      </div>
                      <div className="flex items-center gap-4 mt-1 text-xs text-slate-600">
                        <span>
                          综合分: <span className="text-blue-600 font-medium">{formatScoreValue(ind.score)}</span>
                        </span>
                        <span>
                          完整度: <span className="text-purple-600 font-medium">{formatPercentValue(ind.completeness)}</span>
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-lg font-bold ${getDeltaColor(ind.delta)}`}>
                        {formatDelta(ind.delta, 1, '分')}
                      </div>
                      <div className="text-xs text-slate-600">5D评分变化</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}