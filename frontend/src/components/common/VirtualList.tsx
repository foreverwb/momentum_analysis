import React, { useRef, useState, useEffect, useCallback, useMemo, memo } from 'react';

// ============================================================================
// Types
// ============================================================================

interface VirtualListProps<T> {
  /** 列表数据 */
  items: T[];
  /** 每项高度（固定高度模式）或估算高度（动态高度模式） */
  itemHeight: number;
  /** 容器高度 */
  containerHeight: number;
  /** 渲染每一项的函数 */
  renderItem: (item: T, index: number) => React.ReactNode;
  /** 提取每项的唯一键 */
  keyExtractor: (item: T, index: number) => string | number;
  /** 可视区域外额外渲染的项数（默认 3） */
  overscan?: number;
  /** 列表为空时显示的内容 */
  emptyComponent?: React.ReactNode;
  /** 自定义容器类名 */
  className?: string;
  /** 加载更多回调 */
  onLoadMore?: () => void;
  /** 触发加载更多的阈值（距底部距离） */
  loadMoreThreshold?: number;
  /** 是否正在加载更多 */
  isLoadingMore?: boolean;
}

interface VisibleRange {
  start: number;
  end: number;
}

// ============================================================================
// VirtualList Component
// ============================================================================

/**
 * VirtualList 虚拟滚动列表组件
 * 
 * 特性:
 * - 只渲染可见区域的项目，大幅提升性能
 * - 支持固定高度项目
 * - 支持无限滚动加载
 * - 自定义空状态
 * 
 * 使用方式:
 * ```tsx
 * <VirtualList
 *   items={stocks}
 *   itemHeight={200}
 *   containerHeight={600}
 *   keyExtractor={(item) => item.symbol}
 *   renderItem={(stock, index) => <StockCard stock={stock} rank={index + 1} />}
 * />
 * ```
 */
function VirtualListInner<T>({
  items,
  itemHeight,
  containerHeight,
  renderItem,
  keyExtractor,
  overscan = 3,
  emptyComponent,
  className = '',
  onLoadMore,
  loadMoreThreshold = 200,
  isLoadingMore = false,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);

  // 计算总高度
  const totalHeight = items.length * itemHeight;

  // 计算可见范围
  const visibleRange = useMemo((): VisibleRange => {
    const start = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
    const visibleCount = Math.ceil(containerHeight / itemHeight);
    const end = Math.min(items.length, start + visibleCount + overscan * 2);
    return { start, end };
  }, [scrollTop, itemHeight, containerHeight, overscan, items.length]);

  // 处理滚动
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const target = e.target as HTMLDivElement;
    setScrollTop(target.scrollTop);

    // 检查是否需要加载更多
    if (onLoadMore && !isLoadingMore) {
      const scrollBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
      if (scrollBottom < loadMoreThreshold) {
        onLoadMore();
      }
    }
  }, [onLoadMore, isLoadingMore, loadMoreThreshold]);

  // 滚动到指定索引
  const scrollToIndex = useCallback((index: number, align: 'start' | 'center' | 'end' = 'start') => {
    if (!containerRef.current) return;

    let targetScrollTop = index * itemHeight;

    if (align === 'center') {
      targetScrollTop = index * itemHeight - containerHeight / 2 + itemHeight / 2;
    } else if (align === 'end') {
      targetScrollTop = index * itemHeight - containerHeight + itemHeight;
    }

    containerRef.current.scrollTop = Math.max(0, targetScrollTop);
  }, [itemHeight, containerHeight]);

  // 渲染可见项目
  const visibleItems = useMemo(() => {
    const result: React.ReactNode[] = [];

    for (let i = visibleRange.start; i < visibleRange.end; i++) {
      const item = items[i];
      const key = keyExtractor(item, i);
      const style: React.CSSProperties = {
        position: 'absolute',
        top: i * itemHeight,
        left: 0,
        right: 0,
        height: itemHeight,
      };

      result.push(
        <div key={key} style={style}>
          {renderItem(item, i)}
        </div>
      );
    }

    return result;
  }, [items, visibleRange, itemHeight, keyExtractor, renderItem]);

  // 空状态
  if (items.length === 0) {
    return (
      <div className={`h-full flex items-center justify-center ${className}`}>
        {emptyComponent || (
          <div className="text-center py-12">
            <div className="text-6xl mb-4 opacity-50">📊</div>
            <p className="text-[var(--text-muted)]">暂无数据</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`overflow-auto relative ${className}`}
      style={{ height: containerHeight }}
      onScroll={handleScroll}
    >
      {/* 占位元素，用于创建滚动空间 */}
      <div style={{ height: totalHeight, position: 'relative' }}>
        {visibleItems}
      </div>

      {/* 加载更多指示器 */}
      {isLoadingMore && (
        <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2">
          <div className="flex items-center gap-2 px-4 py-2 bg-[var(--bg-primary)] rounded-full shadow-lg">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-[var(--accent-blue)]" />
            <span className="text-sm text-[var(--text-muted)]">加载中...</span>
          </div>
        </div>
      )}
    </div>
  );
}

// 使用 memo 优化
export const VirtualList = memo(VirtualListInner) as typeof VirtualListInner;

// ============================================================================
// VirtualStockList - 专门为股票列表优化的虚拟滚动
// ============================================================================

interface VirtualStockListProps<T> {
  stocks: T[];
  itemHeight?: number;
  maxHeight?: number;
  renderStock: (stock: T, index: number) => React.ReactNode;
  keyExtractor: (stock: T) => string;
  emptyMessage?: string;
  className?: string;
  onLoadMore?: () => void;
  hasMore?: boolean;
  isLoading?: boolean;
}

/**
 * VirtualStockList 股票虚拟滚动列表
 * 
 * 针对股票卡片优化的虚拟滚动列表
 * 当股票数量超过阈值时自动启用虚拟滚动
 */
export function VirtualStockList<T extends { symbol?: string; id?: string | number }>({
  stocks,
  itemHeight = 280, // StockCard 默认高度
  maxHeight,
  renderStock,
  keyExtractor,
  emptyMessage = '暂无符合条件的股票',
  className = '',
  onLoadMore,
  hasMore = false,
  isLoading = false,
}: VirtualStockListProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerHeight, setContainerHeight] = useState(() => maxHeight ?? 800);

  // 动态计算容器高度
  useEffect(() => {
    if (containerRef.current) {
      const updateHeight = () => {
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect) {
          const MIN_CONTAINER_HEIGHT = 400;
          const VIEWPORT_BOTTOM_GAP = 24;
          const availableHeight = window.innerHeight - rect.top - VIEWPORT_BOTTOM_GAP;
          const computedHeight = Math.max(MIN_CONTAINER_HEIGHT, availableHeight);
          const nextHeight = typeof maxHeight === 'number'
            ? Math.min(maxHeight, computedHeight)
            : computedHeight;

          setContainerHeight(nextHeight);
        }
      };

      updateHeight();
      window.addEventListener('resize', updateHeight);
      return () => window.removeEventListener('resize', updateHeight);
    }
  }, [maxHeight]);

  // 虚拟滚动阈值
  const VIRTUAL_THRESHOLD = 50;
  const shouldVirtualize = stocks.length > VIRTUAL_THRESHOLD;

  // 空状态
  if (stocks.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center py-16 px-4 bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] ${className}`}>
        <div className="text-6xl mb-4 opacity-50">📊</div>
        <h3 className="text-lg font-medium text-[var(--text-primary)] mb-2">
          {emptyMessage}
        </h3>
        <p className="text-sm text-[var(--text-muted)] text-center max-w-md">
          请调整筛选条件或稍后再试
        </p>
      </div>
    );
  }

  // 使用虚拟滚动
  if (shouldVirtualize) {
    return (
      <div ref={containerRef} className={className}>
        <div className="mb-2 text-xs text-[var(--text-muted)] px-2">
          共 {stocks.length} 只股票 (虚拟滚动已启用)
        </div>
        <VirtualList
          items={stocks}
          itemHeight={itemHeight}
          containerHeight={containerHeight}
          keyExtractor={(item, index) => keyExtractor(item) || `item-${index}`}
          renderItem={renderStock}
          overscan={3}
          onLoadMore={hasMore ? onLoadMore : undefined}
          isLoadingMore={isLoading}
          className="rounded-[var(--radius-lg)] border border-[var(--border-light)]"
        />
      </div>
    );
  }

  // 常规渲染（股票数量较少时）
  return (
    <div className={`space-y-5 ${className}`}>
      {stocks.map((stock, index) => (
        <div key={keyExtractor(stock) || `stock-${index}`}>
          {renderStock(stock, index)}
        </div>
      ))}
      
      {/* 加载更多 */}
      {hasMore && (
        <div className="flex justify-center py-4">
          {isLoading ? (
            <div className="flex items-center gap-2">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[var(--accent-blue)]" />
              <span className="text-sm text-[var(--text-muted)]">加载中...</span>
            </div>
          ) : (
            <button
              onClick={onLoadMore}
              className="px-6 py-2 bg-[var(--bg-secondary)] text-[var(--text-secondary)] rounded-lg text-sm font-medium hover:bg-[var(--bg-tertiary)] transition-colors"
            >
              加载更多
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// useVirtualScroll Hook
// ============================================================================

interface UseVirtualScrollOptions {
  itemCount: number;
  itemHeight: number;
  containerHeight: number;
  overscan?: number;
}

interface UseVirtualScrollResult {
  visibleRange: VisibleRange;
  totalHeight: number;
  offsetTop: number;
  handleScroll: (scrollTop: number) => void;
}

/**
 * useVirtualScroll Hook
 * 
 * 提供虚拟滚动的核心逻辑，可用于自定义虚拟滚动实现
 */
export function useVirtualScroll({
  itemCount,
  itemHeight,
  containerHeight,
  overscan = 3,
}: UseVirtualScrollOptions): UseVirtualScrollResult {
  const [scrollTop, setScrollTop] = useState(0);

  const totalHeight = itemCount * itemHeight;

  const visibleRange = useMemo((): VisibleRange => {
    const start = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
    const visibleCount = Math.ceil(containerHeight / itemHeight);
    const end = Math.min(itemCount, start + visibleCount + overscan * 2);
    return { start, end };
  }, [scrollTop, itemHeight, containerHeight, overscan, itemCount]);

  const offsetTop = visibleRange.start * itemHeight;

  const handleScroll = useCallback((newScrollTop: number) => {
    setScrollTop(newScrollTop);
  }, []);

  return {
    visibleRange,
    totalHeight,
    offsetTop,
    handleScroll,
  };
}

// ============================================================================
// Export
// ============================================================================

export default VirtualList;
