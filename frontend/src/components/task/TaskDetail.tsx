import React, { useState } from 'react';
import { TrendChart, type TrendDataPoint } from '../chart';
import { ETFDetailCard } from './ETFDetailCard';
import { HoldingsImportModal, ETFImportModal } from '../modal';
import type { Task } from '../../types';

interface TaskDetailProps {
  task: Task;
  onBack: () => void;
}

// Mock trend data generator
function generateMockTrendData(days: number): TrendDataPoint[] {
  const data: TrendDataPoint[] = [];
  const today = new Date();
  
  let baseline = 100;
  let sector = 100;
  let industry = 100;
  
  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    
    // Random walk
    baseline += (Math.random() - 0.5) * 2;
    sector += (Math.random() - 0.45) * 2.5;
    industry += (Math.random() - 0.4) * 3;
    
    data.push({
      date: `${date.getMonth() + 1}/${date.getDate()}`,
      baseline: Number(baseline.toFixed(2)),
      sector: Number(sector.toFixed(2)),
      industry: Number(industry.toFixed(2)),
      sectorVsBaseline: Number((sector - baseline).toFixed(2)),
      industryVsSector: Number((industry - sector).toFixed(2)),
    });
  }
  
  return data;
}

// Mock ETF detail data
const generateMockETFDetails = (symbols: string[]) => {
  return symbols.map((symbol, index) => ({
    symbol,
    name: getETFName(symbol),
    type: getETFType(symbol),
    score: 65 + Math.random() * 20,
    rank: index + 1,
    totalCount: symbols.length,
    delta3d: (Math.random() - 0.4) * 5,
    delta5d: (Math.random() - 0.35) * 8,
    completeness: 70 + Math.random() * 30,
    dataStatus: [
      { source: 'Finviz' as const, status: Math.random() > 0.3 ? 'complete' as const : 'pending' as const, updatedAt: '今天 09:30', count: Math.floor(20 + Math.random() * 30) },
      { source: 'MarketChameleon' as const, status: Math.random() > 0.5 ? 'complete' as const : 'pending' as const, updatedAt: '今天 10:15' },
      { source: '市场/期权数据' as const, status: Math.random() > 0.7 ? 'complete' as const : 'missing' as const, updatedAt: Math.random() > 0.5 ? '昨天 16:00' : null },
    ],
  }));
};

function getETFName(symbol: string): string {
  const names: Record<string, string> = {
    XLK: 'Technology Select Sector SPDR',
    XLF: 'Financial Select Sector SPDR',
    XLV: 'Health Care Select Sector SPDR',
    XLE: 'Energy Select Sector SPDR',
    SOXX: 'iShares Semiconductor ETF',
    SMH: 'VanEck Semiconductor ETF',
    IGV: 'iShares Expanded Tech-Software ETF',
    SKYY: 'First Trust Cloud Computing ETF',
    HACK: 'ETFMG Prime Cyber Security ETF',
  };
  return names[symbol] || `${symbol} ETF`;
}

function getETFType(symbol: string): 'sector' | 'industry' {
  const sectors = ['XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLI', 'XLC', 'XLP', 'XLU', 'XLRE', 'XLB'];
  return sectors.includes(symbol) ? 'sector' : 'industry';
}

export function TaskDetail({ task, onBack }: TaskDetailProps) {
  const [trendPeriod, setTrendPeriod] = useState<'3d' | '5d'>('5d');
  const [holdingsModalOpen, setHoldingsModalOpen] = useState(false);
  const [etfModalOpen, setETFModalOpen] = useState(false);
  const [selectedETF, setSelectedETF] = useState<string>('');

  const trendData = generateMockTrendData(trendPeriod === '3d' ? 3 : 5);
  const etfDetails = generateMockETFDetails(task.etfs);

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
    console.log('Refreshing all ETF data...');
    alert('刷新全部数据');
  };

  const handleOpenHoldingsModal = (symbol: string) => {
    setSelectedETF(symbol);
    setHoldingsModalOpen(true);
  };

  const handleOpenETFModal = (symbol: string) => {
    setSelectedETF(symbol);
    setETFModalOpen(true);
  };

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
              onRefreshETF={() => console.log('Refresh ETF:', etf.symbol)}
              onImportHoldings={() => handleOpenHoldingsModal(etf.symbol)}
              onImportETFData={() => handleOpenETFModal(etf.symbol)}
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
          alert(`导入 ${selectedETF} 持仓数据成功`);
        }}
      />
      <ETFImportModal
        isOpen={etfModalOpen}
        onClose={() => setETFModalOpen(false)}
        etfSymbol={selectedETF}
        onImport={(data) => {
          console.log('Import ETF data:', selectedETF, data);
          alert(`导入 ${selectedETF} ETF数据成功`);
        }}
      />
    </div>
  );
}
