import React, { memo, useMemo, useCallback } from 'react';
import type { StockDetail } from '../../types';

interface CompareTableProps {
  stocks: StockDetail[];
  onClose?: () => void;
}

// ============================================================================
// 格式化工具函数（移到组件外部）
// ============================================================================

const formatPercent = (value?: number | null): string => {
  if (value === null || value === undefined) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
};

const formatNumber = (value?: number | null, decimals = 2): string => {
  if (value === null || value === undefined) return '--';
  return value.toFixed(decimals);
};

const formatPrice = (value?: number): string => {
  if (value === null || value === undefined) return '--';
  return `$${value.toFixed(2)}`;
};

// ============================================================================
// Metric Row Component (Memoized)
// ============================================================================

interface MetricRowProps {
  metric: {
    label: string;
    getValue: (stock: StockDetail) => number | null | undefined;
    format: (val?: number | null) => string;
    higherIsBetter: boolean;
  };
  stocks: StockDetail[];
  bestIndex: number;
}

const MetricRow = memo(function MetricRow({ metric, stocks, bestIndex }: MetricRowProps) {
  return (
    <tr>
      <td className="py-4 px-5 text-sm text-[var(--text-muted)] font-medium border-b border-[var(--border-light)]">
        {metric.label}
      </td>
      {stocks.map((stock, stockIdx) => {
        const value = metric.getValue(stock);
        const isBest = stockIdx === bestIndex;
        
        return (
          <td 
            key={stock.symbol}
            className={`py-4 px-5 text-sm font-semibold border-b border-[var(--border-light)] ${
              isBest 
                ? 'bg-green-50 text-[var(--accent-green)]' 
                : 'text-[var(--text-primary)]'
            }`}
          >
            {metric.format(value)}
          </td>
        );
      })}
    </tr>
  );
});

// ============================================================================
// CompareTable Component
// ============================================================================

/**
 * CompareTable - 股票对比表格组件
 * 
 * Table component for comparing multiple stocks side by side
 * Highlights the best value in each metric row
 * 
 * 性能优化:
 * - 使用 React.memo 避免不必要的重渲染
 * - 使用 useMemo 缓存指标定义和计算结果
 * - 子组件 MetricRow 也使用 memo 优化
 */
export const CompareTable = memo(function CompareTable({ stocks, onClose }: CompareTableProps) {
  // Helper to find best value index for highlighting
  const findBestIndex = useCallback((
    values: (number | null | undefined)[],
    higherIsBetter: boolean
  ): number => {
    if (!higherIsBetter) return -1;
    
    let bestIndex = -1;
    let bestValue = -Infinity;
    
    values.forEach((val, idx) => {
      const numVal = val ?? -Infinity;
      if (numVal > bestValue) {
        bestValue = numVal;
        bestIndex = idx;
      }
    });
    
    return bestIndex;
  }, []);

  // Define metrics to compare (memoized)
  const metrics = useMemo(() => [
    {
      label: '综合得分',
      getValue: (stock: StockDetail) => stock.totalScore,
      format: (val?: number | null) => formatNumber(val, 1),
      higherIsBetter: true
    },
    {
      label: '价格动能得分',
      getValue: (stock: StockDetail) => stock.momentumScore,
      format: (val?: number | null) => formatNumber(val, 1),
      higherIsBetter: true
    },
    {
      label: '趋势结构得分',
      getValue: (stock: StockDetail) => stock.technicalScore,
      format: (val?: number | null) => formatNumber(val, 1),
      higherIsBetter: true
    },
    {
      label: '量价确认得分',
      getValue: (stock: StockDetail) => stock.volumeScore,
      format: (val?: number | null) => formatNumber(val, 1),
      higherIsBetter: true
    },
    {
      label: '期权覆盖得分',
      getValue: (stock: StockDetail) => stock.optionsScore,
      format: (val?: number | null) => formatNumber(val, 1),
      higherIsBetter: true
    },
    {
      label: '当前价格',
      getValue: (stock: StockDetail) => stock.price,
      format: formatPrice,
      higherIsBetter: false
    },
    {
      label: '20日收益',
      getValue: (stock: StockDetail) => stock.return20d,
      format: formatPercent,
      higherIsBetter: true
    },
    {
      label: '63日收益',
      getValue: (stock: StockDetail) => stock.return63d,
      format: formatPercent,
      higherIsBetter: true
    },
    {
      label: '相对强度(20D)',
      getValue: (stock: StockDetail) => stock.rs20d,
      format: (val?: number | null) => formatNumber(val, 2),
      higherIsBetter: true
    },
    {
      label: 'RSI',
      getValue: (stock: StockDetail) => stock.rsi,
      format: (val?: number | null) => formatNumber(val, 1),
      higherIsBetter: false
    },
    {
      label: '成交量比',
      getValue: (stock: StockDetail) => stock.volumeRatio,
      format: (val?: number | null) => formatNumber(val, 2),
      higherIsBetter: true
    },
    {
      label: 'IV排名',
      getValue: (stock: StockDetail) => stock.ivr,
      format: (val?: number | null) => formatNumber(val, 0),
      higherIsBetter: true
    },
  ], []);

  // 计算每个指标的最佳索引
  const bestIndices = useMemo(() => {
    return metrics.map(metric => {
      const values = stocks.map(stock => metric.getValue(stock));
      return findBestIndex(values, metric.higherIsBetter);
    });
  }, [metrics, stocks, findBestIndex]);

  // Empty state
  if (!stocks || stocks.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-[var(--text-muted)]">请选择至少2只股票进行对比</p>
      </div>
    );
  }

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-6 border-b border-[var(--border-light)]">
        <div>
          <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
            股票对比
          </h2>
          <p className="text-sm text-[var(--text-muted)]">
            对比 {stocks.length} 只股票的关键指标
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="px-4 py-2 bg-[var(--bg-tertiary)] text-[var(--text-secondary)] rounded-lg text-sm font-medium hover:bg-[var(--bg-secondary)] transition-colors"
          >
            关闭
          </button>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead className="bg-[var(--bg-secondary)]">
            <tr>
              <th className="py-4 px-5 text-left text-[13px] font-semibold text-[var(--text-primary)] border-b border-[var(--border-light)] min-w-[160px]">
                指标
              </th>
              {stocks.map((stock) => (
                <th 
                  key={stock.symbol}
                  className="py-4 px-5 text-left text-[13px] font-semibold text-[var(--text-primary)] border-b border-[var(--border-light)] min-w-[120px]"
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-base font-bold">{stock.symbol}</span>
                    <span className="text-xs font-normal text-[var(--text-muted)]">
                      {stock.name}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric, metricIdx) => (
              <MetricRow
                key={metric.label}
                metric={metric}
                stocks={stocks}
                bestIndex={bestIndices[metricIdx]}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer Info */}
      <div className="p-4 bg-[var(--bg-secondary)] text-xs text-[var(--text-muted)] border-t border-[var(--border-light)]">
        <div className="flex items-center gap-2">
          <span className="inline-block w-3 h-3 bg-green-50 border border-green-200 rounded"></span>
          <span>绿色高亮表示该项指标最优</span>
        </div>
      </div>
    </div>
  );
});