import React, { useState, useMemo } from 'react';
import type { HeatType } from '../types';
import { useStocks, useStockCompare } from '../hooks/useData';
import { useCompareMode } from '../hooks/useCompareMode';
import { LoadingState, ErrorMessage } from '../components/common';
import { 
  PageHeader,
  ControlsBar,
  CompareBanner,
  StockList,
  StockDetailView,
  CompareTable
} from '../components/stock';

// View mode type definition
type ViewMode = 'list' | 'detail' | 'compare';

/**
 * MomentumPool Component
 * 
 * Main page for analyzing momentum stocks with multiple view modes:
 * - List view: Browse all stocks with filtering
 * - Detail view: Deep dive into a single stock
 * - Compare view: Side-by-side comparison of selected stocks
 * 
 * Features:
 * - Industry filtering
 * - Heat type filtering
 * - Compare mode with multi-selection
 * - Seamless view transitions
 */
export function MomentumPool() {
  // ============================================================================
  // State Management
  // ============================================================================
  
  // View mode control
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [selectedStock, setSelectedStock] = useState<string | null>(null);
  
  // Filter states
  const [industryFilter, setIndustryFilter] = useState('all');
  const [heatFilter, setHeatFilter] = useState<HeatType | 'all'>('all');
  
  // Compare mode management
  const {
    isCompareMode,
    selectedSymbols,
    toggleCompareMode,
    toggleStock,
    clearSelection,
    canCompare,
  } = useCompareMode(4); // Max 4 stocks for comparison
  
  // ============================================================================
  // Data Fetching
  // ============================================================================
  
  // Fetch all stocks
  const { data: stocks, isLoading, error, refetch } = useStocks();
  
  // Fetch comparison data (only when in compare view)
  const { data: compareData, isLoading: isCompareLoading } = useStockCompare(
    viewMode === 'compare' ? selectedSymbols : []
  );
  
  // ============================================================================
  // Filter Logic
  // ============================================================================
  
  // Build industry filter options from available stocks
  const industryOptions = useMemo(() => {
    if (!stocks) return [{ value: 'all', label: '全部行业' }];
    
    const industries = Array.from(
      new Set(stocks.map(stock => stock.industry).filter(Boolean))
    ).sort();
    
    return [
      { value: 'all', label: '全部行业' },
      ...industries.map(industry => ({ value: industry!, label: industry! }))
    ];
  }, [stocks]);
  
  // Apply filters to stocks
  const filteredStocks = useMemo(() => {
    if (!stocks) return [];
    
    return stocks.filter(stock => {
      // Industry filter
      if (industryFilter !== 'all' && stock.industry !== industryFilter) {
        return false;
      }
      
      // Heat filter
      if (heatFilter !== 'all' && stock.heatType !== heatFilter) {
        return false;
      }
      
      return true;
    });
  }, [stocks, industryFilter, heatFilter]);
  
  // ============================================================================
  // Event Handlers
  // ============================================================================
  
  /**
   * Handle clicking on a stock card
   * In normal mode: Navigate to detail view
   * In compare mode: Toggle selection
   */
  const handleStockClick = (symbol: string) => {
    if (isCompareMode) {
      toggleStock(symbol);
    } else {
      setSelectedStock(symbol);
      setViewMode('detail');
    }
  };
  
  /**
   * Handle back navigation from detail/compare to list view
   */
  const handleBackToList = () => {
    setViewMode('list');
    setSelectedStock(null);
  };
  
  /**
   * Handle entering compare mode from compare banner
   */
  const handleEnterCompare = () => {
    if (canCompare) {
      setViewMode('compare');
    }
  };
  
  /**
   * Handle canceling compare mode
   */
  const handleCancelCompare = () => {
    toggleCompareMode();
    clearSelection();
  };
  
  // ============================================================================
  // Loading and Error States
  // ============================================================================
  
  if (isLoading) {
    return <LoadingState message="正在加载动能股数据..." />;
  }
  
  if (error) {
    return <ErrorMessage error={error} onRetry={refetch} />;
  }
  
  // ============================================================================
  // Render
  // ============================================================================
  
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <PageHeader
        viewMode={viewMode}
        onBack={handleBackToList}
        selectedStock={selectedStock}
        stockCount={filteredStocks.length}
      />
      
      {/* Controls Bar (only in list view) */}
      {viewMode === 'list' && (
        <ControlsBar
          industryFilter={industryFilter}
          heatFilter={heatFilter}
          isCompareMode={isCompareMode}
          onIndustryChange={setIndustryFilter}
          onHeatChange={setHeatFilter}
          onToggleCompareMode={toggleCompareMode}
          industryOptions={industryOptions}
        />
      )}
      
      {/* Compare Mode Banner (only when in compare mode in list view) */}
      {isCompareMode && viewMode === 'list' && (
        <CompareBanner
          selectedCount={selectedSymbols.length}
          maxCount={4}
          onCompare={handleEnterCompare}
          onCancel={handleCancelCompare}
        />
      )}
      
      {/* Main Content Area - Different views based on mode */}
      <div>
        {/* List View */}
        {viewMode === 'list' && (
          <StockList
            stocks={filteredStocks}
            isCompareMode={isCompareMode}
            selectedSymbols={selectedSymbols}
            onStockClick={handleStockClick}
            onToggleSelect={toggleStock}
          />
        )}
        
        {/* Detail View */}
        {viewMode === 'detail' && selectedStock && (
          <StockDetailView
            symbol={selectedStock}
            onBack={handleBackToList}
          />
        )}
        
        {/* Compare View */}
        {viewMode === 'compare' && (
          <>
            {isCompareLoading ? (
              <LoadingState message="正在加载对比数据..." />
            ) : compareData && compareData.length > 0 ? (
              <CompareTable
                stocks={compareData}
                onClose={handleBackToList}
              />
            ) : (
              <ErrorMessage 
                error={new Error('未找到对比数据')} 
                onRetry={handleBackToList}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
