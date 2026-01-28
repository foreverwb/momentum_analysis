import React from 'react';

interface DataStatus {
  source: 'Finviz' | 'MarketChameleon' | '市场/期权数据';
  status: 'complete' | 'pending' | 'missing';
  updatedAt: string | null;
  count?: number;
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
    dataStatus: DataStatus[];
  };
  onRefreshETF: () => void;
  onImportETFData: () => void;
  onRefreshHoldings: () => void;
  onImportHoldings: () => void;
}

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

export function ETFDetailCard({
  etf,
  onRefreshETF,
  onImportETFData,
  onRefreshHoldings,
  onImportHoldings,
}: ETFDetailCardProps) {
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
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
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
        <div className="flex items-center gap-2">
          <button
            onClick={onRefreshETF}
            className="px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] bg-[var(--bg-secondary)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors flex items-center gap-1.5"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 16h5v5" />
            </svg>
            刷新 ETF
          </button>
          <button
            onClick={onImportETFData}
            className="px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] bg-[var(--bg-secondary)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors flex items-center gap-1.5"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12l7-7 7 7" />
            </svg>
            导入 ETF 数据
          </button>
        </div>
      </div>
      
      {/* ETF Name */}
      <div className="text-[13px] text-[var(--text-muted)] mb-4">{etf.name}</div>

      {/* Score Section */}
      <div className="flex items-end justify-between mb-4 pb-4 border-b border-[var(--border-light)]">
        <div>
          <div className="text-4xl font-bold leading-none">
            {etf.score !== null ? etf.score.toFixed(1) : '--'}
          </div>
          <div className="text-[13px] text-[var(--text-muted)] mt-1">
            排名 #{etf.rank !== null ? etf.rank : '-'}/{etf.totalCount}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-[var(--text-muted)]">Δ3D</span>
            <span className={`text-sm font-semibold ${delta3d.className}`}>{delta3d.text}</span>
          </div>
          <div className="flex items-center gap-1.5">
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

      {/* Completeness Progress Bar */}
      <div className="mb-4">
        <div className="h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{
              width: `${etf.completeness}%`,
              background:
                etf.completeness >= 80
                  ? 'var(--accent-green)'
                  : etf.completeness >= 50
                  ? 'var(--accent-amber)'
                  : 'var(--accent-red)',
            }}
          />
        </div>
      </div>

      {/* Data Status List */}
      <div className="mb-4">
        <div className="text-[13px] text-[var(--text-muted)] mb-2.5">数据状态</div>
        <div className="flex flex-col gap-2">
          {etf.dataStatus.map((status, index) => {
            const config = statusConfig[status.status];
            return (
              <div key={index} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
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

      {/* Action Buttons */}
      <div className="flex gap-2.5 pt-3.5 border-t border-[var(--border-light)]">
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