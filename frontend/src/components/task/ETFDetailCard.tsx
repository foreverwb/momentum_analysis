import React, { useEffect, useMemo, useState, useCallback } from 'react';

interface DataStatus {
  source: 'Finviz' | 'MarketChameleon' | '市场数据' | '期权数据' | 'IBKR' | 'Futu';
  status: 'complete' | 'pending' | 'missing' | 'loading';
  updatedAt: string | null;
  count?: number;
}

interface HoldingSummary {
  ticker: string;
  weight: number;
  dataStatus?: 'complete' | 'pending' | 'missing';
}

interface RefreshProgress {
  stage: 'idle' | 'connecting' | 'fetching_price' | 'calculating_relmom' | 'calculating_trend' | 'fetching_iv' | 'saving' | 'done' | 'error';
  message: string;
  progress: number;
}

interface RefreshResult {
  status: string;
  symbol: string;
  message: string;
  score?: number;
  rank?: number;
  completeness?: number;
  thresholds_pass?: boolean;
  breakdown?: {
    rel_mom?: { score: number; data?: Record<string, unknown> };
    trend_quality?: { score: number; data?: Record<string, unknown> };
    breadth?: { score: number; data?: Record<string, unknown> };
    options_confirm?: { score: number; data?: Record<string, unknown> };
  };
  data_sources?: Record<string, boolean>;
  warnings?: string[];
}

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
  onRefreshETF: () => Promise<RefreshResult | void>;
  onRefreshHoldings: () => void;
  onImportHoldings: () => void;
  onViewStockDetail?: (ticker: string) => void;
}

type CoverageOption = {
  id: 'top10' | 'top15' | 'top20' | 'top30' | 'weight60' | 'weight65' | 'weight70' | 'weight75' | 'weight80' | 'weight85';
  label: string;
  type: 'top' | 'weight';
  value: number;
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
];

const statusConfig = {
  complete: {
    label: '完整',
    bgColor: 'rgba(34, 197, 94, 0.1)',
    textColor: 'var(--accent-green)',
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
    ),
  },
  pending: {
    label: '待更新',
    bgColor: 'rgba(245, 158, 11, 0.1)',
    textColor: 'var(--accent-amber)',
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
    ),
  },
  missing: {
    label: '缺失',
    bgColor: 'rgba(239, 68, 68, 0.1)',
    textColor: 'var(--accent-red)',
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
      </svg>
    ),
  },
  loading: {
    label: '加载中',
    bgColor: 'rgba(59, 130, 246, 0.1)',
    textColor: 'var(--accent-blue)',
    icon: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
      </svg>
    ),
  },
};

const holdingStatusConfig = {
  complete: { color: 'var(--accent-green)' },
  pending: { color: 'var(--accent-amber)' },
  missing: { color: 'var(--text-muted)' },
};

const refreshStageMessages: Record<RefreshProgress['stage'], string> = {
  idle: '',
  connecting: '正在连接 IBKR...',
  fetching_price: '正在获取价格数据...',
  calculating_relmom: '正在计算相对动量 (RelMom)...',
  calculating_trend: '正在计算趋势质量...',
  fetching_iv: '正在获取 IV 期限结构...',
  saving: '正在保存数据...',
  done: '刷新完成',
  error: '刷新失败',
};

const formatWeight = (value: number): string => {
  if (value >= 10) {
    return value.toFixed(1);
  }
  return value.toFixed(2);
};

const getCoverageHoldings = (holdings: HoldingSummary[], option: CoverageOption): HoldingSummary[] => {
  if (!holdings.length) {
    return [];
  }
  if (option.type === 'top') {
    return holdings.slice(0, option.value);
  }
  let sum = 0;
  const picked: HoldingSummary[] = [];
  for (const holding of holdings) {
    picked.push(holding);
    sum += holding.weight;
    if (sum >= option.value) {
      break;
    }
  }
  return picked;
};

export function ETFDetailCard({
  etf,
  coverageRanges = [],
  onRefreshETF,
  onRefreshHoldings,
  onImportHoldings,
  onViewStockDetail,
}: ETFDetailCardProps) {
  const [activeCoverage, setActiveCoverage] = useState<CoverageOption['id']>('top10');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshProgress, setRefreshProgress] = useState<RefreshProgress>({
    stage: 'idle',
    message: '',
    progress: 0,
  });
  const [lastRefreshResult, setLastRefreshResult] = useState<RefreshResult | null>(null);
  const [showRefreshDetails, setShowRefreshDetails] = useState(false);

  const sortedHoldings = useMemo(() => {
    const holdings = etf.holdings || [];
    return [...holdings].sort((a, b) => b.weight - a.weight);
  }, [etf.holdings]);

  // 根据传入的 coverageRanges 过滤可用选项
  const availableCoverageOptions = useMemo(() => {
    if (!coverageRanges.length) {
      return [];
    }
    const available = new Set(coverageRanges);
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

  const showCoverageSection = availableCoverageOptions.length >= 1;
  const activeOption = availableCoverageOptions.find((option) => option.id === activeCoverage) || availableCoverageOptions[0] || COVERAGE_OPTIONS[0];
  const activeHoldings = getCoverageHoldings(sortedHoldings, activeOption);
  const coverageSum = activeHoldings.reduce((sum, item) => sum + item.weight, 0);

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

  // 模拟刷新进度
  const simulateProgress = useCallback(async () => {
    const stages: Array<{ stage: RefreshProgress['stage']; duration: number; progress: number }> = [
      { stage: 'connecting', duration: 500, progress: 10 },
      { stage: 'fetching_price', duration: 2000, progress: 30 },
      { stage: 'calculating_relmom', duration: 1500, progress: 50 },
      { stage: 'calculating_trend', duration: 1000, progress: 70 },
      { stage: 'fetching_iv', duration: 1500, progress: 85 },
      { stage: 'saving', duration: 500, progress: 95 },
    ];

    for (const { stage, duration, progress } of stages) {
      setRefreshProgress({
        stage,
        message: refreshStageMessages[stage],
        progress,
      });
      await new Promise((resolve) => setTimeout(resolve, duration));
    }
  }, []);

  const handleRefreshETF = useCallback(async () => {
    if (isRefreshing) return;

    setIsRefreshing(true);
    setShowRefreshDetails(true);
    setLastRefreshResult(null);
    setRefreshProgress({ stage: 'connecting', message: refreshStageMessages['connecting'], progress: 5 });

    try {
      // 并行运行进度模拟和实际API调用
      const [, result] = await Promise.all([
        simulateProgress(),
        onRefreshETF(),
      ]);

      if (result) {
        setLastRefreshResult(result);
        if (result.status === 'success') {
          setRefreshProgress({ stage: 'done', message: refreshStageMessages['done'], progress: 100 });
        } else {
          setRefreshProgress({ 
            stage: 'error', 
            message: result.message || refreshStageMessages['error'], 
            progress: 100 
          });
        }
      } else {
        setRefreshProgress({ stage: 'done', message: refreshStageMessages['done'], progress: 100 });
      }
    } catch (error) {
      setRefreshProgress({ 
        stage: 'error', 
        message: error instanceof Error ? error.message : '刷新失败', 
        progress: 100 
      });
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, onRefreshETF, simulateProgress]);

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
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-5 pb-0">
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
          <div className="flex flex-col items-end gap-3">
            <button
              onClick={handleRefreshETF}
              disabled={isRefreshing}
              className={`px-3.5 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] text-white transition-all flex items-center gap-1.5 ${
                isRefreshing ? 'opacity-70 cursor-not-allowed' : 'hover:opacity-90'
              }`}
              style={{ background: 'var(--accent-green)' }}
            >
              <svg 
                width="12" 
                height="12" 
                viewBox="0 0 24 24" 
                fill="none" 
                stroke="currentColor" 
                strokeWidth="2"
                className={isRefreshing ? 'animate-spin' : ''}
              >
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 16h5v5" />
              </svg>
              {isRefreshing ? '刷新中...' : '刷新 ETF 数据'}
            </button>
            <div className="text-right">
              <div className="text-2xl font-bold leading-none">
                {etf.score !== null ? etf.score.toFixed(1) : '--'}
              </div>
              <div className="text-[12px] text-[var(--text-muted)] mt-1">
                #{etf.rank !== null ? etf.rank : '-'} / {etf.totalCount}
              </div>
            </div>
          </div>
        </div>

        {/* Metrics */}
        <div className="flex items-center justify-between mt-4 pb-4 border-b border-[var(--border-light)]">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className="text-xs text-[var(--text-muted)]">Δ3D</span>
              <span className={`text-sm font-semibold flex items-center gap-1 ${delta3d.className}`}>
                {delta3d.text !== '--' && etf.delta3d !== null && etf.delta3d > 0 && (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                  </svg>
                )}
                {delta3d.text}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-[var(--text-muted)]">Δ5D</span>
              <span className={`text-sm font-semibold flex items-center gap-1 ${delta5d.className}`}>
                {delta5d.text !== '--' && etf.delta5d !== null && etf.delta5d > 0 && (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                  </svg>
                )}
                {delta5d.text}
              </span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-[var(--text-muted)]">数据完备度</div>
            <div
              className="text-lg font-bold"
              style={{
                color: etf.completeness >= 80
                  ? 'var(--accent-green)'
                  : etf.completeness >= 50
                  ? 'var(--accent-amber)'
                  : 'var(--accent-red)',
              }}
            >
              {etf.completeness.toFixed(0)}%
            </div>
          </div>
        </div>
      </div>

      {/* Refresh Progress Section */}
      {showRefreshDetails && (
        <div className="mx-5 mt-4 mb-0">
          <div 
            className="border rounded-[var(--radius-md)] overflow-hidden transition-all"
            style={{ 
              borderColor: refreshProgress.stage === 'error' ? 'rgba(239, 68, 68, 0.3)' 
                : refreshProgress.stage === 'done' ? 'rgba(34, 197, 94, 0.3)' 
                : 'rgba(59, 130, 246, 0.3)',
              background: refreshProgress.stage === 'error' ? 'rgba(239, 68, 68, 0.05)' 
                : refreshProgress.stage === 'done' ? 'rgba(34, 197, 94, 0.05)' 
                : 'rgba(59, 130, 246, 0.05)',
            }}
          >
            {/* Progress Header */}
            <div className="flex items-center justify-between px-3 py-2">
              <div className="flex items-center gap-2">
                {refreshProgress.stage === 'done' ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-green)" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                  </svg>
                ) : refreshProgress.stage === 'error' ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-red)" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" strokeWidth="2" className="animate-spin">
                    <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                    <path d="M3 3v5h5" />
                  </svg>
                )}
                <span className="text-xs font-medium" style={{ 
                  color: refreshProgress.stage === 'error' ? 'var(--accent-red)' 
                    : refreshProgress.stage === 'done' ? 'var(--accent-green)' 
                    : 'var(--accent-blue)' 
                }}>
                  {refreshProgress.message}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-[var(--text-muted)]">{refreshProgress.progress}%</span>
                {(refreshProgress.stage === 'done' || refreshProgress.stage === 'error') && (
                  <button 
                    onClick={() => setShowRefreshDetails(false)}
                    className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                  </button>
                )}
              </div>
            </div>
            
            {/* Progress Bar */}
            <div className="h-1 bg-[var(--bg-secondary)]">
              <div 
                className="h-full transition-all duration-300"
                style={{ 
                  width: `${refreshProgress.progress}%`,
                  background: refreshProgress.stage === 'error' ? 'var(--accent-red)' 
                    : refreshProgress.stage === 'done' ? 'var(--accent-green)' 
                    : 'var(--accent-blue)',
                }}
              />
            </div>

            {/* Refresh Result Details */}
            {lastRefreshResult && (refreshProgress.stage === 'done' || refreshProgress.stage === 'error') && (
              <div className="px-3 py-2 border-t border-[var(--border-light)] text-xs">
                {lastRefreshResult.data_sources && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    {Object.entries(lastRefreshResult.data_sources).map(([source, available]) => (
                      <span 
                        key={source}
                        className="px-2 py-0.5 rounded text-[10px] font-medium"
                        style={{
                          background: available ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                          color: available ? 'var(--accent-green)' : 'var(--accent-red)',
                        }}
                      >
                        {source.replace('_', ' ').replace('ibkr', 'IBKR').replace('futu', 'Futu')}
                        {available ? ' ✓' : ' ✗'}
                      </span>
                    ))}
                  </div>
                )}
                {lastRefreshResult.warnings && lastRefreshResult.warnings.length > 0 && (
                  <div className="text-[var(--accent-amber)] text-[10px]">
                    ⚠️ {lastRefreshResult.warnings.join(', ')}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Data Status List */}
      <div className="p-5 pt-4">
        <div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)] mb-2.5">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/>
          </svg>
          数据状态
        </div>
        <div className="border border-[var(--border-light)] rounded-[var(--radius-md)] overflow-hidden">
          {etf.dataStatus.map((status, index) => {
            const config = statusConfig[status.status];
            return (
              <div
                key={index}
                className="flex items-center justify-between text-xs px-3 py-2.5 border-b border-[var(--border-light)] last:border-0"
              >
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: config.textColor }} />
                  <span className="text-[var(--text-primary)] min-w-[110px]">{status.source}</span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded font-medium inline-flex items-center gap-1"
                    style={{ background: config.bgColor, color: config.textColor }}
                  >
                    {config.icon}
                    {config.label}
                  </span>
                </div>
                <span className="text-[var(--text-muted)]">
                  {status.updatedAt ? status.updatedAt : '--'}
                  {status.count !== undefined && ` · ${status.count}条`}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Coverage Tabs - Enhanced Version */}
      {showCoverageSection && (
        <div className="px-5 pb-5">
          <div className="pt-4 border-t border-[var(--border-light)]">
            <div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)] mb-3">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
              </svg>
              已导入的覆盖范围（点击切换查看详情）
            </div>
            
            {/* Coverage Tab Buttons */}
            <div className="flex items-center gap-2 flex-wrap mb-3">
              {availableCoverageOptions.map((option) => {
                const isActive = option.id === activeCoverage;
                return (
                  <button
                    key={option.id}
                    onClick={() => setActiveCoverage(option.id)}
                    className={getCoverageTabStyle(option, isActive)}
                  >
                    <span 
                      className="w-2 h-2 rounded-full"
                      style={{ background: 'var(--accent-green)' }}
                    />
                    {option.label}
                  </button>
                );
              })}
            </div>

            {/* Coverage Detail Panel */}
            <div
              className="border border-[var(--border-light)] rounded-[var(--radius-md)] overflow-hidden"
            >
              {/* Panel Header */}
              <div 
                className="px-4 py-3 border-b border-[var(--border-light)]"
                style={{ background: 'linear-gradient(135deg, #fef3c7, #fce7f3)' }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span 
                      className="px-2.5 py-1 rounded-full text-[11px] font-semibold"
                      style={{ 
                        background: 'rgba(255,255,255,0.8)',
                        color: activeOption.id.startsWith('top') ? '#b45309' : '#6d28d9',
                      }}
                    >
                      {activeOption.label}
                    </span>
                    <span className="text-sm font-medium text-[var(--text-primary)]">
                      持仓股数据状态
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                      <span className="text-[var(--text-muted)]">
                        {activeHoldings.filter(h => h.dataStatus !== 'missing').length} 完整
                      </span>
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-amber)]" />
                      <span className="text-[var(--text-muted)]">
                        {activeHoldings.filter(h => h.dataStatus === 'pending').length} 待更新
                      </span>
                    </span>
                  </div>
                </div>
              </div>

              {/* Panel Body */}
              <div className="p-4">
                <div className="flex items-center justify-between text-xs mb-3">
                  <span className="text-[var(--text-muted)]">
                    显示 {activeHoldings.length} / {sortedHoldings.length} 只股票
                  </span>
                  <span className="text-[var(--text-muted)]">
                    累计权重 <span className="font-semibold text-[var(--text-primary)]">{formatWeight(coverageSum)}%</span>
                  </span>
                </div>
                
                {activeHoldings.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {activeHoldings.map((holding) => {
                      const statusColor = holdingStatusConfig[holding.dataStatus || 'complete'].color;
                      return (
                        <div
                          key={holding.ticker}
                          onClick={() => onViewStockDetail?.(holding.ticker)}
                          className={`px-2.5 py-1.5 text-xs rounded-lg border border-[var(--border-light)] bg-white flex items-center gap-2 transition-all ${
                            onViewStockDetail ? 'cursor-pointer hover:border-[var(--accent-blue)] hover:shadow-sm' : ''
                          }`}
                        >
                          <span 
                            className="w-1.5 h-1.5 rounded-full" 
                            style={{ background: statusColor }}
                          />
                          <span className="font-semibold text-[var(--text-primary)]">{holding.ticker}</span>
                          <span className="text-[var(--text-muted)]">{formatWeight(holding.weight)}%</span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-[var(--text-muted)] text-center py-4">
                    暂无持仓数据，请先导入 Holdings。
                  </div>
                )}

                {/* View All Link */}
                {activeHoldings.length > 0 && onViewStockDetail && (
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
        </div>
      )}

      {/* Action Buttons - Footer */}
      <div className="flex gap-3 px-5 py-4 border-t border-[var(--border-light)] bg-[var(--bg-secondary)]">
        <button
          onClick={handleRefreshETF}
          className="flex-1 py-2.5 text-xs font-medium rounded-[var(--radius-md)] cursor-pointer text-center bg-[var(--bg-primary)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:border-[var(--border-medium)] transition-colors flex items-center justify-center gap-1.5"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
            <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
            <path d="M16 16h5v5" />
          </svg>
          刷新数据
        </button>
        <button
          onClick={onImportHoldings}
          className="flex-1 py-2.5 text-xs font-medium rounded-[var(--radius-md)] cursor-pointer text-center border transition-colors flex items-center justify-center gap-1.5"
          style={{
            background: 'rgba(245, 158, 11, 0.1)',
            borderColor: 'rgba(245, 158, 11, 0.3)',
            color: 'var(--accent-amber)',
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
          </svg>
          导入 Holdings 数据
        </button>
        {onViewStockDetail && (
          <button
            onClick={() => onViewStockDetail(etf.symbol)}
            className="py-2.5 px-4 text-xs font-medium rounded-[var(--radius-md)] cursor-pointer text-center transition-colors flex items-center justify-center gap-1.5 text-[var(--accent-blue)] hover:bg-[var(--bg-tertiary)]"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
            </svg>
            查看个股详情
          </button>
        )}
      </div>
    </div>
  );
}
