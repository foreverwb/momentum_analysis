import React, { useState, useMemo, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { HeatType, Stock } from '../types';
import { useStocks, useStockCompare } from '../hooks/useData';
import { useCompareMode } from '../hooks/useCompareMode';
import { getMarketSymbolSnapshot } from '../services/api';
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
type DmaFilterOption = 'none' | 'above_spy' | 'above_qqq';
type DmaBenchmark = 'SPY' | 'QQQ';
const ETF_SYMBOL_PATTERN = /^[A-Z0-9][A-Z0-9.\-]{0,9}$/;

function normalizeEtfSymbol(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const normalized = raw.trim().toUpperCase();
  if (!normalized) return null;
  if (!ETF_SYMBOL_PATTERN.test(normalized)) return null;
  return normalized;
}

function normalizeStockSymbol(raw: unknown): string | null {
  return normalizeEtfSymbol(raw);
}

function encodeSymbolForRoute(symbol: string): string {
  return encodeURIComponent(symbol).replace(/\./g, '%2E');
}

function buildMomentumDetailRoute(symbol: string): string {
  return `/momentum/${encodeSymbolForRoute(symbol)}`;
}

function collectStockEtfSymbols(stock: Stock): string[] {
  const symbols = new Set<string>();
  const add = (value: unknown) => {
    const normalized = normalizeEtfSymbol(value);
    if (normalized) {
      symbols.add(normalized);
    }
  };

  (stock.sectorEtfs || []).forEach(add);
  (stock.industryEtfs || []).forEach(add);
  (stock.comparisons || []).forEach((item) => {
    if (item.type === 'sector' || item.type === 'industry') {
      add(item.symbol);
    }
  });

  // Backward-compatible fallback when API does not return sectorEtfs/industryEtfs.
  add(stock.sector);
  add(stock.industry);

  return Array.from(symbols).sort((a, b) => a.localeCompare(b));
}

function resolveBelow20DMA(snapshot?: {
  price?: number;
  sma20?: number;
  dist_to_sma20?: number | null;
} | null): boolean | null {
  if (!snapshot) return null;
  if (typeof snapshot.dist_to_sma20 === 'number' && Number.isFinite(snapshot.dist_to_sma20)) {
    return snapshot.dist_to_sma20 < 0;
  }
  if (
    typeof snapshot.price === 'number' &&
    Number.isFinite(snapshot.price) &&
    typeof snapshot.sma20 === 'number' &&
    Number.isFinite(snapshot.sma20) &&
    snapshot.sma20 !== 0
  ) {
    return snapshot.price < snapshot.sma20;
  }
  return null;
}

function isStockAbove20DMA(stock: Stock): boolean {
  const deviation = stock.metrics?.deviationFrom20ma;
  if (typeof deviation === 'number' && Number.isFinite(deviation)) {
    return deviation > 0;
  }
  if (
    typeof stock.price === 'number' &&
    Number.isFinite(stock.price) &&
    typeof stock.sma20 === 'number' &&
    Number.isFinite(stock.sma20) &&
    stock.sma20 !== 0
  ) {
    return stock.price > stock.sma20;
  }
  return false;
}

/**
 * MomentumPool Component
 * 
 * Main page for analyzing momentum stocks with multiple view modes:
 * - List view: Browse all stocks with filtering
 * - Detail view: Deep dive into a single stock
 * - Compare view: Side-by-side comparison of selected stocks
 * 
 * Features:
 * - ETF filtering
 * - Heat type filtering
 * - Compare mode with multi-selection
 * - Seamless view transitions
 */
export function MomentumPool() {
  const navigate = useNavigate();
  const { symbol: routeSymbol } = useParams<{ symbol?: string }>();

  // ============================================================================
  // State Management
  // ============================================================================
  
  // View mode control
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const selectedStock = useMemo(
    () => normalizeStockSymbol(routeSymbol),
    [routeSymbol]
  );
  const effectiveViewMode: ViewMode = selectedStock ? 'detail' : viewMode;
  
  // Filter states
  const [industryFilter, setIndustryFilter] = useState('all');
  const [heatFilter, setHeatFilter] = useState<HeatType | 'all'>('all');
  const [dmaFilter, setDmaFilter] = useState<DmaFilterOption>('none');
  const [dmaBenchmarkBelow20, setDmaBenchmarkBelow20] = useState<Record<DmaBenchmark, boolean | null>>({
    SPY: null,
    QQQ: null,
  });
  
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
    effectiveViewMode === 'compare' ? selectedSymbols : []
  );

  useEffect(() => {
    if (!routeSymbol) return;
    const normalized = normalizeStockSymbol(routeSymbol);
    if (!normalized) {
      navigate('/momentum', { replace: true });
      return;
    }
    if (normalized !== routeSymbol) {
      navigate(buildMomentumDetailRoute(normalized), { replace: true });
    }
  }, [routeSymbol, navigate]);

  useEffect(() => {
    let cancelled = false;

    const loadBenchmarks = async () => {
      try {
        const [spySnapshot, qqqSnapshot] = await Promise.all([
          getMarketSymbolSnapshot('SPY'),
          getMarketSymbolSnapshot('QQQ'),
        ]);
        if (cancelled) return;
        setDmaBenchmarkBelow20({
          SPY: resolveBelow20DMA(spySnapshot),
          QQQ: resolveBelow20DMA(qqqSnapshot),
        });
      } catch {
        if (cancelled) return;
        setDmaBenchmarkBelow20({ SPY: null, QQQ: null });
      }
    };

    void loadBenchmarks();

    return () => {
      cancelled = true;
    };
  }, []);
  
  // ============================================================================
  // Filter Logic
  // ============================================================================
  
  const stockEtfSymbolsMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const stock of stocks || []) {
      map.set(stock.symbol, collectStockEtfSymbols(stock));
    }
    return map;
  }, [stocks]);

  // Build ETF filter options from scored holdings (sector + industry ETF symbols).
  const industryOptions = useMemo(() => {
    const etfSymbols = new Set<string>();
    for (const symbols of stockEtfSymbolsMap.values()) {
      for (const symbol of symbols) {
        etfSymbols.add(symbol);
      }
    }

    return [
      { value: 'all', label: '全部ETF' },
      ...Array.from(etfSymbols)
        .sort((a, b) => a.localeCompare(b))
        .map((symbol) => ({ value: symbol, label: symbol })),
    ];
  }, [stockEtfSymbolsMap]);

  useEffect(() => {
    const hasOption = industryOptions.some((option) => option.value === industryFilter);
    if (!hasOption) {
      setIndustryFilter('all');
    }
  }, [industryFilter, industryOptions]);
  
  // Apply filters to stocks
  const selectedDmaBenchmark: DmaBenchmark = dmaFilter === 'above_qqq' ? 'QQQ' : 'SPY';
  const shouldApplyDmaFilter =
    dmaFilter !== 'none' && dmaBenchmarkBelow20[selectedDmaBenchmark] === true;
  const dmaStatusText = useMemo(() => {
    if (dmaFilter === 'none') {
      return '';
    }
    const below20 = dmaBenchmarkBelow20[selectedDmaBenchmark];
    if (below20 === null) {
      return `${selectedDmaBenchmark} 20DMA状态未知`;
    }
    if (below20) {
      return `${selectedDmaBenchmark} < 20DMA，已触发过滤`;
    }
    return `${selectedDmaBenchmark} >= 20DMA，未触发过滤`;
  }, [dmaFilter, dmaBenchmarkBelow20, selectedDmaBenchmark]);

  const filteredStocks = useMemo(() => {
    if (!stocks) return [];
    
    return stocks.filter(stock => {
      // ETF filter
      if (industryFilter !== 'all') {
        const relatedEtfSymbols = stockEtfSymbolsMap.get(stock.symbol) || [];
        if (!relatedEtfSymbols.includes(industryFilter)) {
          return false;
        }
      }

      // Heat filter
      if (heatFilter !== 'all' && stock.heatType !== heatFilter) {
        return false;
      }

      // 20DMA filter:
      // Only apply when selected benchmark is below its own 20DMA.
      if (shouldApplyDmaFilter && !isStockAbove20DMA(stock)) {
        return false;
      }
      
      return true;
    });
  }, [stocks, industryFilter, heatFilter, shouldApplyDmaFilter, stockEtfSymbolsMap]);
  
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
      const normalized = normalizeStockSymbol(symbol);
      if (!normalized) return;
      navigate(buildMomentumDetailRoute(normalized));
    }
  };
  
  /**
   * Handle back navigation from detail/compare to list view
   */
  const handleBackToList = () => {
    if (selectedStock) {
      navigate('/momentum');
      return;
    }
    setViewMode('list');
  };
  
  /**
   * Handle entering compare mode from compare banner
   */
  const handleEnterCompare = () => {
    if (canCompare) {
      if (selectedStock) {
        navigate('/momentum');
      }
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
        viewMode={effectiveViewMode}
        onBack={handleBackToList}
        selectedStock={selectedStock}
        stockCount={filteredStocks.length}
      />
      
      {/* Controls Bar (only in list view) */}
      {effectiveViewMode === 'list' && (
        <ControlsBar
          industryFilter={industryFilter}
          heatFilter={heatFilter}
          dmaFilter={dmaFilter}
          dmaStatusText={dmaStatusText}
          isCompareMode={isCompareMode}
          onIndustryChange={setIndustryFilter}
          onHeatChange={setHeatFilter}
          onDmaChange={setDmaFilter}
          onToggleCompareMode={toggleCompareMode}
          industryOptions={industryOptions}
        />
      )}
      
      {/* Compare Mode Banner (only when in compare mode in list view) */}
      {isCompareMode && effectiveViewMode === 'list' && (
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
        {effectiveViewMode === 'list' && (
          <StockList
            stocks={filteredStocks}
            isCompareMode={isCompareMode}
            selectedSymbols={selectedSymbols}
            onStockClick={handleStockClick}
            onToggleSelect={toggleStock}
          />
        )}
        
        {/* Detail View */}
        {effectiveViewMode === 'detail' && selectedStock && (
          <StockDetailView
            symbol={selectedStock}
            onBack={handleBackToList}
          />
        )}
        
        {/* Compare View */}
        {effectiveViewMode === 'compare' && (
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
