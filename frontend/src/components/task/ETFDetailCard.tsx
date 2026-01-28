import React, { useEffect, useMemo, useState } from 'react';

interface DataStatus {
  source: 'Finviz' | 'MarketChameleon' | '市场/期权数据';
  status: 'complete' | 'pending' | 'missing';
  updatedAt: string | null;
  count?: number;
}

interface HoldingSummary {
  ticker: string;
  weight: number;
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
  onRefreshETF: () => void;
  onRefreshHoldings: () => void;
  onImportHoldings: () => void;
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
  },
  pending: {
    label: '待更新',
    bgColor: 'rgba(245, 158, 11, 0.1)',
    textColor: 'var(--accent-amber)',
  },
  missing: {
    label: '缺失',
    bgColor: 'rgba(239, 68, 68, 0.1)',
    textColor: 'var(--accent-red)',
  },
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
}: ETFDetailCardProps) {
  const [activeCoverage, setActiveCoverage] = useState<CoverageOption['id']>('top10');

  const sortedHoldings = useMemo(() => {
    const holdings = etf.holdings || [];
    return [...holdings].sort((a, b) => b.weight - a.weight);
  }, [etf.holdings]);

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

  const showCoverageSection = availableCoverageOptions.length >= 2;
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

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5 shadow-sm">
      {/* Header */}
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
            onClick={onRefreshETF}
            className="px-3.5 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] text-white transition-opacity flex items-center gap-1.5 hover:opacity-90"
            style={{ background: 'var(--accent-green)' }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 16h5v5" />
            </svg>
            刷新 ETF 数据
          </button>
          <div className="text-right">
            <div className="text-2xl font-bold leading-none">
              {etf.score !== null ? etf.score.toFixed(1) : '--'}
            </div>
            <div className="text-[12px] text-[var(--text-muted)] mt-1">
              排名 #{etf.rank !== null ? etf.rank : '-'}/{etf.totalCount}
            </div>
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="flex items-center justify-between mt-4 pb-4 border-b border-[var(--border-light)]">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Δ3D</span>
            <span className={`text-sm font-semibold ${delta3d.className}`}>{delta3d.text}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Δ5D</span>
            <span className={`text-sm font-semibold ${delta5d.className}`}>{delta5d.text}</span>
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

      {/* Data Status List */}
      <div className="mt-4">
        <div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)] mb-2.5">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-[var(--bg-secondary)] text-[var(--text-muted)]">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M12 3v18" />
            </svg>
          </span>
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
                    className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                    style={{ background: config.bgColor, color: config.textColor }}
                  >
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

      {/* Coverage Tabs */}
      {showCoverageSection && (
        <div className="mt-4 pt-4 border-t border-[var(--border-light)]">
          <div className="text-[13px] text-[var(--text-muted)] mb-2.5">
            已导入的覆盖范围（点击切换查看详情）
          </div>
          <div className="flex items-center gap-2 flex-wrap mb-3">
            {availableCoverageOptions.map((option) => {
              const isActive = option.id === activeCoverage;
              return (
                <button
                  key={option.id}
                  onClick={() => setActiveCoverage(option.id)}
                  className={`px-3 py-1 text-xs font-medium rounded-full border transition-colors ${
                    isActive
                      ? 'bg-[var(--accent-blue)] text-white border-transparent'
                      : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] border-[var(--border-light)] hover:bg-[var(--bg-tertiary)]'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          <div
            className="border border-[var(--border-light)] rounded-[var(--radius-md)] p-3"
            style={{ background: 'linear-gradient(135deg, rgba(253, 230, 138, 0.12), rgba(255, 241, 242, 0.12))' }}
          >
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="font-semibold text-[var(--text-primary)]">
                {activeOption.label} 持仓股数据状态
              </span>
              <span className="text-[var(--text-muted)]">
                {activeHoldings.length}/{sortedHoldings.length} · 累计 {formatWeight(coverageSum)}%
              </span>
            </div>
            {activeHoldings.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {activeHoldings.map((holding) => (
                  <div
                    key={holding.ticker}
                    className="px-2.5 py-1 text-xs rounded-full border border-[var(--border-light)] bg-white text-[var(--text-secondary)] flex items-center gap-1.5"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                    <span className="font-medium text-[var(--text-primary)]">{holding.ticker}</span>
                    <span className="text-[var(--text-muted)]">{formatWeight(holding.weight)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-[var(--text-muted)]">暂无持仓数据，请先导入 Holdings。</div>
            )}
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex gap-2.5 pt-4 border-t border-[var(--border-light)] mt-4">
        <button
          onClick={onRefreshHoldings}
          className="flex-1 py-2.5 text-xs font-medium rounded-[var(--radius-md)] cursor-pointer text-center bg-[var(--bg-secondary)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors flex items-center justify-center gap-1.5"
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
            <path d="M12 5v14M5 12l7-7 7 7" />
          </svg>
          导入 Holdings
        </button>
      </div>
    </div>
  );
}
