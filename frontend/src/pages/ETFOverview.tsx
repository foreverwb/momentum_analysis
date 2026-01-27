import React, { useState } from 'react';
import { useETFs } from '../hooks/useData';
import { ETFCard } from '../components/etf';
import { LoadingState, ErrorMessage, Button } from '../components/common';
import { HoldingsImportModal, ETFImportModal } from '../components/modal';

interface ETFOverviewProps {
  type: 'sector' | 'industry';
}

// 趋势向上图标
const TrendingUpIcon = (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline>
    <polyline points="17 6 23 6 23 12"></polyline>
  </svg>
);

export function ETFOverview({ type }: ETFOverviewProps) {
  const { data: etfs, isLoading, error, refetch } = useETFs(type);
  const [viewMode, setViewMode] = useState<'card' | 'table'>('card');
  const [holdingsModalOpen, setHoldingsModalOpen] = useState(false);
  const [etfModalOpen, setETFModalOpen] = useState(false);
  const [selectedETF, setSelectedETF] = useState<string>('');
  const [showAll, setShowAll] = useState(false);

  const title = type === 'sector' ? '板块 ETF 分析矩阵' : '行业 ETF 分析矩阵';

  // 过滤只有 holdings 的 ETF（除非用户选择显示全部）
  const filteredETFs = etfs?.filter(etf => showAll || etf.holdingsCount > 0) || [];
  const etfsWithoutHoldings = etfs?.filter(etf => etf.holdingsCount === 0) || [];

  const handleViewHoldings = (symbol: string) => {
    setSelectedETF(symbol);
    setHoldingsModalOpen(true);
  };

  const handleRefresh = (symbol: string) => {
    setSelectedETF(symbol);
    setETFModalOpen(true);
  };

  if (isLoading) {
    return <LoadingState message={`正在加载${type === 'sector' ? '板块' : '行业'} ETF 数据...`} />;
  }

  if (error) {
    return <ErrorMessage error={error} onRetry={refetch} />;
  }

  // 获取当前时间
  const now = new Date();
  const timeStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  return (
    <div className="space-y-4">
      {/* Page Header - 参考 data_config_etf_panel.html 的设计 */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="w-5 h-5 text-blue-600">{TrendingUpIcon}</span>
          <h2 className="text-xl font-bold text-slate-900">{title}</h2>
          <span className="text-sm text-slate-600">
            {filteredETFs.length} 个{type === 'sector' ? '板块' : '行业'}
            {!showAll && etfsWithoutHoldings.length > 0 && (
              <span className="text-slate-400 ml-1">
                (已隐藏 {etfsWithoutHoldings.length} 个无持仓)
              </span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-4">
          {/* Show All Toggle */}
          {etfsWithoutHoldings.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={showAll}
                onChange={(e) => setShowAll(e.target.checked)}
                className="w-4 h-4 rounded border-slate-300"
              />
              显示全部
            </label>
          )}
          <div className="text-sm text-slate-600">实时更新 · {timeStr}</div>
          {/* View Toggle */}
          <div className="flex gap-1 bg-white p-1 rounded-xl border border-slate-200 shadow-sm">
            <button
              onClick={() => setViewMode('card')}
              className={`
                px-4 py-2 rounded-sm text-sm font-medium transition-all
                ${viewMode === 'card'
                  ? 'bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-md'
                  : 'text-slate-600 hover:text-slate-900'
                }
              `}
            >
              卡片
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`
                px-4 py-2 rounded-sm text-sm font-medium transition-all
                ${viewMode === 'table'
                  ? 'bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-md'
                  : 'text-slate-600 hover:text-slate-900'
                }
              `}
            >
              表格
            </button>
          </div>
        </div>
      </div>

      {/* Table View */}
      {viewMode === 'table' ? (
        <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[var(--bg-secondary)] border-b border-[var(--border-light)]">
                <th className="text-left py-3 px-4 font-medium text-[var(--text-muted)]">代码</th>
                <th className="text-left py-3 px-4 font-medium text-[var(--text-muted)]">名称</th>
                {type === 'industry' && (
                  <th className="text-left py-3 px-4 font-medium text-[var(--text-muted)]">所属板块</th>
                )}
                <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">综合分</th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">排名</th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">3D变化</th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">5D变化</th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-muted)]">完整度</th>
                <th className="text-center py-3 px-4 font-medium text-[var(--text-muted)]">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredETFs.map((etf) => {
                const formatDelta = (value: number | null) => {
                  if (value === null) return { text: '--', className: '' };
                  if (value > 0) return { text: `+${value.toFixed(1)}`, className: 'text-[var(--accent-green)]' };
                  if (value < 0) return { text: `${value.toFixed(1)}`, className: 'text-[var(--accent-red)]' };
                  return { text: '0', className: '' };
                };
                const delta3d = formatDelta(etf.delta?.delta3d);
                const delta5d = formatDelta(etf.delta?.delta5d);

                return (
                  <tr key={etf.id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-secondary)] transition-colors">
                    <td className="py-3 px-4 font-semibold">{etf.symbol}</td>
                    <td className="py-3 px-4 text-[var(--text-secondary)]">{etf.name}</td>
                    {type === 'industry' && (
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 bg-blue-50 text-[var(--accent-blue)] rounded text-xs font-medium">
                          {etf.parentSector || 'XLK'}
                        </span>
                      </td>
                    )}
                    <td className="text-right py-3 px-4 font-bold text-lg">{etf.score > 0 ? etf.score.toFixed(1) : '--'}</td>
                    <td className="text-right py-3 px-4 text-[var(--text-muted)]">{etf.rank > 0 ? `#${etf.rank}` : '--'}</td>
                    <td className={`text-right py-3 px-4 font-medium ${delta3d.className}`}>{delta3d.text}</td>
                    <td className={`text-right py-3 px-4 font-medium ${delta5d.className}`}>{delta5d.text}</td>
                    <td className="text-right py-3 px-4">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
                          <div
                            className="h-full bg-[var(--accent-green)] rounded-full"
                            style={{ width: `${etf.completeness}%` }}
                          />
                        </div>
                        <span className="text-xs text-[var(--text-muted)] w-10">{etf.completeness}%</span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex items-center justify-center gap-2">
                        <button
                          onClick={() => handleViewHoldings(etf.symbol)}
                          className="px-2.5 py-1 text-xs bg-transparent border border-[var(--accent-blue)] text-[var(--accent-blue)] rounded-[var(--radius-sm)] hover:bg-blue-50 transition-colors"
                        >
                          持仓
                        </button>
                        <button
                          onClick={() => handleRefresh(etf.symbol)}
                          className="px-2.5 py-1 text-xs bg-transparent border border-[var(--border-light)] text-[var(--text-secondary)] rounded-[var(--radius-sm)] hover:bg-[var(--bg-tertiary)] transition-colors"
                        >
                          刷新
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filteredETFs.length === 0 && (
            <div className="text-center py-12 text-slate-500">
              暂无已导入持仓的 ETF 数据
            </div>
          )}
        </div>
      ) : (
        /* Card View - 单列布局，参考 data_config_etf_panel.html */
        <div className="space-y-4">
          {filteredETFs.length > 0 ? (
            filteredETFs.map((etf) => (
              <ETFCard
                key={etf.id}
                etf={etf}
                onViewHoldings={() => handleViewHoldings(etf.symbol)}
                onRefresh={() => handleRefresh(etf.symbol)}
              />
            ))
          ) : (
            <div className="text-center py-12 text-slate-500">
              暂无已导入持仓的 ETF 数据
            </div>
          )}
        </div>
      )}

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