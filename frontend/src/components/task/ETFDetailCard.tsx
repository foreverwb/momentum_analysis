import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { RefreshProgressModal } from '../modal';
import type { RefreshResult } from '../../types';
import { getHoldingsRefreshProgress } from '../../services/api';

interface DataStatus {
  source: 'Finviz' | 'MarketChameleon' | '市场数据' | '期权数据' | 'IBKR' | 'Futu';
  status: 'complete' | 'pending' | 'missing' | 'loading';
  updatedAt: string | null;
  count?: number;
}

interface HoldingSummary {
  ticker: string;
  weight: number;
  dataStatus?: 'complete' | 'pending' | 'missing' | 'loading';
  completeness?: number;  // 0-100 percentage
  score?: number | null; // 个股得分
  price?: number | null;
  deviationFrom20ma?: number | null;
  aboveSma20?: boolean | null;
  dataSources?: Record<string, boolean>;  // { finviz, market_chameleon, market_data, options_data }
  updatedAt?: string | null;  // timestamp
}

type DmaFilterOption = 'above_spy' | 'above_qqq';

interface ETFDetailCardProps {
  etf: {
    symbol: string;
    name: string;
    type: 'sector' | 'industry';
    score: number | null;
    rank: number | null;
    totalCount: number;
    delta3d: number | null;
    delta5d: number | null;
    completeness: number;
    holdings: HoldingSummary[];
    dataStatus: DataStatus[];
  };
  coverageRanges?: string[];
  onRefreshHoldings: (coverageId: string, expectedSymbolsCount?: number, progressToken?: string) => Promise<unknown>;
  onImportHoldings?: (coverageId?: string) => void;
  onViewStockDetail?: (ticker: string) => void;
  refreshResult?: RefreshResult;
  dmaFilter?: DmaFilterOption;
  dmaBenchmarkBelow20?: boolean | null;
}

type CoverageOption = {
  id: 'top10' | 'top15' | 'top20' | 'top30' | 'weight60' | 'weight65' | 'weight70' | 'weight75' | 'weight80' | 'weight85' | 'all';
  label: string;
  type: 'top' | 'weight' | 'all';
  value?: number;
};

const COVERAGE_OPTIONS: CoverageOption[] = [
  { id: 'top10', label: 'Top10', type: 'top', value: 10 },
  { id: 'top15', label: 'Top15', type: 'top', value: 15 },
  { id: 'top20', label: 'Top20', type: 'top', value: 20 },
  { id: 'top30', label: 'Top30', type: 'top', value: 30 },
  { id: 'weight60', label: 'Weight60%', type: 'weight', value: 60 },
  { id: 'weight65', label: 'Weight65%', type: 'weight', value: 65 },
  { id: 'weight70', label: 'Weight70%', type: 'weight', value: 70 },
  { id: 'weight75', label: 'Weight75%', type: 'weight', value: 75 },
  { id: 'weight80', label: 'Weight80%', type: 'weight', value: 80 },
  { id: 'weight85', label: 'Weight85%', type: 'weight', value: 85 },
  { id: 'all', label: 'ALL', type: 'all' },
];

const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

type CoverageSourceKey = 'finviz' | 'marketchameleon' | 'ibkr' | 'futu';

const COVERAGE_SOURCE_META: Record<CoverageSourceKey, { label: string; color: string }> = {
  finviz: { label: 'Finviz', color: '#93c5fd' },
  marketchameleon: { label: 'MarketChameleon', color: '#86efac' },
  ibkr: { label: '市场数据(IBKR)', color: '#fca5a5' },
  futu: { label: '期权数据(Futu)', color: '#fb923c' },
};

interface RefreshDimension {
  score?: number;
  data?: Record<string, unknown>;
}

const toNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const resolveDimension = (
  breakdown: RefreshResult['breakdown'],
  key: 'rel_mom' | 'trend_quality' | 'breadth' | 'options_confirm'
): RefreshDimension => {
  const source = breakdown?.[key];
  if (source === undefined || source === null) {
    return {};
  }
  if (typeof source === 'number') {
    return { score: source };
  }
  if (isRecord(source)) {
    return {
      score: toNumber(source.score),
      data: isRecord(source.data) ? source.data : undefined,
    };
  }
  return {};
};

// 评分维度卡片组件
interface ScoreDimensionCardProps {
  label: string;
  weight: string;
  score: number | undefined;
  color: string;
  data?: Record<string, unknown>;
}

function ScoreDimensionCard({
  label,
  weight,
  score,
  color,
  data,
}: ScoreDimensionCardProps) {
  const [showDetails, setShowDetails] = React.useState(false);

  return (
    <div
      className="bg-[var(--bg-secondary)] rounded-[var(--radius-md)] p-3 cursor-pointer hover:bg-[var(--bg-tertiary)] transition-colors"
      onClick={() => data && setShowDetails(!showDetails)}
      title={data ? '点击查看详细数据' : ''}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
        <span className="text-[10px] text-[var(--text-muted)]">{weight}</span>
      </div>
      <div className="text-2xl font-bold" style={{ color }}>
        {score !== undefined ? Math.round(score) : '--'}
      </div>

      {/* Expandable details */}
      {showDetails && data && (
        <div className="mt-2 pt-2 border-t border-[var(--border-light)] text-[10px] text-[var(--text-muted)] space-y-1">
          {Object.entries(data).slice(0, 5).map(([key, value]) => (
            <div key={key} className="flex justify-between gap-2">
              <span className="flex-shrink-0">{key}:</span>
              <span className="font-mono text-right flex-shrink-0">
                {typeof value === 'number' ? value.toFixed(2) : String(value)}
              </span>
            </div>
          ))}
          {Object.keys(data).length > 5 && (
            <div className="text-[9px] italic">...及其他 {Object.keys(data).length - 5} 项</div>
          )}
        </div>
      )}
    </div>
  );
}

const formatWeight = (value: number): string => {
  if (value >= 10) {
    return value.toFixed(1);
  }
  return value.toFixed(2);
};

const isHoldingAbove20Dma = (holding: HoldingSummary): boolean => {
  if (typeof holding.aboveSma20 === 'boolean') {
    return holding.aboveSma20;
  }
  if (typeof holding.deviationFrom20ma === 'number' && Number.isFinite(holding.deviationFrom20ma)) {
    return holding.deviationFrom20ma > 0;
  }
  return false;
};

const normalizeIsoTimestamp = (value?: string | null): string | null => {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Backend may return naive UTC timestamps; normalize to explicit UTC for stable parsing.
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(trimmed)) {
    return `${trimmed}Z`;
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(trimmed)) {
    return `${trimmed.replace(' ', 'T')}Z`;
  }
  return trimmed;
};

const BEIJING_DATETIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const formatUpdatedAt = (value?: string | null): string => {
  if (!value) return '--';
  const normalized = normalizeIsoTimestamp(value);
  if (!normalized) return '--';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return '--';
  const parts = BEIJING_DATETIME_FORMATTER.formatToParts(date);
  const month = parts.find((part) => part.type === 'month')?.value ?? '--';
  const day = parts.find((part) => part.type === 'day')?.value ?? '--';
  const hour = parts.find((part) => part.type === 'hour')?.value ?? '--';
  const minute = parts.find((part) => part.type === 'minute')?.value ?? '--';
  return `${month}-${day} ${hour}:${minute}`;
};

const getCoverageHoldings = (holdings: HoldingSummary[], option: CoverageOption): HoldingSummary[] => {
  if (!holdings.length) {
    return [];
  }
  if (option.type === 'all') {
    return holdings;
  }
  const coverageValue = option.value ?? 0;
  if (option.type === 'top') {
    return holdings.slice(0, coverageValue);
  }
  let sum = 0;
  const picked: HoldingSummary[] = [];
  for (const holding of holdings) {
    picked.push(holding);
    sum += holding.weight;
    if (sum >= coverageValue) {
      break;
    }
  }
  return picked;
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

const parseUpdatedAtMs = (value?: string | null): number => {
  if (!value) return Number.NaN;
  const normalized = normalizeIsoTimestamp(value);
  if (!normalized) return Number.NaN;
  return new Date(normalized).getTime();
};

const hasFreshHoldingData = (holding: HoldingSummary, boundaryMs: number): boolean => {
  const updatedAtMs = parseUpdatedAtMs(holding.updatedAt);
  if (!Number.isFinite(updatedAtMs) || updatedAtMs < boundaryMs) {
    return false;
  }

  const sourceFlags = [
    getHoldingSourceAvailable(holding, 'finviz'),
    getHoldingSourceAvailable(holding, 'marketchameleon'),
    getHoldingSourceAvailable(holding, 'ibkr'),
    getHoldingSourceAvailable(holding, 'futu'),
  ].filter((flag): flag is boolean => typeof flag === 'boolean');

  // 若已具备来源明细，则“完整”定义为当前可识别来源全部可用且为当日有效
  if (sourceFlags.length > 0) {
    return sourceFlags.every((flag) => flag === true);
  }

  // 回退逻辑（历史数据兼容）
  if (holding.dataStatus === 'missing' || holding.dataStatus === 'pending') {
    return false;
  }
  return true;
};

const isHoldingSourceFresh = (
  holding: HoldingSummary,
  sourceKey: CoverageSourceKey,
  boundaryMs: number
): boolean => {
  const sourceReady = getHoldingSourceAvailable(holding, sourceKey) === true;
  if (!sourceReady) return false;
  const updatedAtMs = parseUpdatedAtMs(holding.updatedAt);
  return Number.isFinite(updatedAtMs) && updatedAtMs >= boundaryMs;
};

const getHoldingSourceAvailable = (
  holding: HoldingSummary,
  sourceKey: CoverageSourceKey
): boolean | undefined => {
  const dataSources = holding.dataSources;
  if (!dataSources) return undefined;
  const resolveAliasAvailability = (keys: string[]): boolean | undefined => {
    const values = keys
      .map((key) => dataSources[key])
      .filter((value): value is boolean => typeof value === 'boolean');
    if (!values.length) {
      return undefined;
    }
    return values.some((value) => value === true);
  };
  if (sourceKey === 'finviz') {
    return resolveAliasAvailability(['finviz']);
  }
  if (sourceKey === 'marketchameleon') {
    return resolveAliasAvailability(['marketchameleon', 'market_chameleon', 'mc_options']);
  }
  if (sourceKey === 'ibkr') {
    return resolveAliasAvailability(['ibkr', 'market_data', 'ibkr_price', 'ibkr_relmom', 'ibkr_trend']);
  }
  return resolveAliasAvailability(['futu', 'options_data', 'futu_iv']);
};

const getCoverageAccentColor = (option: CoverageOption): string => {
  switch (option.id) {
    case 'top10':
      return '#f59e0b';
    case 'top15':
      return '#ec4899';
    case 'top20':
      return '#3b82f6';
    case 'top30':
      return '#10b981';
    case 'all':
      return '#475569';
    default:
      return option.type === 'weight' ? '#8b5cf6' : 'var(--accent-blue)';
  }
};

const createProgressToken = (): string => {
  const tokenCore =
    typeof globalThis.crypto !== 'undefined' && typeof globalThis.crypto.randomUUID === 'function'
      ? globalThis.crypto.randomUUID().replace(/-/g, '')
      : `${Date.now()}_${Math.random().toString(36).slice(2, 12)}`;
  return `hld_${tokenCore}`;
};

const copyTextToClipboard = async (text: string): Promise<void> => {
  if (
    typeof navigator !== 'undefined' &&
    navigator.clipboard &&
    typeof navigator.clipboard.writeText === 'function'
  ) {
    await navigator.clipboard.writeText(text);
    return;
  }

  if (typeof document === 'undefined') {
    throw new Error('Clipboard API unavailable');
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  textarea.style.pointerEvents = 'none';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(textarea);

  if (!copied) {
    throw new Error('Copy command failed');
  }
};

export function ETFDetailCard({
  etf,
  coverageRanges = [],
  onRefreshHoldings,
  onImportHoldings,
  onViewStockDetail,
  refreshResult,
  dmaFilter: _dmaFilter = 'above_spy',
  dmaBenchmarkBelow20 = null,
}: ETFDetailCardProps) {
  const [activeCoverage, setActiveCoverage] = useState<CoverageOption['id']>('top10');
  const [coverageCopyState, setCoverageCopyState] = useState<'idle' | 'success' | 'error'>('idle');
  const lastRefreshResult = refreshResult || null;
  const relMom = resolveDimension(lastRefreshResult?.breakdown, 'rel_mom');
  const trendQuality = resolveDimension(lastRefreshResult?.breakdown, 'trend_quality');
  const breadth = resolveDimension(lastRefreshResult?.breakdown, 'breadth');
  const optionsConfirm = resolveDimension(lastRefreshResult?.breakdown, 'options_confirm');

  // Unified refresh modal state for both ETF and Holdings refresh
  const [showRefreshModal, setShowRefreshModal] = useState(false);
  const [refreshModalTitle, setRefreshModalTitle] = useState('');
  const [refreshModalProgress, setRefreshModalProgress] = useState({
    completed: 0,
    total: 100,
    currentItem: '',
    message: '',
  });
  const [refreshModalError, setRefreshModalError] = useState(false);
  const [refreshModalComplete, setRefreshModalComplete] = useState(false);

  // Holdings refresh state
  const [holdingsRefreshState, setHoldingsRefreshState] = useState<{
    isLoading: boolean;
    progress: number;
    message: string;
    error?: string;
  }>({
    isLoading: false,
    progress: 0,
    message: '',
  });

  // Top holdings section collapse state
  const [isTopHoldingsCollapsed, setIsTopHoldingsCollapsed] = useState(false);
  const [clockNowMs, setClockNowMs] = useState<number>(() => Date.now());

  const sortedHoldings = useMemo(() => {
    const holdings = etf.holdings || [];
    return [...holdings].sort((a, b) => b.weight - a.weight);
  }, [etf.holdings]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockNowMs(Date.now());
    }, 30 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  // 按得分排序的前五标的（若无得分则按权重排序）
  const topScoreHoldings = useMemo(() => {
    const holdings = etf.holdings || [];
    return [...holdings]
      .sort((a, b) => {
        const scoreA = a.score ?? -Infinity;
        const scoreB = b.score ?? -Infinity;
        if (scoreA === scoreB) {
          return b.weight - a.weight;
        }
        return scoreB - scoreA;
      })
      .slice(0, 5);
  }, [etf.holdings]);

  // 根据传入的 coverageRanges 过滤可用选项
  const availableCoverageOptions = useMemo(() => {
    if (!coverageRanges.length) {
      return [];
    }
    const available = new Set(coverageRanges.map((value) => value.trim().toLowerCase()));
    return COVERAGE_OPTIONS.filter((option) => available.has(option.id));
  }, [coverageRanges]);

  useEffect(() => {
    if (!availableCoverageOptions.length) {
      return;
    }
    if (!availableCoverageOptions.some((option) => option.id === activeCoverage)) {
      setActiveCoverage(availableCoverageOptions[0].id);
    }
  }, [activeCoverage, availableCoverageOptions]);

  useEffect(() => {
    setCoverageCopyState('idle');
  }, [activeCoverage]);

  const showCoverageSection = availableCoverageOptions.length >= 1;
  const beijingResetBoundaryMs = useMemo(() => getBeijingResetBoundaryMs(clockNowMs), [clockNowMs]);

  const coverageStatsByOption = useMemo(() => {
    const stats = new Map<CoverageOption['id'], {
      total: number;
      completeCount: number;
      pendingCount: number;
      allComplete: boolean;
    }>();

    availableCoverageOptions.forEach((option) => {
      const holdings = getCoverageHoldings(sortedHoldings, option);
      const completeCount = holdings.filter((holding) => hasFreshHoldingData(holding, beijingResetBoundaryMs)).length;
      const pendingCount = Math.max(0, holdings.length - completeCount);
      stats.set(option.id, {
        total: holdings.length,
        completeCount,
        pendingCount,
        allComplete: holdings.length > 0 && pendingCount === 0,
      });
    });

    return stats;
  }, [availableCoverageOptions, sortedHoldings, beijingResetBoundaryMs]);

  const activeOption = availableCoverageOptions.find((option) => option.id === activeCoverage) || availableCoverageOptions[0] || COVERAGE_OPTIONS[0];
  const activeHoldings = getCoverageHoldings(sortedHoldings, activeOption);
  const isDmaFilterActive = dmaBenchmarkBelow20 === true;
  const dmaFilteredHoldings = useMemo(() => {
    if (!isDmaFilterActive) {
      return activeHoldings;
    }
    return activeHoldings.filter((holding) => isHoldingAbove20Dma(holding));
  }, [activeHoldings, isDmaFilterActive]);
  const displayedHoldings = isDmaFilterActive ? dmaFilteredHoldings : activeHoldings;
  const displayCoverageSum = displayedHoldings.reduce((sum, item) => sum + item.weight, 0);
  const activeCoverageStats = coverageStatsByOption.get(activeOption.id) || {
    total: activeHoldings.length,
    completeCount: activeHoldings.filter((holding) => hasFreshHoldingData(holding, beijingResetBoundaryMs)).length,
    pendingCount: activeHoldings.filter((holding) => !hasFreshHoldingData(holding, beijingResetBoundaryMs)).length,
    allComplete: false,
  };

  const activeCoverageSourceIndicators = useMemo(() => {
    const latestMs = activeHoldings.reduce((acc, holding) => {
      const ts = parseUpdatedAtMs(holding.updatedAt);
      return Number.isFinite(ts) ? Math.max(acc, ts) : acc;
    }, Number.NEGATIVE_INFINITY);
    const latestUpdatedAt = Number.isFinite(latestMs) ? new Date(latestMs).toISOString() : null;

    return (Object.keys(COVERAGE_SOURCE_META) as CoverageSourceKey[]).map((sourceKey) => {
      const totalCount = activeHoldings.length;
      const knownCount = activeHoldings.filter(
        (holding) => typeof getHoldingSourceAvailable(holding, sourceKey) === 'boolean'
      ).length;
      const freshCount = activeHoldings.filter(
        (holding) => isHoldingSourceFresh(holding, sourceKey, beijingResetBoundaryMs)
      ).length;
      const isComplete = totalCount > 0 && knownCount === totalCount && freshCount === totalCount;
      const isPartial = !isComplete && freshCount > 0;
      const statusLabel = isComplete ? '完备' : isPartial ? '部分' : '缺失';
      return {
        key: sourceKey,
        label: COVERAGE_SOURCE_META[sourceKey].label,
        color: COVERAGE_SOURCE_META[sourceKey].color,
        isComplete,
        isPartial,
        freshCount,
        totalCount,
        statusLabel,
        updatedAt: latestUpdatedAt,
      };
    });
  }, [activeHoldings, beijingResetBoundaryMs]);

  const formatDelta = (value: number | null): { text: string; className: string } => {
    if (value === null || value === undefined) {
      return { text: '--', className: '' };
    }
    if (value > 0) {
      return { text: `+${value.toFixed(2)}`, className: 'text-[var(--accent-green)]' };
    }
    if (value < 0) {
      return { text: `${value.toFixed(2)}`, className: 'text-[var(--accent-red)]' };
    }
    return { text: '0', className: '' };
  };

  const delta3d = formatDelta(etf.delta3d);
  const delta5d = formatDelta(etf.delta5d);

  useEffect(() => {
    if (coverageCopyState === 'idle') {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setCoverageCopyState('idle');
    }, 1600);
    return () => window.clearTimeout(timer);
  }, [coverageCopyState]);

  const handleCopyCoverageSymbols = useCallback(async () => {
    if (!displayedHoldings.length) {
      return;
    }
    try {
      const tickers = displayedHoldings.map((holding) => holding.ticker).join(', ');
      await copyTextToClipboard(tickers);
      setCoverageCopyState('success');
    } catch (error) {
      console.error('Failed to copy coverage symbols:', error);
      setCoverageCopyState('error');
    }
  }, [displayedHoldings]);

  const handleRefreshHoldings = useCallback(async () => {
    // 防止重复点击
    if (holdingsRefreshState.isLoading) return;
    const estimatedSymbolsCount =
      activeHoldings.length > 0
        ? activeHoldings.length
        : activeOption.type === 'top'
          ? activeOption.value
          : undefined;
    const progressToken = createProgressToken();
    const defaultProgressTotal =
      estimatedSymbolsCount && estimatedSymbolsCount > 0 ? estimatedSymbolsCount : 1;

    // 立即更新UI状态
    setHoldingsRefreshState({
      isLoading: true,
      progress: 0,
      message:
        estimatedSymbolsCount && estimatedSymbolsCount > 0
          ? `已发送请求，预计处理 ${estimatedSymbolsCount} 个标的...`
          : '已发送请求，等待后端返回...',
    });

    // 立即显示模态框 - 这是关键
    setShowRefreshModal(true);
    setRefreshModalTitle(`正在刷新 ${etf.symbol} ${activeOption.label} Holdings`);
    setRefreshModalProgress({
      completed: 0,
      total: estimatedSymbolsCount && estimatedSymbolsCount > 0 ? estimatedSymbolsCount : 1,
      currentItem: '',
      message:
        estimatedSymbolsCount && estimatedSymbolsCount > 0
          ? `请求中...（${estimatedSymbolsCount} 个标的）`
          : '请求中...',
    });
    setRefreshModalError(false);
    setRefreshModalComplete(false);

    let stopPolling = false;
    let pollTimer: number | null = null;
    let pollFailureCount = 0;
    const pollProgress = async () => {
      if (stopPolling) return;
      try {
        const progress = await getHoldingsRefreshProgress(etf.symbol, progressToken);
        if (stopPolling) return;
        pollFailureCount = 0;

        const total =
          typeof progress.total === 'number' && progress.total > 0
            ? progress.total
            : defaultProgressTotal;
        const completedRaw = typeof progress.completed === 'number' ? progress.completed : 0;
        const completed = Math.min(total, Math.max(0, completedRaw));
        const currentItem = typeof progress.current_item === 'string' ? progress.current_item : '';
        const message =
          typeof progress.message === 'string' && progress.message.trim() !== ''
            ? progress.message
            : `请求中...（${total} 个标的）`;

        setRefreshModalProgress({
          completed,
          total,
          currentItem,
          message,
        });
        setHoldingsRefreshState({
          isLoading: true,
          progress: total > 0 ? Math.round((completed / total) * 100) : 0,
          message,
        });

        if (progress.status === 'completed' || progress.status === 'error') {
          stopPolling = true;
          if (pollTimer !== null) {
            window.clearInterval(pollTimer);
            pollTimer = null;
          }
        }
      } catch {
        pollFailureCount += 1;
        if (pollFailureCount >= 3) {
          stopPolling = true;
          if (pollTimer !== null) {
            window.clearInterval(pollTimer);
            pollTimer = null;
          }
          setRefreshModalProgress((prev) => ({
            ...prev,
            message: '进度同步暂不可用，等待后端任务完成...',
          }));
        }
      }
    };
    void pollProgress();
    pollTimer = window.setInterval(() => {
      void pollProgress();
    }, 2000);

    try {
      const resp = await onRefreshHoldings(activeCoverage, estimatedSymbolsCount, progressToken);
      stopPolling = true;
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
        pollTimer = null;
      }
      const responseRecord = resp as { message?: string; stocks_count?: number; updated_stocks?: unknown[] };
      const refreshedCount = typeof responseRecord.stocks_count === 'number'
        ? responseRecord.stocks_count
        : Array.isArray(responseRecord.updated_stocks)
          ? responseRecord.updated_stocks.length
          : 0;
      const progressTotal = estimatedSymbolsCount && estimatedSymbolsCount > 0
        ? estimatedSymbolsCount
        : refreshedCount > 0
          ? refreshedCount
          : defaultProgressTotal;
      const progressCompleted = Math.min(progressTotal, refreshedCount > 0 ? refreshedCount : progressTotal);

      // 完成状态
      setRefreshModalProgress({
        completed: progressCompleted,
        total: progressTotal,
        currentItem: '',
        message: responseRecord.message || '刷新完成',
      });
      setRefreshModalComplete(true);

      setHoldingsRefreshState({
        isLoading: false,
        progress: 100,
        message: responseRecord.message || '刷新完成',
      });

      // 延迟关闭模态框（1.5秒后自动关闭，给用户查看结果的时间）
      setTimeout(() => {
        setShowRefreshModal(false);
        // 保持本地状态显示完成信息，稍后清空
        setTimeout(() => {
          setHoldingsRefreshState({ isLoading: false, progress: 0, message: '' });
        }, 500);
      }, 1500);
    } catch (error) {
      stopPolling = true;
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
        pollTimer = null;
      }
      const errorMsg = error instanceof Error ? error.message : '刷新失败';
      console.error('Holdings refresh error:', error);

      // 错误状态
      setRefreshModalProgress({
        completed: 0,
        total: defaultProgressTotal,
        currentItem: '',
        message: errorMsg,
      });
      setRefreshModalError(true);

      setHoldingsRefreshState({
        isLoading: false,
        progress: 100,
        message: errorMsg,
        error: errorMsg,
      });

      // 延迟关闭模态框
      setTimeout(() => {
        setShowRefreshModal(false);
        setTimeout(() => {
          setHoldingsRefreshState({ isLoading: false, progress: 0, message: '' });
        }, 500);
      }, 2000);
    } finally {
      stopPolling = true;
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
      }
    }
  }, [
    holdingsRefreshState.isLoading,
    activeCoverage,
    activeOption,
    activeHoldings.length,
    onRefreshHoldings,
    etf.symbol,
  ]);

  const getCoverageTabStyle = (option: CoverageOption, isActive: boolean) => {
    const baseStyle = 'px-3 py-1.5 text-xs font-medium rounded-full border-2 transition-all cursor-pointer flex items-center gap-1.5';
    
    if (isActive) {
      switch (option.id) {
        case 'top10':
          return `${baseStyle} bg-[#fef3c7] border-[#f59e0b] text-[#b45309]`;
        case 'top15':
          return `${baseStyle} bg-[#fce7f3] border-[#ec4899] text-[#be185d]`;
        case 'top20':
          return `${baseStyle} bg-[#dbeafe] border-[#3b82f6] text-[#1e40af]`;
        case 'top30':
          return `${baseStyle} bg-[#d1fae5] border-[#10b981] text-[#065f46]`;
        case 'all':
          return `${baseStyle} bg-[#e2e8f0] border-[#64748b] text-[#334155]`;
        default:
          if (option.type === 'weight') {
            return `${baseStyle} bg-[#ede9fe] border-[#8b5cf6] text-[#6d28d9]`;
          }
          return `${baseStyle} bg-[var(--accent-blue)] text-white border-transparent`;
      }
    }
    
    return `${baseStyle} bg-[var(--bg-secondary)] text-[var(--text-secondary)] border-[var(--border-light)] hover:bg-[var(--bg-tertiary)] hover:border-[var(--border-medium)]`;
  };

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] shadow-sm overflow-hidden h-[860px] flex flex-col">
      {/* Header */}
      <div className="p-5 pb-0 shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="text-lg font-bold">{etf.symbol}</span>
              <span
                className="text-[11px] px-2 py-0.5 rounded font-medium"
                style={{
                  background: etf.type === 'sector' ? 'rgba(59, 130, 246, 0.1)' : 'rgba(139, 92, 246, 0.1)',
                  color: etf.type === 'sector' ? 'var(--accent-blue)' : 'var(--accent-purple)',
                }}
              >
                {etf.type === 'sector' ? '板块' : '行业'}
              </span>
            </div>
            <div className="text-[13px] text-[var(--text-muted)] mt-1">{etf.name}</div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold leading-none">
              {etf.score !== null ? etf.score.toFixed(1) : '--'}
            </div>
            <div className="text-[12px] text-[var(--text-muted)] mt-1">
              #{etf.rank !== null ? etf.rank : '-'} / {etf.totalCount}
            </div>
          </div>
        </div>

        {/* Dimension Scores Grid */}
        <div className="grid grid-cols-4 gap-3 mt-4 pb-4">
          {/* 相对动量 (45%) */}
          <ScoreDimensionCard
            label="相对动量"
            weight="45%"
            score={relMom.score}
            color="var(--accent-green)"
            data={relMom.data}
          />

          {/* 趋势质量 (25%) */}
          <ScoreDimensionCard
            label="趋势质量"
            weight="25%"
            score={trendQuality.score}
            color="var(--accent-blue)"
            data={trendQuality.data}
          />

          {/* 广度/参与度 (20%) */}
          <ScoreDimensionCard
            label="广度/参与度"
            weight="20%"
            score={breadth.score}
            color="var(--accent-amber)"
            data={breadth.data}
          />

          {/* 期权确认 (10%) */}
          <ScoreDimensionCard
            label="期权确认"
            weight="10%"
            score={optionsConfirm.score}
            color="var(--accent-purple)"
            data={optionsConfirm.data}
          />
        </div>
      </div>

      {/* Coverage Tabs - Enhanced Version */}
      {showCoverageSection && (
        <div className="px-5 py-5 flex-1 min-h-0 overflow-hidden flex flex-col">
          <div className="pt-0 border-t border-[var(--border-light)] flex-1 min-h-0 flex flex-col">
            {/* Coverage Tab Buttons */}
            <div className="flex items-center gap-2 flex-wrap mb-3 mt-3 shrink-0">
              {availableCoverageOptions.map((option) => {
                const isActive = option.id === activeCoverage;
                const optionStats = coverageStatsByOption.get(option.id);
                const dotColor = getCoverageAccentColor(option);
                const isComplete = Boolean(optionStats?.allComplete);
                return (
                  <button
                    key={option.id}
                    onClick={() => setActiveCoverage(option.id)}
                    className={getCoverageTabStyle(option, isActive)}
                  >
                    <span
                      className="w-2 h-2 rounded-full border"
                      style={{
                        borderColor: dotColor,
                        background: isComplete ? dotColor : 'transparent',
                      }}
                    />
                    {option.label}
                  </button>
                );
              })}
            </div>

            {/* Coverage Detail Panel */}
            <div
              className="border border-[var(--border-light)] rounded-[var(--radius-md)] overflow-hidden flex flex-col flex-1 min-h-0"
            >
              {/* Panel Header */}
              <div
                className="px-4 py-3 border-b border-[var(--border-light)] shrink-0"
                style={{ background: 'linear-gradient(135deg, #fef3c7, #fce7f3)' }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        void handleCopyCoverageSymbols();
                      }}
                      disabled={displayedHoldings.length === 0}
                      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                        displayedHoldings.length === 0
                          ? 'cursor-not-allowed border-transparent opacity-50'
                          : coverageCopyState === 'success'
                            ? 'border-emerald-200 bg-emerald-50'
                            : coverageCopyState === 'error'
                              ? 'border-rose-200 bg-rose-50'
                              : 'border-transparent hover:border-white/80'
                      }`}
                      title={displayedHoldings.length === 0 ? '当前覆盖范围暂无可复制标的' : '点击复制当前覆盖范围标的'}
                      aria-label="复制当前覆盖范围标的"
                      style={{
                        background:
                          displayedHoldings.length === 0
                            ? 'rgba(255,255,255,0.45)'
                            : coverageCopyState === 'success'
                              ? undefined
                              : coverageCopyState === 'error'
                                ? undefined
                                : 'rgba(255,255,255,0.8)',
                        color:
                          coverageCopyState === 'success'
                            ? '#059669'
                            : coverageCopyState === 'error'
                              ? '#e11d48'
                              : activeOption.type === 'top'
                                ? '#b45309'
                                : activeOption.type === 'all'
                                  ? '#334155'
                                  : '#6d28d9',
                      }}
                    >
                      {activeOption.label}
                    </button>
                    {coverageCopyState !== 'idle' && displayedHoldings.length > 0 && (
                      <span
                        className={`text-[10px] font-medium ${
                          coverageCopyState === 'success' ? 'text-emerald-600' : 'text-rose-600'
                        }`}
                      >
                        {coverageCopyState === 'success' ? '已复制' : '复制失败'}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <div className="flex items-center gap-1.5">
                      {activeCoverageSourceIndicators.map((indicator) => (
                        <span
                          key={indicator.key}
                          className="relative inline-flex h-2.5 w-2.5 items-center justify-center rounded-full border"
                          style={{
                            borderColor: indicator.isComplete || indicator.isPartial ? indicator.color : '#cbd5e1',
                            background: indicator.isComplete ? indicator.color : 'transparent',
                          }}
                          title={`${indicator.label}: ${indicator.statusLabel} (${indicator.freshCount}/${indicator.totalCount}) · ${formatUpdatedAt(indicator.updatedAt)}`}
                        >
                          {!indicator.isComplete && !indicator.isPartial && (
                            <svg
                              width="6"
                              height="6"
                              viewBox="0 0 8 8"
                              fill="none"
                              className="pointer-events-none"
                            >
                              <path d="M1 1L7 7M7 1L1 7" stroke="#94a3b8" strokeWidth="1.25" strokeLinecap="round" />
                            </svg>
                          )}
                          {indicator.isPartial && (
                            <span
                              className="pointer-events-none block h-[1.25px] w-[6px] rounded"
                              style={{ background: indicator.color }}
                            />
                          )}
                        </span>
                      ))}
                    </div>
                    <div className="flex flex-col gap-1 text-left">
                      <span className="flex items-center gap-1">
                        <span className="text-[var(--text-muted)]">
                         Completed: {activeCoverageStats.completeCount} 
                        </span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="text-[var(--text-muted)]">
                          Incomplete: {activeCoverageStats.pendingCount} 
                        </span>
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Panel Body */}
                <div className="p-4 flex-1 min-h-0 overflow-y-auto overscroll-contain">
                  <div className="flex items-center justify-between text-xs mb-3">
                    <span className="text-[var(--text-muted)]">
                      显示 {displayedHoldings.length} / {activeHoldings.length} 只股票
                    </span>
                    <span className="text-[var(--text-muted)]">
                      累计权重 <span className="font-semibold text-[var(--text-primary)]">{formatWeight(displayCoverageSum)}%</span>
                    </span>
                  </div>
                {displayedHoldings.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {displayedHoldings.map((holding) => {
                      const isHoldingComplete = hasFreshHoldingData(holding, beijingResetBoundaryMs);
                      const statusColor = isHoldingComplete
                        ? 'var(--accent-green)'
                        : holding.dataStatus === 'missing'
                          ? 'var(--accent-red)'
                          : 'var(--accent-amber)';
                      const completeness = holding.completeness || 0;
                      const dataSourceLabels: Array<{ key: CoverageSourceKey; label: string }> = [
                        { key: 'finviz', label: 'Finviz 数据' },
                        { key: 'marketchameleon', label: 'MarketChameleon 数据' },
                        { key: 'ibkr', label: '市场数据 (IBKR)' },
                        { key: 'futu', label: '期权数据 (Futu)' },
                      ];

                      // Build tooltip content
                      const tooltipLines = [];
                      tooltipLines.push(`完备度: ${Math.round(completeness)}%`);
                      if (typeof holding.deviationFrom20ma === 'number' && Number.isFinite(holding.deviationFrom20ma)) {
                        tooltipLines.push(`20DMA偏离: ${holding.deviationFrom20ma.toFixed(2)}%`);
                      }
                      if (typeof holding.aboveSma20 === 'boolean') {
                        tooltipLines.push(`20DMA状态: ${holding.aboveSma20 ? '上方' : '下方'}`);
                      }

                      dataSourceLabels.forEach(({ key, label }) => {
                        const available = getHoldingSourceAvailable(holding, key);
                        const icon = available ? '✓' : '✗';
                        const status = available ? '可用' : '缺失';
                        tooltipLines.push(`${icon} ${label}: ${status}`);
                      });

                      const tooltipText = tooltipLines.join('\n');

                      return (
                        <div
                          key={holding.ticker}
                          onClick={() => onViewStockDetail?.(holding.ticker)}
                          className={`px-2.5 py-1.5 text-xs rounded-lg border border-[var(--border-light)] bg-white flex items-center gap-2 transition-all ${
                            onViewStockDetail ? 'cursor-pointer hover:border-[var(--accent-blue)] hover:shadow-sm' : ''
                          }`}
                          title={tooltipText}
                        >
                          {/* Data freshness indicator: complete=solid, pending=hollow */}
                          <span
                            className="h-2.5 w-2.5 rounded-full border flex-shrink-0"
                            style={{
                              borderColor: statusColor,
                              background: isHoldingComplete ? statusColor : 'transparent',
                            }}
                          />

                          <span className="font-semibold text-[var(--text-primary)]">
                            {holding.ticker}
                          </span>
                          <span className="text-[var(--text-muted)]">
                            {formatWeight(holding.weight)}%
                          </span>

                          {/* Show completeness percentage for non-complete items */}
                          {holding.dataStatus === 'pending' && (
                            <span className="text-[10px] text-[var(--accent-amber)] font-medium ml-auto">
                              {Math.round(completeness)}%
                            </span>
                          )}
                          {holding.dataStatus === 'missing' && (
                            <span className="text-[10px] text-[var(--accent-red)] font-medium ml-auto">
                              {Math.round(completeness)}%
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-[var(--text-muted)] text-center py-4">
                    {activeHoldings.length === 0 && '暂无持仓数据，请先导入 Holdings。'}
                  </div>
                )}

                {/* View All Link */}
                {displayedHoldings.length > 0 && onViewStockDetail && (
                  <div className="mt-3 pt-3 border-t border-[var(--border-light)]">
                    <button
                      className="text-xs text-[var(--accent-blue)] hover:underline flex items-center gap-1"
                      onClick={() => {
                        // Navigate to stock details page
                      }}
                    >
                      查看 {activeOption.label} 完整个股详情
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7"/>
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
          {/* Data Status List */}
      <div className="pt-4">
        <button
          onClick={() => setIsTopHoldingsCollapsed(!isTopHoldingsCollapsed)}
          className="flex items-center gap-2 text-[13px] text-[var(--text-muted)] mb-2.5 hover:text-[var(--text-primary)] transition-colors cursor-pointer w-full"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/>
          </svg>
          得分前五标的
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={`ml-auto transition-transform ${isTopHoldingsCollapsed ? '-rotate-90' : ''}`}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7-7m0 0l-7 7m7-7v12" />
          </svg>
        </button>
        {!isTopHoldingsCollapsed && (
          <div className="border border-[var(--border-light)] rounded-[var(--radius-md)] overflow-hidden">
            {topScoreHoldings.length > 0 ? (
              topScoreHoldings.map((holding) => {
                const isHoldingComplete = hasFreshHoldingData(holding, beijingResetBoundaryMs);
                const statusColor = isHoldingComplete
                  ? 'var(--accent-green)'
                  : holding.dataStatus === 'missing'
                    ? 'var(--accent-red)'
                    : 'var(--accent-amber)';
                return (
                  <div
                    key={holding.ticker}
                    className="flex items-center justify-between text-xs px-3 py-2.5 border-b border-[var(--border-light)] last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 rounded-full border flex-shrink-0"
                        style={{
                          borderColor: statusColor,
                          background: isHoldingComplete ? statusColor : 'transparent',
                        }}
                      />
                      <span className="text-[var(--text-primary)] font-semibold min-w-[60px]">{holding.ticker}</span>
                      <span className="text-[var(--text-muted)]">
                        {formatWeight(holding.weight)}%
                      </span>
                    </div>
                    <span className="text-sm font-bold text-[var(--accent-blue)]">
                      {typeof holding.score === 'number' ? holding.score.toFixed(1) : '--'}
                    </span>
                    <span className="text-[var(--text-muted)]">
                      {formatUpdatedAt(holding.updatedAt)}
                    </span>
                  </div>
                );
              })
            ) : (
              <div className="text-xs text-[var(--text-muted)] px-3 py-3 text-center">
                暂无得分数据，请先刷新或导入数据。
              </div>
            )}
          </div>
        )}
      </div>
        </div>
      )}
      {/* Action Buttons - Footer */}
      <div className="flex gap-3 px-5 py-4 border-t border-[var(--border-light)] bg-[var(--bg-secondary)] mt-auto shrink-0">
          <button
            onClick={() => handleRefreshHoldings()}
            disabled={holdingsRefreshState.isLoading}
            className={`flex-1 py-2.5 text-xs font-medium rounded-[var(--radius-md)] border transition-colors flex items-center justify-center gap-1.5 ${
              holdingsRefreshState.isLoading ? 'opacity-60 cursor-not-allowed' : ''
            }`}
            style={{
              background: 'rgba(59, 130, 246, 0.08)',
              borderColor: 'rgba(59, 130, 246, 0.3)',
              color: 'var(--accent-blue)',
            }}
          >
            {holdingsRefreshState.isLoading ? (
              <>
                <svg className="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Refreshing...
              </>
            ) : (
              `Refresh ${activeOption.label} Holdings`
            )}
          </button>
        <button
          onClick={() => onImportHoldings?.(activeCoverage)}
          className="flex-1 py-2.5 text-xs font-medium rounded-[var(--radius-md)] cursor-pointer text-center border transition-colors flex items-center justify-center gap-1.5"
          style={{
            background: 'rgba(245, 158, 11, 0.1)',
            borderColor: 'rgba(245, 158, 11, 0.3)',
            color: 'var(--accent-amber)',
          }}
        >
          Export Holdings
        </button>
      </div>

      {/* Unified Refresh Progress Modal */}
      <RefreshProgressModal
        isOpen={showRefreshModal}
        title={refreshModalTitle}
        currentItem={refreshModalProgress.currentItem}
        message={refreshModalProgress.message}
        completed={refreshModalProgress.completed}
        total={refreshModalProgress.total}
        isError={refreshModalError}
        isComplete={refreshModalComplete}
      />
    </div>
  );
}
