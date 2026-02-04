import React, { useState, useEffect, useMemo } from 'react';
import { RelativeTrendChart, type RelativeTrendSeries } from '../chart';
import { ETFDetailCard } from './ETFDetailCard';
import { HoldingsImportModal, ETFImportModal, RefreshProgressModal } from '../modal';
import { LoadingState, ErrorMessage } from '../common';
import type { Task, ETF, Holding, RefreshResult } from '../../types';
import * as api from '../../services/api';

interface TaskDetailProps {
  task: Task;
  onBack: () => void;
}

// ETF 名称映射
const ETF_NAMES: Record<string, string> = {
  XLK: 'Technology Select Sector SPDR',
  XLF: 'Financial Select Sector SPDR',
  XLV: 'Health Care Select Sector SPDR',
  XLE: 'Energy Select Sector SPDR',
  XLY: 'Consumer Discretionary Select Sector SPDR',
  XLI: 'Industrial Select Sector SPDR',
  XLC: 'Communication Services Select Sector SPDR',
  XLP: 'Consumer Staples Select Sector SPDR',
  XLU: 'Utilities Select Sector SPDR',
  XLRE: 'Real Estate Select Sector SPDR',
  XLB: 'Materials Select Sector SPDR',
  SOXX: 'iShares Semiconductor ETF',
  SMH: 'VanEck Semiconductor ETF',
  IGV: 'iShares Expanded Tech-Software ETF',
  SKYY: 'First Trust Cloud Computing ETF',
  HACK: 'ETFMG Prime Cyber Security ETF',
  KBE: 'SPDR S&P Bank ETF',
  KRE: 'SPDR S&P Regional Banking ETF',
  XBI: 'SPDR S&P Biotech ETF',
  IBB: 'iShares Biotechnology ETF',
  XOP: 'SPDR S&P Oil & Gas Exploration ETF',
  OIH: 'VanEck Oil Services ETF',
};

// 板块 ETF 符号列表
const SECTOR_SYMBOLS = ['XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLI', 'XLC', 'XLP', 'XLU', 'XLRE', 'XLB'];
const TREND_COLORS = ['#22c55e', '#3b82f6', '#8b5cf6', '#f59e0b', '#14b8a6', '#e11d48'];
const TREND_METRIC_OPTIONS = [
  { value: 'relative', label: '相对走势' },
  { value: 'sma20', label: '20DMA' },
  { value: 'return20d', label: '20D收益' },
  { value: 'score', label: '综合评分' },
];
const TASK_TREND_CACHE_TTL_MS = 60 * 1000;
const taskTrendCache = new Map<string, {
  cachedAt: number;
  dates: string[];
  series: RelativeTrendSeries[];
  priceSeries: RelativeTrendSeries[];
  sma20Series: RelativeTrendSeries[];
}>();

const toTaskTrendCacheKey = (
  taskId: number,
  period: '5d' | '20d' | '63d',
  metric: 'relative' | 'sma20' | 'return20d' | 'score'
): string => `${taskId}|${period}|${metric}`;

const hasValidSeriesValues = (values: Array<number | null> | undefined): boolean =>
  Array.isArray(values) && values.some((value) => typeof value === 'number' && Number.isFinite(value));

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

type SourceStatus = 'complete' | 'pending' | 'missing' | 'loading';
type SourceKey = 'finviz' | 'marketchameleon' | 'ibkr' | 'futu';

const SOURCE_STATUS_LABEL: Record<SourceStatus, string> = {
  complete: '已更新',
  pending: '待更新',
  missing: '缺失',
  loading: '更新中',
};

const SOURCE_STATUS_STORAGE_PREFIX = 'task-detail-source-status-v1';
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

const SOURCE_CIRCLE_META: Record<SourceKey, { label: string; borderColor: string }> = {
  finviz: { label: 'Finviz', borderColor: '#93c5fd' },
  marketchameleon: { label: 'MarketChameleon', borderColor: '#86efac' },
  ibkr: { label: '市场数据(IBKR)', borderColor: '#fca5a5' },
  futu: { label: '期权数据(Futu)', borderColor: '#fb923c' },
};

const SOURCE_REFRESH_KEYS: Record<SourceKey, string[]> = {
  finviz: ['finviz', 'finviz_breadth'],
  marketchameleon: ['market_chameleon', 'marketchameleon', 'mc_options'],
  ibkr: ['ibkr', 'ibkr_price', 'ibkr_relmom', 'ibkr_trend', 'market_data'],
  futu: ['futu', 'futu_iv', 'options_data'],
};

const normalizeSourceKey = (source: string): SourceKey | null => {
  const normalized = source.trim().toLowerCase();
  if (normalized.includes('finviz')) return 'finviz';
  if (normalized.includes('marketchameleon') || normalized.includes('market_chameleon') || normalized === 'mc') return 'marketchameleon';
  if (normalized.includes('ibkr') || normalized.includes('market_data') || normalized.includes('市场数据')) return 'ibkr';
  if (normalized.includes('futu') || normalized.includes('options_data') || normalized.includes('期权数据')) return 'futu';
  return null;
};

const pickAggregatedStatus = (statuses: Set<SourceStatus>): SourceStatus => {
  if (statuses.has('loading')) return 'loading';
  if (statuses.has('complete')) return 'complete';
  if (statuses.has('pending')) return 'pending';
  return 'missing';
};

const getSourceStatusStorageKey = (taskId: number): string => `${SOURCE_STATUS_STORAGE_PREFIX}:${taskId}`;

const loadStoredSourceUpdatedAt = (taskId: number): Partial<Record<SourceKey, string>> => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = localStorage.getItem(getSourceStatusStorageKey(taskId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};
    const result: Partial<Record<SourceKey, string>> = {};
    (Object.keys(SOURCE_CIRCLE_META) as SourceKey[]).forEach((key) => {
      const value = (parsed as Record<string, unknown>)[key];
      if (typeof value !== 'string') return;
      const ts = new Date(value);
      if (Number.isNaN(ts.getTime())) return;
      result[key] = ts.toISOString();
    });
    return result;
  } catch {
    return {};
  }
};

const saveStoredSourceUpdatedAt = (taskId: number, payload: Partial<Record<SourceKey, string>>) => {
  if (typeof window === 'undefined') return;
  try {
    const sanitized: Partial<Record<SourceKey, string>> = {};
    (Object.keys(SOURCE_CIRCLE_META) as SourceKey[]).forEach((key) => {
      const value = payload[key];
      if (!value) return;
      const ts = new Date(value);
      if (Number.isNaN(ts.getTime())) return;
      sanitized[key] = ts.toISOString();
    });
    localStorage.setItem(getSourceStatusStorageKey(taskId), JSON.stringify(sanitized));
  } catch {
    // ignore storage errors
  }
};

const getBeijingResetBoundaryMs = (nowMs: number): number => {
  const beijingNow = new Date(nowMs + BEIJING_OFFSET_MS);
  const year = beijingNow.getUTCFullYear();
  const month = beijingNow.getUTCMonth();
  const day = beijingNow.getUTCDate();
  const hour = beijingNow.getUTCHours();
  let boundaryUtcMs = Date.UTC(year, month, day, 0, 0, 0, 0); // 08:00 BJT
  if (hour < 8) {
    boundaryUtcMs -= ONE_DAY_MS;
  }
  return boundaryUtcMs;
};

const mapDataSourcesToKeys = (dataSources?: Record<string, boolean>): SourceKey[] => {
  if (!dataSources) return [];
  return (Object.keys(SOURCE_REFRESH_KEYS) as SourceKey[]).filter((sourceKey) =>
    SOURCE_REFRESH_KEYS[sourceKey].some((candidate) => Boolean(dataSources[candidate]))
  );
};

const formatUpdateDate = (value?: string | null): string => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const formatUpdateDateTime = (value?: string | null): string => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  const beijing = new Date(date.getTime() + BEIJING_OFFSET_MS);
  const month = `${beijing.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${beijing.getUTCDate()}`.padStart(2, '0');
  const hours = `${beijing.getUTCHours()}`.padStart(2, '0');
  const minutes = `${beijing.getUTCMinutes()}`.padStart(2, '0');
  return `${month}-${day} ${hours}:${minutes}`;
};

const formatBeijingBoundaryLabel = (boundaryUtcMs: number): string => {
  const beijing = new Date(boundaryUtcMs + BEIJING_OFFSET_MS);
  const year = beijing.getUTCFullYear();
  const month = `${beijing.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${beijing.getUTCDate()}`.padStart(2, '0');
  return `${year}-${month}-${day} 08:00`;
};

const normalizeEtfs = (raw: unknown): string[] => {
  if (Array.isArray(raw)) {
    return raw
      .map((item) => String(item).trim().toUpperCase())
      .filter((item) => item.length > 0);
  }
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed
          .map((item) => String(item).trim().toUpperCase())
          .filter((item) => item.length > 0);
      }
    } catch {
      // Fallback to comma-separated list
    }
    return raw
      .split(',')
      .map((item) => item.trim().toUpperCase())
      .filter((item) => item.length > 0);
  }
  return [];
};

const getSymbolsKey = (symbols: string[]): string => symbols.join('|');

function getETFName(symbol: string): string {
  return ETF_NAMES[symbol] || `${symbol} ETF`;
}

function getETFType(symbol: string): 'sector' | 'industry' {
  return SECTOR_SYMBOLS.includes(symbol) ? 'sector' : 'industry';
}

interface ETFDetailData {
  symbol: string;
  name: string;
  type: 'sector' | 'industry';
  score: number | null;
  rank: number | null;
  totalCount: number;
  delta3d: number | null;
  delta5d: number | null;
  completeness: number;
  holdings: Array<Holding & { dataStatus?: 'complete' | 'pending' | 'missing' | 'loading' }>;
  dataStatus: Array<{
    source: 'Finviz' | 'MarketChameleon' | '市场数据' | '期权数据' | 'IBKR' | 'Futu';
    status: 'complete' | 'pending' | 'missing' | 'loading';
    updatedAt: string | null;
    count?: number;
  }>;
  coverageRanges: string[];
}

const ETF_DETAILS_CACHE_TTL_MS = 60 * 1000;
const etfDetailsCache = new Map<string, { cachedAt: number; data: ETFDetailData[] }>();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const normalizeRefreshStatus = (status?: string): RefreshResult['status'] => {
  if (status === 'success') return 'success';
  if (status === 'partial_success' || status === 'partial') return 'partial';
  if (status === 'warning') return 'warning';
  if (status === 'snapshot') return 'snapshot';
  if (status === 'failed') return 'failed';
  return 'error';
};

export function TaskDetail({ task, onBack }: TaskDetailProps) {
  const [trendPeriod, setTrendPeriod] = useState<'5d' | '20d' | '63d'>('20d');
  const [trendMetric, setTrendMetric] = useState<'relative' | 'sma20' | 'return20d' | 'score'>('relative');
  const [holdingsModalOpen, setHoldingsModalOpen] = useState(false);
  const [etfModalOpen, setETFModalOpen] = useState(false);
  const [selectedETF, setSelectedETF] = useState<string>('');
  const [selectedCoverage, setSelectedCoverage] = useState<string | undefined>();
  const [coverageRangesByETF, setCoverageRangesByETF] = useState<Record<string, string[]>>({});
  const [resolvedEtfs, setResolvedEtfs] = useState<string[]>(() => normalizeEtfs(task.etfs));
  const resolvedEtfsKey = useMemo(() => getSymbolsKey(resolvedEtfs), [resolvedEtfs]);

  // API 数据状态
  const [etfDetails, setEtfDetails] = useState<ETFDetailData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [trendDates, setTrendDates] = useState<string[]>([]);
  const [trendSeries, setTrendSeries] = useState<RelativeTrendSeries[]>([]);
  const [trendPriceSeries, setTrendPriceSeries] = useState<RelativeTrendSeries[]>([]);
  const [trendSma20Series, setTrendSma20Series] = useState<RelativeTrendSeries[]>([]);
  const [isTrendLoading, setIsTrendLoading] = useState(false);
  const [trendError, setTrendError] = useState<string | null>(null);

  // WebSocket 刷新全部状态
  const [isRefreshingAll, setIsRefreshingAll] = useState(false);
  const [showRefreshModal, setShowRefreshModal] = useState(false);
  const [refreshProgress, setRefreshProgress] = useState({
    completed: 0,
    total: 0,
    currentETF: '',
    message: '',
  });
  const [refreshError, setRefreshError] = useState(false);
  const [refreshComplete, setRefreshComplete] = useState(false);
  const [latestRefreshResults, setLatestRefreshResults] = useState<Record<string, RefreshResult>>({});
  const [sourceUpdatedAtMap, setSourceUpdatedAtMap] = useState<Partial<Record<SourceKey, string>>>(
    () => loadStoredSourceUpdatedAt(task.id)
  );
  const [clockNowMs, setClockNowMs] = useState<number>(() => Date.now());
  const createFallbackETFDetail = (symbol: string, totalCount: number): ETFDetailData => ({
    symbol,
    name: getETFName(symbol),
    type: getETFType(symbol),
    score: null,
    rank: null,
    totalCount,
    delta3d: null,
    delta5d: null,
    completeness: 0,
    holdings: [],
    dataStatus: [
      { source: 'Finviz', status: 'missing', updatedAt: null },
      { source: 'MarketChameleon', status: 'missing', updatedAt: null },
      { source: '市场数据', status: 'missing', updatedAt: null },
      { source: '期权数据', status: 'missing', updatedAt: null },
    ],
    coverageRanges: [],
  });

  const loadETFData = async (symbols: string[], options?: { silent?: boolean; cacheKey?: string }) => {
    const silent = Boolean(options?.silent);
    const cacheKey = options?.cacheKey || `${task.id}|${getSymbolsKey(symbols)}`;
    if (!silent) {
      setIsLoading(true);
      setError(null);
    }
    
    try {
      const etfDataPromises = symbols.map(async (symbol) => {
        try {
          const etf = await api.getETFBySymbol(symbol, true);
          if (etf) {
            return {
              symbol: etf.symbol,
              name: etf.name || getETFName(symbol),
              type: (etf.type as 'sector' | 'industry') || getETFType(symbol),
              score: etf.score > 0 ? etf.score : null,
              rank: etf.rank > 0 ? etf.rank : null,
              totalCount: symbols.length,
              delta3d: etf.delta?.delta3d ?? null,
              delta5d: etf.delta?.delta5d ?? null,
              completeness: etf.completeness || 0,
              holdings: etf.holdings || [],
              dataStatus: generateDataStatus(etf),
              coverageRanges: etf.coverageRanges || [],
            };
          }
        } catch (e) {
          console.warn(`Failed to load ETF ${symbol}:`, e);
        }

        // 回退到基础数据
        return createFallbackETFDetail(symbol, symbols.length);
      });
      
      const results = await Promise.all(etfDataPromises);
      setEtfDetails(results);
      setSelectedETF((prev) => prev || results[0]?.symbol || '');
      etfDetailsCache.set(cacheKey, {
        cachedAt: Date.now(),
        data: results,
      });
    } catch (e) {
      if (!silent) {
        setError(e instanceof Error ? e : new Error('加载数据失败'));
      } else {
        console.warn('Silent ETF refresh failed:', e);
      }
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    const normalized = normalizeEtfs(task.etfs);
    if (!(Array.isArray(task.etfs) || typeof task.etfs === 'string')) {
      return;
    }
    setResolvedEtfs((prev) => {
      const prevKey = getSymbolsKey(prev);
      const nextKey = getSymbolsKey(normalized);
      return prevKey === nextKey ? prev : normalized;
    });
  }, [task.etfs]);

  useEffect(() => {
    setSourceUpdatedAtMap(loadStoredSourceUpdatedAt(task.id));
  }, [task.id]);

  useEffect(() => {
    saveStoredSourceUpdatedAt(task.id, sourceUpdatedAtMap);
  }, [task.id, sourceUpdatedAtMap]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockNowMs(Date.now());
    }, 30 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (resolvedEtfs.length || !task.id) {
      return;
    }
    let cancelled = false;
    const loadTask = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const latestTask = await api.getTaskById(task.id);
        if (cancelled) return;
        const normalized = normalizeEtfs(latestTask?.etfs);
        if (normalized.length) {
          setResolvedEtfs(normalized);
        } else {
          setIsLoading(false);
        }
      } catch (e) {
        console.warn('Failed to load task details:', e);
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };
    loadTask();
    return () => {
      cancelled = true;
    };
  }, [resolvedEtfs.length, task.id]);

  // 加载 ETF 数据
  useEffect(() => {
    if (!resolvedEtfs.length) {
      setEtfDetails([]);
      setTrendDates([]);
      setTrendSeries([]);
      setTrendPriceSeries([]);
      setTrendSma20Series([]);
      if (!task.id) {
        setIsLoading(false);
      }
      return;
    }
    const cacheKey = `${task.id}|${resolvedEtfsKey}`;
    const cached = etfDetailsCache.get(cacheKey);
    if (cached) {
      setEtfDetails(cached.data);
      setSelectedETF((prev) => prev || cached.data[0]?.symbol || '');
      setError(null);
      setIsLoading(false);
      const isFresh = Date.now() - cached.cachedAt < ETF_DETAILS_CACHE_TTL_MS;
      if (isFresh) {
        return;
      }
      void loadETFData(resolvedEtfs, { silent: true, cacheKey });
      return;
    }
    void loadETFData(resolvedEtfs, { cacheKey });
  }, [resolvedEtfsKey, task.id]);

  useEffect(() => {
    if (!task.id) {
      return;
    }
    let cancelled = false;
    const periodValue = trendPeriod === '5d' ? 5 : trendPeriod === '20d' ? 20 : 63;
    const baseSymbol = task.baseIndex?.toUpperCase();
    const sectorSymbol = task.sector?.toUpperCase();
    const reservedColors: Record<string, string> = {
      SPY: '#94a3b8',
      QQQ: '#64748b',
    };
    if (baseSymbol) {
      reservedColors[baseSymbol] = '#94a3b8';
    }
    if (sectorSymbol) {
      reservedColors[sectorSymbol] = '#8b5cf6';
    }
    const cacheKey = toTaskTrendCacheKey(task.id, trendPeriod, trendMetric);
    const cached = taskTrendCache.get(cacheKey);
    if (cached && Date.now() - cached.cachedAt < TASK_TREND_CACHE_TTL_MS) {
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
        const marketSymbols = Array.from(
          new Set([baseSymbol, 'SPY', 'QQQ'].filter((symbol): symbol is string => Boolean(symbol)))
        );
        const warmupPromise =
          trendMetric === 'score' || marketSymbols.length === 0
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

        let resp = await api.getTaskTrendComparison(task.id, periodValue, trendMetric);
        if (
          trendMetric !== 'score' &&
          marketSymbols.length > 0 &&
          !hasRequiredSymbolsData(resp.price_series || resp.series, marketSymbols) &&
          warmupPromise
        ) {
          await warmupPromise;
          if (cancelled) return;
          resp = await api.getTaskTrendComparison(task.id, periodValue, trendMetric);
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
        taskTrendCache.set(cacheKey, {
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
  }, [task.id, task.baseIndex, task.sector, trendPeriod, trendMetric]);

  useEffect(() => {
    if (!resolvedEtfs.length) {
      return;
    }
    let cancelled = false;
    const loadSnapshots = async () => {
      try {
        const snapshots = await api.getEtfScoreSnapshots(resolvedEtfs);
        if (cancelled || !snapshots?.length) {
          return;
        }
        const mappedResults = snapshots.reduce<Record<string, RefreshResult>>((acc, item) => {
          if (!item?.symbol) {
            return acc;
          }
          acc[item.symbol] = {
            status: 'snapshot',
            symbol: item.symbol,
            message: item.date ? `Snapshot ${item.date}` : 'Snapshot',
            score: item.total_score ?? undefined,
            thresholds_pass: item.thresholds_pass ?? undefined,
            breakdown: item.score_breakdown ?? undefined,
          };
          return acc;
        }, {});

        setLatestRefreshResults((prev) => {
          const next = { ...prev };
          Object.entries(mappedResults).forEach(([symbol, result]) => {
            const existing = next[symbol];
            if (!existing || existing.status === 'snapshot') {
              next[symbol] = result;
            }
          });
          return next;
        });
      } catch (e) {
        console.warn('Failed to load ETF score snapshots:', e);
      }
    };
    loadSnapshots();
    return () => {
      cancelled = true;
    };
  }, [resolvedEtfsKey]);

  // 根据 ETF 数据生成数据状态
  const generateDataStatus = (etf: ETF) => {
    const hasHoldings = etf.holdingsCount > 0;
    const hasScore = etf.score > 0;
    
    return [
      { 
        source: 'Finviz' as const, 
        status: hasHoldings ? 'complete' as const : 'missing' as const, 
        updatedAt: hasHoldings ? formatRelativeTime(etf.completeness > 50) : null,
        count: etf.holdingsCount > 0 ? etf.holdingsCount : undefined,
      },
      { 
        source: 'MarketChameleon' as const, 
        status: hasScore ? 'complete' as const : 'pending' as const, 
        updatedAt: hasScore ? formatRelativeTime(etf.completeness > 70) : null,
      },
      { 
        source: '市场数据' as const, 
        status: etf.completeness >= 60 ? 'complete' as const : 'missing' as const, 
        updatedAt: etf.completeness >= 60 ? formatRelativeTime(true) : null,
      },
      { 
        source: '期权数据' as const, 
        status: etf.completeness >= 80 ? 'complete' as const : 'missing' as const, 
        updatedAt: etf.completeness >= 80 ? formatRelativeTime(true) : null,
      },
    ];
  };

  // 格式化相对时间
  const formatRelativeTime = (recent: boolean): string => {
    if (recent) {
      const hours = Math.floor(Math.random() * 3) + 1;
      return `${hours}小时前`;
    }
    return '1天前';
  };

  const taskTypeLabel = {
    rotation: '板块轮动',
    drilldown: '板块下钻',
    momentum: '动能追踪',
  };

  const etfSymbols = resolvedEtfs;
  const latestUpdatedAt = task.updatedAt || task.createdAt;
  const latestUpdatedAtLabel = useMemo(() => formatUpdateDate(latestUpdatedAt), [latestUpdatedAt]);
  const resetBoundaryMs = useMemo(() => getBeijingResetBoundaryMs(clockNowMs), [clockNowMs]);
  const trendSymbolRoleMap = useMemo(() => {
    const roleMap: Record<string, 'market' | 'sector' | 'industry' | 'stock' | 'other'> = {
      SPY: 'market',
      QQQ: 'market',
      IWM: 'market',
      DIA: 'market',
    };
    if (task.baseIndex) {
      roleMap[task.baseIndex.toUpperCase()] = 'market';
    }
    if (task.sector) {
      roleMap[task.sector.toUpperCase()] = 'sector';
    }
    etfDetails.forEach((etf) => {
      roleMap[etf.symbol.toUpperCase()] = etf.type === 'sector' ? 'sector' : 'industry';
    });
    return roleMap;
  }, [etfDetails, task.baseIndex, task.sector]);

  const sourceIndicators = useMemo(() => {
    return (Object.keys(SOURCE_CIRCLE_META) as SourceKey[]).map((sourceKey) => {
      const updatedAt = sourceUpdatedAtMap[sourceKey] || null;
      const updatedAtMs = updatedAt ? new Date(updatedAt).getTime() : Number.NaN;
      const isUpdatedInCurrentWindow = Number.isFinite(updatedAtMs) && updatedAtMs >= resetBoundaryMs;
      const status: SourceStatus = isUpdatedInCurrentWindow ? 'complete' : 'missing';
      const borderColor =
        status === 'complete'
          ? SOURCE_CIRCLE_META[sourceKey].borderColor
          : '#cbd5e1';
      const statusLabel = SOURCE_STATUS_LABEL[status];
      return {
        key: sourceKey,
        label: SOURCE_CIRCLE_META[sourceKey].label,
        status,
        statusLabel,
        borderColor,
        updatedAt: isUpdatedInCurrentWindow ? updatedAt : null,
      };
    });
  }, [resetBoundaryMs, sourceUpdatedAtMap]);

  const refreshImportGuardMessage = useMemo(() => {
    const requiredSources: SourceKey[] = ['finviz', 'marketchameleon'];
    const missing = requiredSources.filter((sourceKey) => {
      const updatedAt = sourceUpdatedAtMap[sourceKey];
      if (!updatedAt) return true;
      const ts = new Date(updatedAt).getTime();
      return !Number.isFinite(ts) || ts < resetBoundaryMs;
    });
    if (!missing.length) return null;

    const sourceLabels: Record<SourceKey, string> = {
      finviz: 'Finviz',
      marketchameleon: 'MarketChameleon',
      ibkr: 'IBKR',
      futu: 'Futu',
    };
    const missingLabel = missing.map((sourceKey) => sourceLabels[sourceKey]).join(' + ');
    const boundaryLabel = formatBeijingBoundaryLabel(resetBoundaryMs);
    return `请先导入 ${missingLabel} 最新数据（北京时间 ${boundaryLabel} 起算）。`;
  }, [resetBoundaryMs, sourceUpdatedAtMap]);

  const trendValueFormatter = useMemo(() => {
    if (trendMetric === 'sma20') {
      return (value: number) => `${value.toFixed(2)}%`;
    }
    if (trendMetric === 'score') {
      return (value: number) => value.toFixed(1);
    }
    return (value: number) => `${value.toFixed(1)}%`;
  }, [trendMetric]);

  const markSourcesUpdated = (sources: SourceKey[], updatedAt?: string) => {
    if (!sources.length) return;
    const normalizedAt = (() => {
      if (!updatedAt) return new Date().toISOString();
      const parsed = new Date(updatedAt);
      return Number.isNaN(parsed.getTime()) ? new Date().toISOString() : parsed.toISOString();
    })();
    setSourceUpdatedAtMap((prev) => {
      const next = { ...prev };
      sources.forEach((sourceKey) => {
        next[sourceKey] = normalizedAt;
      });
      return next;
    });
  };

  const handleRefreshAll = async () => {
    if (refreshImportGuardMessage) {
      alert(refreshImportGuardMessage);
      return;
    }

    setIsRefreshingAll(true);
    setShowRefreshModal(true);
    setRefreshComplete(false);
    setRefreshError(false);
    setRefreshProgress({ completed: 0, total: etfSymbols.length, currentETF: '', message: '已发送刷新请求...' });

    try {
      const resp = await api.refreshTaskAllETFs(task.id);
      // 把后端返回的刷新结果按 symbol 存起来，传给卡片展示细分得分
      const updatedSources = new Set<SourceKey>();
      const mappedResults = (resp.results || []).reduce<Record<string, RefreshResult>>((acc, item) => {
        if (item?.symbol) {
          const sourceKeys = mapDataSourcesToKeys(item.data_sources);
          sourceKeys.forEach((sourceKey) => updatedSources.add(sourceKey));
          acc[item.symbol] = {
            status: normalizeRefreshStatus(item.status),
            symbol: item.symbol,
            message: item.message,
            score: item.score,
            thresholds_pass: item.thresholds_pass,
            breakdown: isRecord(item.breakdown) ? item.breakdown : undefined,
            completeness: item.completeness,
            data_sources: item.data_sources,
          };
        }
        return acc;
      }, {});
      setLatestRefreshResults((prev) => ({ ...prev, ...mappedResults }));
      if (updatedSources.size > 0) {
        markSourcesUpdated(Array.from(updatedSources));
      }

      setRefreshProgress({
        completed: resp.completed ?? etfSymbols.length,
        total: resp.total ?? etfSymbols.length,
        currentETF: '',
        message: resp.message || '刷新完成！',
      });
      setRefreshComplete(true);

      setTimeout(() => {
        if (etfSymbols.length) {
          loadETFData(etfSymbols);
        }
        setShowRefreshModal(false);
      }, 1200);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '刷新失败';
      setRefreshError(true);
      setRefreshProgress({ completed: 0, total: etfSymbols.length, currentETF: '', message: msg });
      setTimeout(() => setShowRefreshModal(false), 2000);
    } finally {
      setIsRefreshingAll(false);
    }
  };

  const handleRefreshHoldings = async (
    symbol: string,
    coverageId: string,
    expectedSymbolsCount?: number,
    progressToken?: string
  ) => {
    // 解析 coverageId (如 "top10", "weight70")
    const isTop = coverageId.startsWith('top');
    const coverageType = isTop ? 'top' : 'weight';
    const valueStr = coverageId.replace('top', '').replace('weight', '');
    const coverageValue = parseInt(valueStr, 10);

    try {
      if (isNaN(coverageValue)) {
        console.error('无效的覆盖范围值');
        throw new Error('无效的覆盖范围值');
      }

      console.log(`开始刷新 ${symbol} 的 ${coverageId} Holdings 数据...`);

      // 调用API刷新Holdings数据
      // 后端应该支持多数据源的并发获取：Finviz, MarketChameleon, 市场数据(IBKR), 期权数据(Futu)等
      const response = await api.refreshHoldingsByCoverage(
        symbol,
        coverageType,
        coverageValue,
        expectedSymbolsCount,
        progressToken
      );

      console.log('Holdings refresh response:', response);

      const responseRecord = response as unknown as Record<string, unknown>;
      const updatedAtRaw = responseRecord['updated_at'];
      const updatedAtFromResponse = typeof updatedAtRaw === 'string' ? updatedAtRaw : undefined;
      const refreshedSources = new Set<SourceKey>();
      const perHoldingUpdates = new Map<
        string,
        {
          dataSources?: Record<string, boolean>;
          dataStatus?: Holding['dataStatus'];
          completeness?: number;
          updatedAt?: string | null;
          score?: number | null;
        }
      >();
      if (Array.isArray(response.updated_stocks)) {
        response.updated_stocks.forEach((stock) => {
          if (!isRecord(stock)) return;

          const tickerRaw = stock['ticker'];
          const ticker = typeof tickerRaw === 'string' ? tickerRaw.trim().toUpperCase() : '';
          if (!ticker) return;

          const dataSourcesArray = Array.isArray(stock.data_sources) ? stock.data_sources : [];
          const sourceFlags: Record<string, boolean> = {
            finviz: false,
            marketchameleon: false,
            market_chameleon: false,
            ibkr: false,
            market_data: false,
            futu: false,
            options_data: false,
          };
          dataSourcesArray.forEach((source) => {
            if (typeof source !== 'string') return;
            const normalized = source.trim().toLowerCase();
            const sourceKey = normalizeSourceKey(normalized);
            if (sourceKey) {
              refreshedSources.add(sourceKey);
            }
            if (normalized.includes('finviz')) {
              sourceFlags.finviz = true;
            }
            if (normalized.includes('marketchameleon') || normalized.includes('market_chameleon') || normalized.includes('mc')) {
              sourceFlags.marketchameleon = true;
              sourceFlags.market_chameleon = true;
            }
            if (normalized.includes('ibkr') || normalized.includes('market_data')) {
              sourceFlags.ibkr = true;
              sourceFlags.market_data = true;
            }
            if (normalized.includes('futu') || normalized.includes('options_data')) {
              sourceFlags.futu = true;
              sourceFlags.options_data = true;
            }
          });

          const rawStatus = typeof stock['data_status'] === 'string' ? stock['data_status'] : undefined;
          const dataStatus: Holding['dataStatus'] =
            rawStatus === 'complete' || rawStatus === 'pending' || rawStatus === 'missing' || rawStatus === 'loading'
              ? rawStatus
              : undefined;

          const completenessRaw = stock['completeness'];
          const completeness = typeof completenessRaw === 'number' && Number.isFinite(completenessRaw)
            ? completenessRaw
            : undefined;

          const stockUpdatedAtRaw = stock['updated_at'];
          const stockUpdatedAt = typeof stockUpdatedAtRaw === 'string' ? stockUpdatedAtRaw : updatedAtFromResponse ?? null;

          const scoreRaw = stock['score'];
          const score = typeof scoreRaw === 'number' && Number.isFinite(scoreRaw) ? scoreRaw : null;

          perHoldingUpdates.set(ticker, {
            dataSources: dataSourcesArray.length > 0 ? sourceFlags : undefined,
            dataStatus,
            completeness,
            updatedAt: stockUpdatedAt,
            score,
          });
        });
      }
      if (refreshedSources.size > 0) {
        markSourcesUpdated(Array.from(refreshedSources), updatedAtFromResponse);
      }

      if (perHoldingUpdates.size > 0) {
        setEtfDetails((prev) =>
          prev.map((etfDetail) => {
            if (etfDetail.symbol !== symbol) return etfDetail;
            const nextHoldings = etfDetail.holdings.map((holding) => {
              const update = perHoldingUpdates.get(holding.ticker.toUpperCase());
              if (!update) return holding;
              const mergedDataSources = update.dataSources
                ? { ...(holding.dataSources || {}), ...update.dataSources }
                : holding.dataSources;
              return {
                ...holding,
                ...(mergedDataSources ? { dataSources: mergedDataSources } : {}),
                ...(update.dataStatus ? { dataStatus: update.dataStatus } : {}),
                ...(typeof update.completeness === 'number' ? { completeness: update.completeness } : {}),
                ...(update.updatedAt ? { updatedAt: update.updatedAt } : {}),
                ...(typeof update.score === 'number' ? { score: update.score } : {}),
              };
            });
            return {
              ...etfDetail,
              holdings: nextHoldings,
            };
          })
        );
      }

      // 当后端未返回逐标的更新结果时，回退为全量重载
      if (perHoldingUpdates.size === 0) {
        setTimeout(() => {
          if (etfSymbols.length) {
            loadETFData(etfSymbols, { silent: true });
          }
        }, 1000);
      }

      return response;
    } catch (e) {
      if (e instanceof api.TimeoutError) {
        const estimatedCount =
          typeof expectedSymbolsCount === 'number' && expectedSymbolsCount > 0
            ? expectedSymbolsCount
            : coverageType === 'top'
              ? coverageValue
              : undefined;
        if (progressToken) {
          const recoveryAttempts = 8;
          const recoveryIntervalMs = 3000;
          for (let attempt = 0; attempt < recoveryAttempts; attempt += 1) {
            let progress: api.HoldingsRefreshProgress | null = null;
            try {
              progress = await api.getHoldingsRefreshProgress(symbol, progressToken);
            } catch (progressError) {
              if (progressError instanceof Error && progressError.message) {
                console.warn('Failed to recover holdings refresh progress after timeout:', progressError.message);
              }
            }
            if (progress?.status === 'completed') {
              return {
                status: 'success',
                symbol: symbol.toUpperCase(),
                coverage: coverageId.toLowerCase(),
                stocks_count:
                  typeof progress.total === 'number' && progress.total > 0
                    ? progress.total
                    : estimatedCount ?? 0,
                total_weight: 0,
                completeness: {},
                updated_stocks: [],
                updated_at: progress.updated_at || new Date().toISOString(),
                message: progress.message || '刷新完成（超时后已同步）',
              };
            }
            if (progress?.status === 'error') {
              const backendError =
                typeof progress.message === 'string' && progress.message.trim() !== ''
                  ? progress.message
                  : '刷新失败';
              throw new Error(backendError);
            }
            await new Promise<void>((resolve) => {
              window.setTimeout(resolve, recoveryIntervalMs);
            });
          }
        }
        const detail = estimatedCount ? `（预计 ${estimatedCount} 个标的）` : '';
        throw new Error(`刷新超时${detail}，请重试或缩小覆盖范围（如 Top10/Top15）`);
      }
      console.error('Failed to refresh holdings:', e);
      throw e;
    }
  };

  const handleOpenHoldingsModal = (symbol: string, coverageId?: string) => {
    setSelectedETF(symbol);
    setSelectedCoverage(coverageId);
    setHoldingsModalOpen(true);
  };

  const handleOpenETFImport = () => {
    const targetSymbol = selectedETF || etfDetails[0]?.symbol || etfSymbols[0];
    if (!targetSymbol) {
      alert('暂无可导入的 ETF');
      return;
    }
    setSelectedETF(targetSymbol);
    setETFModalOpen(true);
  };

  if (isLoading) {
    return <LoadingState message="正在加载监控任务数据..." />;
  }

  if (error) {
    return <ErrorMessage error={error} onRetry={() => loadETFData(etfSymbols)} />;
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="p-2 rounded-[var(--radius-sm)] text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold">{task.title}</h1>
              <span
                className="px-2.5 py-1 rounded-full text-xs font-medium"
                style={{ background: 'rgba(139, 92, 246, 0.1)', color: 'var(--accent-purple)' }}
              >
                {taskTypeLabel[task.type]}
              </span>
            </div>
            <div className="flex items-center gap-4 mt-1 text-sm text-[var(--text-muted)]">
              <span>基准: {task.baseIndex}</span>
              {task.sector && <span>板块: {task.sector}</span>}
              <span className="inline-flex items-center gap-1.5">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 6v6l4 2" />
                </svg>
                <span className="font-medium text-[var(--text-primary)]">更新时间: {latestUpdatedAtLabel}</span>
              </span>
            </div>
          </div>
        </div>
        <div className="flex flex-col items-end gap-3">
          <div className="flex items-center gap-3">
            <button
              onClick={handleRefreshAll}
              disabled={isRefreshingAll}
              className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRefreshingAll ? (
                <>
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Refreshing...
                </>
              ) : (
                'Refresh ETFs'
              )}
            </button>
            <button
              onClick={handleOpenETFImport}
              className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--bg-secondary)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors flex items-center gap-2"
            >
              Export ETFs
            </button>
          </div>
          <div className="flex items-center gap-3 pr-1">
            {sourceIndicators.map((indicator) => (
              <div key={indicator.key} className="group relative inline-flex">
                <span
                  className="block h-5 w-5 rounded-full border-[2.5px] bg-transparent"
                  style={{ borderColor: indicator.borderColor }}
                  aria-label={`${indicator.label}: ${indicator.statusLabel}`}
                  title={`${indicator.label}: ${formatUpdateDateTime(indicator.updatedAt)}`}
                />
                <div className="pointer-events-none absolute right-0 top-7 z-20 w-max min-w-[176px] translate-y-1 rounded-[var(--radius-sm)] border border-[var(--border-light)] bg-[var(--bg-primary)] px-3 py-2 text-xs text-[var(--text-secondary)] opacity-0 shadow-lg invisible transition-all duration-150 group-hover:translate-y-0 group-hover:opacity-100 group-hover:visible">
                  <p className="font-medium text-[var(--text-primary)]">
                    {indicator.label}: {formatUpdateDateTime(indicator.updatedAt)}
                  </p>
                  <p className="mt-1">状态: {indicator.statusLabel}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Refresh Progress Modal */}
      <RefreshProgressModal
        isOpen={showRefreshModal}
        title="正在刷新 ETF 数据"
        currentItem={refreshProgress.currentETF}
        message={refreshProgress.message}
        completed={refreshProgress.completed}
        total={refreshProgress.total}
        isError={refreshError}
        isComplete={refreshComplete}
      />

      {/* Trend Chart Section */}
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
          baseSymbol={task.baseIndex}
          symbolRoleMap={trendSymbolRoleMap}
        />
        {isTrendLoading && (
          <div className="text-xs text-[var(--text-muted)] mt-2">走势数据加载中...</div>
        )}
      </div>

      {/* ETF Cards Section */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold">监控ETF ({etfSymbols.length})</h3>
        </div>
        <div className="grid grid-cols-3 gap-5">
          {etfDetails.map((etf) => {
            // 合并后端返回的 coverageRanges 和本地状态
            const backendRanges = etf.coverageRanges || [];
            const localRanges = coverageRangesByETF[etf.symbol] || [];
            const mergedRanges = [...new Set([...backendRanges, ...localRanges])];
            
            return (
              <ETFDetailCard
                key={etf.symbol}
                etf={etf}
                coverageRanges={mergedRanges}
                refreshResult={latestRefreshResults[etf.symbol]}
                onRefreshHoldings={(coverageId: string, expectedSymbolsCount?: number, progressToken?: string) =>
                  handleRefreshHoldings(etf.symbol, coverageId, expectedSymbolsCount, progressToken)
                }
                onImportHoldings={(coverageId?: string) => handleOpenHoldingsModal(etf.symbol, coverageId)}
                onViewStockDetail={(ticker) => {
                  console.log('View stock detail:', ticker);
                  // TODO: Navigate to stock detail page
                }}
              />
            );
          })}
        </div>
      </div>

      {/* Modals */}
      <HoldingsImportModal
        isOpen={holdingsModalOpen}
        onClose={() => {
          setHoldingsModalOpen(false);
          setSelectedCoverage(undefined);
        }}
        etfSymbol={selectedETF}
        selectedCoverage={selectedCoverage}
        onImport={async (data) => {
          console.log('Import holdings:', selectedETF, data);
          if (selectedETF && data.jsonData) {
            try {
              const parsedData = JSON.parse(data.jsonData);
              if (!Array.isArray(parsedData)) {
                throw new Error('JSON 数据必须是数组格式');
              }
              const importedAt = new Date().toISOString();
              const importedSymbols = new Set(
                parsedData
                  .map((item) => {
                    if (!isRecord(item)) return null;
                    const symbolRaw = item.Ticker ?? item.ticker ?? item.Symbol ?? item.symbol;
                    return typeof symbolRaw === 'string' ? symbolRaw.trim().toUpperCase() : null;
                  })
                  .filter((value): value is string => Boolean(value))
              );
              
              // 调用后端 API 导入数据
              if (data.source === 'finviz') {
                await api.importFinvizData(selectedETF, data.coverage, parsedData);
                markSourcesUpdated(['finviz'], importedAt);
              } else {
                await api.importMCData(parsedData);
                markSourcesUpdated(['marketchameleon'], importedAt);
              }

              // 更新本地 coverage 范围（后端未落库时也能立刻显示）
              setCoverageRangesByETF((prev) => {
                const existing = new Set(prev[selectedETF] || []);
                existing.add(data.coverage);
                return { ...prev, [selectedETF]: Array.from(existing) };
              });

              // 先做乐观更新，确保卡片即时反馈
              if (importedSymbols.size > 0) {
                setEtfDetails((prev) =>
                  prev.map((etfDetail) => {
                    if (etfDetail.symbol !== selectedETF) return etfDetail;
                    const nextHoldings = etfDetail.holdings.map((holding) => {
                      if (!importedSymbols.has(holding.ticker.toUpperCase())) {
                        return holding;
                      }
                      const mergedDataSources = { ...(holding.dataSources || {}) };
                      if (data.source === 'finviz') {
                        mergedDataSources.finviz = true;
                      } else {
                        mergedDataSources.marketchameleon = true;
                        mergedDataSources.market_chameleon = true;
                      }

                      const finvizReady = Boolean(mergedDataSources.finviz);
                      const mcReady = Boolean(
                        mergedDataSources.marketchameleon || mergedDataSources.market_chameleon
                      );
                      const dataStatus: Holding['dataStatus'] =
                        finvizReady && mcReady
                          ? 'complete'
                          : finvizReady || mcReady
                            ? 'pending'
                            : 'missing';
                      const completeness =
                        finvizReady && mcReady ? 100 : finvizReady || mcReady ? 50 : 0;

                      return {
                        ...holding,
                        dataSources: mergedDataSources,
                        dataStatus,
                        completeness,
                        updatedAt: importedAt,
                      };
                    });
                    const existingRanges = new Set(etfDetail.coverageRanges || []);
                    existingRanges.add(data.coverage);
                    return {
                      ...etfDetail,
                      holdings: nextHoldings,
                      coverageRanges: Array.from(existingRanges),
                    };
                  })
                );
              }

              // 再拉后端真实数据，确保前后端一致
              if (etfSymbols.length) {
                await loadETFData(etfSymbols, { silent: true });
              }
            } catch (e) {
              console.error('Import failed:', e);
              const message = e instanceof Error ? e.message : '导入失败，请检查数据格式';
              throw new Error(message);
            }
          }
        }}
      />
      <ETFImportModal
        isOpen={etfModalOpen}
        onClose={() => setETFModalOpen(false)}
        etfSymbol={selectedETF}
        onImport={(data) => {
          console.log('Import ETF data:', selectedETF, data);
          if (data.source === 'finviz') {
            markSourcesUpdated(['finviz']);
          } else {
            markSourcesUpdated(['marketchameleon']);
          }
          if (etfSymbols.length) {
            loadETFData(etfSymbols, { silent: true });
          }
        }}
      />
    </div>
  );
}
