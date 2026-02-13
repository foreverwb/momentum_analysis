import React, { memo, useCallback } from 'react';
import type { Stock } from '../../types';
import { StockCard } from './StockCard';
import { VirtualStockList } from '../common/VirtualList';

interface StockListProps {
  stocks: Stock[];
  isCompareMode?: boolean;
  selectedSymbols?: string[];
  onStockClick?: (symbol: string) => void;
  onToggleSelect?: (symbol: string) => void;
  /** 启用虚拟滚动的阈值（默认 50） */
  virtualScrollThreshold?: number;
  /** 容器最大高度 */
  maxHeight?: number;
}

/**
 * StockList Component
 * 
 * Displays a list of stock cards with optional compare mode functionality
 * 
 * Features:
 * - Renders StockCard for each stock
 * - Passes through compare mode state
 * - Handles stock click and selection events
 * - Shows empty state when no stocks
 * - **虚拟滚动支持**: 当股票数量超过阈值时自动启用
 * 
 * 性能优化:
 * - 使用 React.memo 避免不必要的重渲染
 * - 大列表自动启用虚拟滚动
 */
export const StockList = memo(function StockList({
  stocks,
  isCompareMode = false,
  selectedSymbols = [],
  onStockClick,
  onToggleSelect,
  virtualScrollThreshold = 50,
  maxHeight
}: StockListProps) {

  // 使用 useCallback 缓存渲染函数
  const renderStock = useCallback((stock: Stock, index: number) => (
    <StockCard
      key={stock.symbol || stock.id || index}
      stock={stock}
      rank={index + 1}
      onClick={() => onStockClick?.(stock.symbol)}
      isCompareMode={isCompareMode}
      isSelected={selectedSymbols.includes(stock.symbol)}
      onToggleSelect={onToggleSelect}
    />
  ), [isCompareMode, selectedSymbols, onStockClick, onToggleSelect]);

  const keyExtractor = useCallback((stock: Stock) => stock.symbol || String(stock.id), []);

  // Empty state
  if (stocks.length === 0) {
    return (
      <div className="
        flex flex-col items-center justify-center
        py-16 px-4
        bg-[var(--bg-primary)]
        border border-[var(--border-light)]
        rounded-[var(--radius-lg)]
      ">
        <div className="text-6xl mb-4 opacity-50">📊</div>
        <h3 className="text-lg font-medium text-[var(--text-primary)] mb-2">
          暂无符合条件的股票
        </h3>
        <p className="text-sm text-[var(--text-muted)] text-center max-w-md">
          请调整筛选条件或稍后再试
        </p>
      </div>
    );
  }

  // 大列表使用虚拟滚动
  if (stocks.length > virtualScrollThreshold) {
    return (
      <VirtualStockList
        stocks={stocks}
        itemHeight={420}
        maxHeight={maxHeight}
        renderStock={renderStock}
        keyExtractor={keyExtractor}
        emptyMessage="暂无符合条件的股票"
      />
    );
  }

  // 常规渲染（股票数量较少时）
  return (
    <div className="space-y-5">
      {stocks.map((stock, index) => renderStock(stock, index))}
    </div>
  );
});
