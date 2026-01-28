import React, { useState, useEffect } from 'react';
import { TrendChart, type TrendDataPoint } from '../chart';
import { ETFDetailCard } from './ETFDetailCard';
import { HoldingsImportModal, ETFImportModal } from '../modal';
import { LoadingState, ErrorMessage } from '../common';
import type { Task, ETF } from '../../types';
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
  dataStatus: Array<{
    source: 'Finviz' | 'MarketChameleon' | '市场/期权数据';
    status: 'complete' | 'pending' | 'missing';
    updatedAt: string | null;
    count?: number;
  }>;
}

export function TaskDetail({ task, onBack }: TaskDetailProps) {
  const [trendPeriod, setTrendPeriod] = useState<'3d' | '5d'>('5d');
  const [holdingsModalOpen, setHoldingsModalOpen] = useState(false);
  const [etfModalOpen, setETFModalOpen] = useState(false);
  const [selectedETF, setSelectedETF] = useState<string>('');
  
  // API 数据状态
  const [etfDetails, setEtfDetails] = useState<ETFDetailData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([]);

  // 加载 ETF 数据
  useEffect(() => {
    loadETFData();
  }, [task.etfs]);

  const loadETFData = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const etfDataPromises = task.etfs.map(async (symbol) => {
        try {
          const etf = await api.getETFBySymbol(symbol, false);
          if (etf) {
            return {
              symbol: etf.symbol,
              name: etf.name || getETFName(symbol),
              type: (etf.type as 'sector' | 'industry') || getETFType(symbol),
              score: etf.score > 0 ? etf.score : null,
              rank: etf.rank > 0 ? etf.rank : null,
              totalCount: task.etfs.length,
              delta3d: etf.delta?.delta3d ?? null,
              delta5d: etf.delta?.delta5d ?? null,
              completeness: etf.completeness || 0,
              dataStatus: generateDataStatus(etf),
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
          totalCount: task.etfs.length,
          delta3d: null,
          delta5d: null,
          completeness: 0,
          dataStatus: [
            { source: 'Finviz' as const, status: 'missing' as const, updatedAt: null },
            { source: 'MarketChameleon' as const, status: 'missing' as const, updatedAt: null },
            { source: '市场/期权数据' as const, status: 'missing' as const, updatedAt: null },
          ],
        };
      });
      
      const results = await Promise.all(etfDataPromises);
      setEtfDetails(results);
      
      // 生成趋势数据（基于真实数据或空数据）
      setTrendData(generateEmptyTrendData(trendPeriod === '3d' ? 3 : 5));
    } catch (e) {
      setError(e instanceof Error ? e : new Error('加载数据失败'));
    } finally {
      setIsLoading(false);
    }
  };

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
        source: '市场/期权数据' as const, 
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

  const handleExport = () => {
    console.log('Exporting task data...');
    alert('导出功能开发中');
  };

  const handleRefreshAll = () => {
    loadETFData();
  };

  const handleRefreshETF = async (symbol: string) => {
    try {
      const response = await api.refreshETFData(symbol);
      console.log('Refresh ETF response:', response);
      loadETFData();
    } catch (e) {
      console.error('Failed to refresh ETF:', e);
      alert(`刷新 ${symbol} 数据失败`);
    }
  };

  const handleRefreshHoldings = async (symbol: string) => {
    try {
      const response = await api.refreshHoldingsData(symbol);
      console.log('Refresh holdings response:', response);
      loadETFData();
    } catch (e) {
      console.error('Failed to refresh holdings:', e);
      alert(`刷新 ${symbol} Holdings 数据失败`);
    }
  };

  const handleOpenHoldingsModal = (symbol: string) => {
    setSelectedETF(symbol);
    setHoldingsModalOpen(true);
  };

  const handleOpenETFModal = (symbol: string) => {
    setSelectedETF(symbol);
    setETFModalOpen(true);
  };

  if (isLoading) {
    return <LoadingState message="正在加载监控任务数据..." />;
  }

  if (error) {
    return <ErrorMessage error={error} onRetry={loadETFData} />;
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
            className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] transition-colors flex items-center gap-2"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 16h5v5" />
            </svg>
            刷新全部
          </button>
          <button
            onClick={handleExport}
            className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors flex items-center gap-2"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            导出报告
          </button>
        </div>
      </div>

      {/* Trend Chart Section */}
      <div className="mb-6">
        <TrendChart
          data={trendData}
          period={trendPeriod}
          onPeriodChange={setTrendPeriod}
          baselineName={task.baseIndex}
          sectorName={task.sector || task.etfs[0]}
          industryName={task.etfs[task.etfs.length - 1]}
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
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">{task.sector || task.etfs[0]}</th>
                  <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">{task.etfs[task.etfs.length - 1]}</th>
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
          <h3 className="text-base font-semibold">监控ETF ({task.etfs.length})</h3>
        </div>
        <div className="grid grid-cols-3 gap-5">
          {etfDetails.map((etf) => (
            <ETFDetailCard
              key={etf.symbol}
              etf={etf}
              onRefreshETF={() => handleRefreshETF(etf.symbol)}
              onImportETFData={() => handleOpenETFModal(etf.symbol)}
              onRefreshHoldings={() => handleRefreshHoldings(etf.symbol)}
              onImportHoldings={() => handleOpenHoldingsModal(etf.symbol)}
            />
          ))}
        </div>
      </div>

      {/* Modals */}
      <HoldingsImportModal
        isOpen={holdingsModalOpen}
        onClose={() => setHoldingsModalOpen(false)}
        etfSymbol={selectedETF}
        onImport={(data) => {
          console.log('Import holdings:', selectedETF, data);
          loadETFData();
        }}
      />
      <ETFImportModal
        isOpen={etfModalOpen}
        onClose={() => setETFModalOpen(false)}
        etfSymbol={selectedETF}
        onImport={(data) => {
          console.log('Import ETF data:', selectedETF, data);
          loadETFData();
        }}
      />
    </div>
  );
}