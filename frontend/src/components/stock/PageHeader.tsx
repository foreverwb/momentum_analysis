import React from 'react';

type ViewMode = 'list' | 'detail' | 'compare';

interface PageHeaderProps {
  viewMode: ViewMode;
  onBack?: () => void;
  selectedStock?: string | null;
  stockCount?: number;
}

/**
 * PageHeader Component
 * 
 * Displays the page title and navigation controls based on current view mode
 * 
 * - List view: Shows title and stock count
 * - Detail view: Shows back button and stock symbol
 * - Compare view: Shows back button and comparison title
 */
export function PageHeader({ 
  viewMode, 
  onBack, 
  selectedStock,
  stockCount = 0 
}: PageHeaderProps) {
  
  // List View Header
  if (viewMode === 'list') {
    return (
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h5>Total - {stockCount}</h5>
        </div>
      </div>
    );
  }

  // Detail View Header
  if (viewMode === 'detail') {
    return (
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="
            flex items-center gap-2 px-3 py-2
            text-sm text-[var(--text-secondary)]
            hover:text-[var(--text-primary)]
            hover:bg-[var(--bg-secondary)]
            rounded-[var(--radius-md)]
            transition-all
          "
        >
          <span>←</span>
          <span>返回列表</span>
        </button>
        <div className="w-px h-6 bg-[var(--border-light)]" />
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            {selectedStock || '股票详情'}
          </h1>
        </div>
      </div>
    );
  }

  // Compare View Header
  if (viewMode === 'compare') {
    return (
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="
            flex items-center gap-2 px-3 py-2
            text-sm text-[var(--text-secondary)]
            hover:text-[var(--text-primary)]
            hover:bg-[var(--bg-secondary)]
            rounded-[var(--radius-md)]
            transition-all
          "
        >
          <span>←</span>
          <span>返回列表</span>
        </button>
        <div className="w-px h-6 bg-[var(--border-light)]" />
        <div className="flex items-center gap-2">
          <span className="text-xl">⚖️</span>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            股票对比分析
          </h1>
        </div>
      </div>
    );
  }

  return null;
}
