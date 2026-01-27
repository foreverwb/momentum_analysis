import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { RefreshProgressModal } from '../modal';
import type { RefreshResult } from '../../types';

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
  completeness?: number;  // 0-100 percentage
  score?: number; // 个股得分
  dataSources?: Record<string, boolean>;  // { finviz, market_chameleon, market_data, options_data }
  updatedAt?: string;  // timestamp
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
  onRefreshHoldings: (coverageId: string) => Promise<unknown>;
  onImportHoldings?: (coverageId?: string) => void;
  onViewStockDetail?: (ticker: string) => void;
  refreshResult?: RefreshResult;
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

// 获取北京时间当天 8 点的时间戳
const getBeiјingToday8AM = (): number => {
  const now = new Date();
  const utcTime = now.getTime();
  const beijingTime = new Date(utcTime + 8 * 60 * 60 * 1000);

  const year = beijingTime.getUTCFullYear();
  const month = beijingTime.getUTCMonth();
  const date = beijingTime.getUTCDate();

  return new Date(year, month, date, 8, 0, 0).getTime();
};

// 检查当前覆盖范围下的所有 holdings 是否都有在北京时间 8 点以后更新的 MarketChameleon 和 Finviz 数据
const areHoldingsDataUpdatedAfter8AM = (holdings: HoldingSummary[]): boolean => {
  if (!holdings.length) {
    return false;
  }

  const todayBeijing8AM = getBeiјingToday8AM();

  return holdings.every(holding => {
    const dataSources = holding.dataSources || {};
    const hasFinviz = dataSources.finviz === true;
    const hasMarketChameleon = dataSources.market_chameleon === true;

    if (!hasFinviz || !hasMarketChameleon) {
      return false;
    }

    // 检查 updatedAt 是否晚于北京时间 8 点
    if (!holding.updatedAt) {
      return false;
    }

    const updatedAtTime = new Date(holding.updatedAt).getTime();
    return updatedAtTime >= todayBeijing8AM;
  });
};

export function ETFDetailCard({
  etf,
  coverageRanges = [],
  onRefreshHoldings,
  onImportHoldings,
  onViewStockDetail,
  refreshResult,
}: ETFDetailCardProps) {
  const [activeCoverage, setActiveCoverage] = useState<CoverageOption['id']>('top10');
  const lastRefreshResult = refreshResult || null;

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

  const sortedHoldings = useMemo(() => {
    const holdings = etf.holdings || [];
    return [...holdings].sort((a, b) => b.weight - a.weight);
  }, [etf.holdings]);

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

  const handleRefreshHoldings = useCallback(async () => {
    // 防止重复点击
    if (holdingsRefreshState.isLoading) return;

    // 立即更新UI状态
    setHoldingsRefreshState({
      isLoading: true,
      progress: 0,
      message: '已发送请求，等待后端返回...',
    });

    // 立即显示模态框 - 这是关键
    setShowRefreshModal(true);
    setRefreshModalTitle(`正在刷新 ${etf.symbol} ${activeOption.label} Holdings`);
    setRefreshModalProgress({
      completed: 0,
      total: 1,
      currentItem: '',
      message: '请求中...',
    });
    setRefreshModalError(false);
    setRefreshModalComplete(false);

    try {
      const resp = await onRefreshHoldings(activeCoverage);

      // 完成状态
      setRefreshModalProgress({
        completed: 1,
        total: 1,
        currentItem: '',
        message: (resp as { message?: string })?.message || '刷新完成',
      });
      setRefreshModalComplete(true);

      setHoldingsRefreshState({
        isLoading: false,
        progress: 100,
        message: (resp as { message?: string })?.message || '刷新完成',
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
      const errorMsg = error instanceof Error ? error.message : '刷新失败';
      console.error('Holdings refresh error:', error);

      // 错误状态
      setRefreshModalProgress({
        completed: 0,
        total: 1,
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
    }
  }, [holdingsRefreshState.isLoading, activeCoverage, activeOption, onRefreshHoldings, etf.symbol]);

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
            score={lastRefreshResult?.breakdown?.rel_mom?.score}
            color="var(--accent-green)"
            data={lastRefreshResult?.breakdown?.rel_mom?.data}
          />

          {/* 趋势质量 (25%) */}
          <ScoreDimensionCard
            label="趋势质量"
            weight="25%"
            score={lastRefreshResult?.breakdown?.trend_quality?.score}
            color="var(--accent-blue)"
            data={lastRefreshResult?.breakdown?.trend_quality?.data}
          />

          {/* 广度/参与度 (20%) */}
          <ScoreDimensionCard
            label="广度/参与度"
            weight="20%"
            score={lastRefreshResult?.breakdown?.breadth?.score}
            color="var(--accent-amber)"
            data={lastRefreshResult?.breakdown?.breadth?.data}
          />

          {/* 期权确认 (10%) */}
          <ScoreDimensionCard
            label="期权确认"
            weight="10%"
            score={lastRefreshResult?.breakdown?.options_confirm?.score}
            color="var(--accent-purple)"
            data={lastRefreshResult?.breakdown?.options_confirm?.data}
          />
        </div>
      </div>

      {/* Coverage Tabs - Enhanced Version */}
      {showCoverageSection && (
        <div className="px-5 py-5">
          <div className="pt-0 border-t border-[var(--border-light)]">
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
                      const completeness = holding.completeness || 0;
                      const dataSources = holding.dataSources || {};

                      // Data source labels in Chinese
                      const dataSourceLabels: Record<string, string> = {
                        finviz: 'Finviz 数据',
                        market_chameleon: 'MarketChameleon 数据',
                        market_data: '市场数据 (IBKR)',
                        options_data: '期权数据 (Futu)',
                      };

                      // Build tooltip content
                      const tooltipLines = [];
                      tooltipLines.push(`完备度: ${Math.round(completeness)}%`);

                      Object.entries(dataSourceLabels).forEach(([key, label]) => {
                        const available = dataSources[key];
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
                          {/* Status indicator with completeness ring */}
                          <div className="relative w-3 h-3 flex-shrink-0">
                            <div
                              className="w-1.5 h-1.5 rounded-full absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2"
                              style={{ background: statusColor }}
                            />
                            {/* Completeness ring */}
                            {completeness < 100 && (
                              <svg className="absolute inset-0" viewBox="0 0 12 12">
                                <circle
                                  cx="6"
                                  cy="6"
                                  r="5"
                                  fill="none"
                                  stroke={
                                    completeness >= 80
                                      ? 'var(--accent-green)'
                                      : completeness >= 50
                                      ? 'var(--accent-amber)'
                                      : 'var(--accent-red)'
                                  }
                                  strokeWidth="1"
                                  opacity="0.3"
                                />
                              </svg>
                            )}
                          </div>

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
              topScoreHoldings.map((holding) => (
                <div
                  key={holding.ticker}
                  className="flex items-center justify-between text-xs px-3 py-2.5 border-b border-[var(--border-light)] last:border-0"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--text-primary)] font-semibold min-w-[60px]">{holding.ticker}</span>
                    <span className="text-[var(--text-muted)]">
                      权重 {formatWeight(holding.weight)}%
                    </span>
                  </div>
                  <span className="text-sm font-bold text-[var(--accent-blue)]">
                    {typeof holding.score === 'number' ? holding.score.toFixed(1) : '--'}
                  </span>
                </div>
              ))
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
      <div className="flex gap-3 px-5 py-4 border-t border-[var(--border-light)] bg-[var(--bg-secondary)]">
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
