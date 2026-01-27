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
    score: number;
    rank: number;
    totalCount: number;
    delta3d: number | null;
    delta5d: number | null;
    completeness: number;
    dataStatus: DataStatus[];
  };
  onRefreshETF: () => void;
  onImportHoldings: () => void;
  onImportETFData: () => void;
}

const statusConfig = {
  complete: {
    label: '完整',
    bgColor: 'rgba(34, 197, 94, 0.1)',
    textColor: 'var(--accent-green)',
  },
  pending: {
    label: '部分',
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
  onImportHoldings,
  onImportETFData,
}: ETFDetailCardProps) {
  const formatDelta = (value: number | null): { text: string; className: string } => {
    if (value === null || value === undefined) {
      return { text: '--', className: '' };
    }
    if (value > 0) {
      return { text: `+${value.toFixed(1)}`, className: 'text-[var(--accent-green)]' };
    }
    if (value < 0) {
      return { text: `${value.toFixed(1)}`, className: 'text-[var(--accent-red)]' };
    }
    return { text: '0', className: '' };
  };

  const delta3d = formatDelta(etf.delta3d);
  const delta5d = formatDelta(etf.delta5d);

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1">
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
          <div className="text-[13px] text-[var(--text-muted)]">{etf.name}</div>
        </div>
        <button
          onClick={onRefreshETF}
          className="p-2 rounded-[var(--radius-sm)] text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          title="刷新数据"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
            <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
            <path d="M16 16h5v5" />
          </svg>
        </button>
      </div>

      {/* Score Section */}
      <div className="flex items-end gap-5 mb-4 pb-4 border-b border-[var(--border-light)]">
        <div className="text-4xl font-bold leading-none">{etf.score.toFixed(1)}</div>
        <div className="text-[13px] text-[var(--text-muted)] mb-1">
          排名 #{etf.rank}/{etf.totalCount}
        </div>
        <div className="flex gap-4 ml-auto">
          <div className="flex items-center gap-1">
            <span className="text-xs text-[var(--text-muted)]">3D</span>
            <span className={`text-sm font-semibold ${delta3d.className}`}>{delta3d.text}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-[var(--text-muted)]">5D</span>
            <span className={`text-sm font-semibold ${delta5d.className}`}>{delta5d.text}</span>
          </div>
        </div>
      </div>

      {/* Completeness */}
      <div className="mb-4">
        <div className="flex items-center justify-between text-xs mb-2">
          <span className="text-[var(--text-muted)]">数据完备度</span>
          <span className="font-semibold text-[var(--accent-green)]">{etf.completeness}%</span>
        </div>
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
                  <span className="text-[var(--text-primary)] min-w-[100px]">{status.source}</span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                    style={{ background: config.bgColor, color: config.textColor }}
                  >
                    {config.label}
                  </span>
                </div>
                <span className="text-[var(--text-muted)]">
                  {status.updatedAt ? status.updatedAt : '--'}
                  {status.count !== undefined && ` · ${status.count}只`}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2.5 pt-3.5 border-t border-[var(--border-light)]">
        <button
          onClick={onImportHoldings}
          className="flex-1 py-2.5 text-xs rounded-[var(--radius-md)] cursor-pointer text-center border"
          style={{
            background: 'rgba(245, 158, 11, 0.1)',
            borderColor: 'rgba(245, 158, 11, 0.3)',
            color: 'var(--accent-amber)',
          }}
        >
          导入持仓
        </button>
        <button
          onClick={onImportETFData}
          className="flex-1 py-2.5 text-xs rounded-[var(--radius-md)] cursor-pointer text-center bg-[var(--bg-secondary)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
        >
          导入ETF数据
        </button>
      </div>
    </div>
  );
}
