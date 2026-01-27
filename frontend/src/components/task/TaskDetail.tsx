import React, { useState, useEffect, useMemo } from 'react';
import { TrendChart, type TrendDataPoint } from '../chart';
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
  holdings: Array<Holding & { dataStatus?: 'complete' | 'pending' | 'missing' }>;
  dataStatus: Array<{
    source: 'Finviz' | 'MarketChameleon' | '市场数据' | '期权数据' | 'IBKR' | 'Futu';
    status: 'complete' | 'pending' | 'missing' | 'loading';
    updatedAt: string | null;
    count?: number;
  }>;
  coverageRanges: string[];
}

export function TaskDetail({ task, onBack }: TaskDetailProps) {
  const [trendPeriod, setTrendPeriod] = useState<'3d' | '5d'>('5d');
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
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([]);

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

  const loadETFData = async (symbols: string[]) => {
    setIsLoading(true);
    setError(null);
    
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
        return {
          symbol,
          name: getETFName(symbol),
          type: getETFType(symbol),
          score: null,
          rank: null,
          totalCount: symbols.length,
          delta3d: null,
          delta5d: null,
          completeness: 0,
          holdings: [],
          dataStatus: [
            { source: 'Finviz' as const, status: 'missing' as const, updatedAt: null },
            { source: 'MarketChameleon' as const, status: 'missing' as const, updatedAt: null },
            { source: '市场数据' as const, status: 'missing' as const, updatedAt: null },
            { source: '期权数据' as const, status: 'missing' as const, updatedAt: null },
          ],
          coverageRanges: [],
        };
      });
      
      const results = await Promise.all(etfDataPromises);
      setEtfDetails(results);
      setSelectedETF((prev) => prev || results[0]?.symbol || '');
    } catch (e) {
      setError(e instanceof Error ? e : new Error('加载数据失败'));
    } finally {
      setIsLoading(false);
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
      setTrendData(generateEmptyTrendData(trendPeriod === '3d' ? 3 : 5));
      if (!task.id) {
        setIsLoading(false);
      }
      return;
    }
    loadETFData(resolvedEtfs);
  }, [resolvedEtfsKey, task.id]);

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

  useEffect(() => {
    setTrendData(generateEmptyTrendData(trendPeriod === '3d' ? 3 : 5));
  }, [trendPeriod]);

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

  // 生成空趋势数据
  const generateEmptyTrendData = (days: number): TrendDataPoint[] => {
    const data: TrendDataPoint[] = [];
    const today = new Date();
    
    for (let i = days - 1; i >= 0; i--) {
      const date = new Date(today);
      date.setDate(date.getDate() - i);
      
      data.push({
        date: `${date.getMonth() + 1}/${date.getDate()}`,
        baseline: 0,
        sector: 0,
        industry: 0,
        sectorVsBaseline: 0,
        industryVsSector: 0,
      });
    }
    
    return data;
  };

  const taskTypeLabel = {
    rotation: '板块轮动',
    drilldown: '板块下钻',
    momentum: '动能追踪',
  };

  const etfSymbols = resolvedEtfs;

  const handleRefreshAll = async () => {
    setIsRefreshingAll(true);
    setShowRefreshModal(true);
    setRefreshComplete(false);
    setRefreshError(false);
    setRefreshProgress({ completed: 0, total: etfSymbols.length, currentETF: '', message: '已发送刷新请求...' });

    try {
      const resp = await api.refreshTaskAllETFs(task.id);
      // 把后端返回的刷新结果按 symbol 存起来，传给卡片展示细分得分
      const mappedResults = (resp.results || []).reduce<Record<string, RefreshResult>>((acc, item) => {
        if (item?.symbol) {
          acc[item.symbol] = item;
        }
        return acc;
      }, {});
      setLatestRefreshResults((prev) => ({ ...prev, ...mappedResults }));

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

  const handleRefreshHoldings = async (symbol: string, coverageId: string) => {
    try {
      // 解析 coverageId (如 "top10", "weight70")
      const isTop = coverageId.startsWith('top');
      const coverageType = isTop ? 'top' : 'weight';
      const valueStr = coverageId.replace('top', '').replace('weight', '');
      const coverageValue = parseInt(valueStr, 10);

      if (isNaN(coverageValue)) {
        console.error('无效的覆盖范围值');
        throw new Error('无效的覆盖范围值');
      }

      console.log(`开始刷新 ${symbol} 的 ${coverageId} Holdings 数据...`);

      // 调用API刷新Holdings数据
      // 后端应该支持多数据源的并发获取：Finviz, MarketChameleon, 市场数据(IBKR), 期权数据(Futu)等
      const response = await api.refreshHoldingsByCoverage(symbol, coverageType, coverageValue);

      console.log('Holdings refresh response:', response);

      // 延迟后重新加载数据，以显示更新结果
      setTimeout(() => {
        if (etfSymbols.length) {
          loadETFData(etfSymbols);
        }
      }, 1000);

      return response;
    } catch (e) {
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
              <span>创建: {task.createdAt}</span>
            </div>
          </div>
        </div>
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
        <TrendChart
          data={trendData}
          period={trendPeriod}
          onPeriodChange={setTrendPeriod}
          baselineName={task.baseIndex}
          sectorName={task.sector || etfSymbols[0]}
          industryName={etfSymbols[etfSymbols.length - 1]}
        />
      </div>

      {/* Trend Data Table */}
      {trendData.length > 0 && trendData.some(d => d.baseline > 0) && (
        <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5 mb-6">
          <h3 className="text-base font-semibold mb-4">趋势数据</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-light)]">
                  <th className="text-left py-3 px-4 font-medium text-[var(--text-muted)]">日期</th>
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">{task.baseIndex}</th>
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">{task.sector || etfSymbols[0]}</th>
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">{etfSymbols[etfSymbols.length - 1]}</th>
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">板块 vs 基准</th>
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">行业 vs 板块</th>
                </tr>
              </thead>
              <tbody>
                {trendData.map((row, index) => (
                  <tr key={index} className="border-b border-[var(--border-light)] last:border-0">
                    <td className="py-3 px-4">{row.date}</td>
                    <td className="text-right py-3 px-4">{row.baseline.toFixed(2)}</td>
                    <td className="text-right py-3 px-4">{row.sector.toFixed(2)}</td>
                    <td className="text-right py-3 px-4">{row.industry.toFixed(2)}</td>
                    <td className={`text-right py-3 px-4 font-medium ${row.sectorVsBaseline >= 0 ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                      {row.sectorVsBaseline >= 0 ? '+' : ''}{row.sectorVsBaseline.toFixed(2)}%
                    </td>
                    <td className={`text-right py-3 px-4 font-medium ${row.industryVsSector >= 0 ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                      {row.industryVsSector >= 0 ? '+' : ''}{row.industryVsSector.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
                onRefreshHoldings={(coverageId: string) => handleRefreshHoldings(etf.symbol, coverageId)}
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
        onClose={() => setHoldingsModalOpen(false)}
        etfSymbol={selectedETF}
        onImport={async (data) => {
          console.log('Import holdings:', selectedETF, data);
          if (selectedETF && data.jsonData) {
            try {
              const parsedData = JSON.parse(data.jsonData);
              
              // 调用后端 API 导入数据
              if (data.source === 'finviz') {
                await api.importFinvizData(selectedETF, data.coverage, parsedData);
              } else {
                await api.importMCData(parsedData);
              }
              
              // 更新本地状态（作为备份）
              setCoverageRangesByETF((prev) => {
                const existing = new Set(prev[selectedETF] || []);
                existing.add(data.coverage);
                return { ...prev, [selectedETF]: Array.from(existing) };
              });
              
              // 刷新数据
              if (etfSymbols.length) {
                loadETFData(etfSymbols);
              }
            } catch (e) {
              console.error('Import failed:', e);
              alert('导入失败，请检查数据格式');
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
          if (etfSymbols.length) {
            loadETFData(etfSymbols);
          }
        }}
      />
    </div>
  );
}
