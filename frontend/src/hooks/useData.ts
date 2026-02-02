// ============================================================================
// React Query Hooks for Momentum Analysis Frontend
// ============================================================================

import { useQuery, useMutation, useQueryClient, UseQueryOptions } from '@tanstack/react-query';
import type {
  Stock,
  StockDetail,
  HeatType,
  StockQueryParams,
  SectorSummary,
  PaginatedResponse,
  ETF,
  Task,
  CreateTaskInput
} from '../types';
import {
  getStocks,
  getStocksPaginated,
  getStockDetail,
  getStock,
  compareStocks,
  getStocksByHeat,
  getHeatDistribution,
  getSectors,
  getStocksBySector,
  getSectorSummary,
  getAllSectorSummaries,
  searchStocks,
  refreshStock,
  refreshAllStocks,
  checkHealth,
  getETFs,    
  getETF,      
  refreshETF,
  getTasks,
  createTask,
  deleteTask,  
} from '../services/api';

// ----------------------------------------------------------------------------
// Query Keys Factory
// ----------------------------------------------------------------------------
export const queryKeys = {
  all: ['stocks'] as const,
  lists: () => [...queryKeys.all, 'list'] as const,
  list: (params?: StockQueryParams) => [...queryKeys.lists(), params] as const,
  details: () => [...queryKeys.all, 'detail'] as const,
  detail: (symbol: string) => [...queryKeys.details(), symbol] as const,
  compare: (symbols: string[]) => ['stock-compare', symbols.sort().join(',')] as const,
  byHeat: (heatType: HeatType | null, sector?: string) => 
    ['stocks-by-heat', heatType, sector] as const,
  heatDistribution: () => ['heat-distribution'] as const,
  sectors: {
    all: ['sectors'] as const,
    list: () => [...queryKeys.sectors.all, 'list'] as const,
    stocks: (sector: string) => [...queryKeys.sectors.all, sector, 'stocks'] as const,
    summary: (sector: string) => [...queryKeys.sectors.all, sector, 'summary'] as const,
    summaries: () => [...queryKeys.sectors.all, 'summaries'] as const,
  },
  search: (query: string) => ['search', query] as const,
  health: () => ['health'] as const,
};

// ----------------------------------------------------------------------------
// Stock List Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to fetch all stocks with optional filtering
 */
export function useStocks(params?: StockQueryParams) {
  return useQuery({
    queryKey: queryKeys.list(params),
    queryFn: () => getStocks(params),
    staleTime: 30000, // 30 seconds
    gcTime: 300000, // 5 minutes (formerly cacheTime)
  });
}

/**
 * Hook to fetch paginated stocks
 */
export function useStocksPaginated(params?: StockQueryParams) {
  return useQuery({
    queryKey: ['stocks-paginated', params],
    queryFn: () => getStocksPaginated(params),
    staleTime: 30000,
    gcTime: 300000,
    placeholderData: (previousData) => previousData, // Keep previous data while loading
  });
}

// ----------------------------------------------------------------------------
// Stock Detail Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to fetch detailed stock information including score breakdown
 * @param symbol - Stock symbol to fetch (null to disable)
 */
export function useStockDetail(symbol: string | null) {
  return useQuery({
    queryKey: queryKeys.detail(symbol || ''),
    queryFn: () => (symbol ? getStockDetail(symbol) : null),
    enabled: !!symbol && symbol.trim() !== '',
    staleTime: 30000,
    gcTime: 300000,
  });
}

/**
 * Hook to fetch basic stock information
 */
export function useStock(symbol: string | null) {
  return useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => (symbol ? getStock(symbol) : null),
    enabled: !!symbol && symbol.trim() !== '',
    staleTime: 30000,
  });
}

// ----------------------------------------------------------------------------
// Stock Comparison Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to compare multiple stocks side by side
 * @param symbols - Array of stock symbols to compare (minimum 2)
 */
export function useStockCompare(symbols: string[]) {
  const validSymbols = symbols.filter(s => s && s.trim() !== '');
  
  return useQuery({
    queryKey: queryKeys.compare(validSymbols),
    queryFn: () => compareStocks(validSymbols),
    enabled: validSymbols.length >= 2,
    staleTime: 30000,
    gcTime: 300000,
  });
}

// ----------------------------------------------------------------------------
// Heat Filter Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to fetch stocks filtered by heat type
 * @param heatType - Heat type to filter by (null to disable)
 * @param sector - Optional sector filter
 */
export function useStocksByHeat(
  heatType: HeatType | null,
  sector?: string,
  options?: Omit<UseQueryOptions<Stock[]>, 'queryKey' | 'queryFn'>
) {
  return useQuery({
    queryKey: queryKeys.byHeat(heatType, sector),
    queryFn: () => (heatType ? getStocksByHeat(heatType, { sector }) : []),
    enabled: !!heatType,
    staleTime: 30000,
    gcTime: 300000,
    ...options,
  });
}

/**
 * Hook to fetch heat distribution across all stocks
 */
export function useHeatDistribution() {
  return useQuery({
    queryKey: queryKeys.heatDistribution(),
    queryFn: getHeatDistribution,
    staleTime: 60000, // 1 minute
    gcTime: 300000,
  });
}

// ----------------------------------------------------------------------------
// Sector Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to fetch all available sectors
 */
export function useSectors() {
  return useQuery({
    queryKey: queryKeys.sectors.list(),
    queryFn: getSectors,
    staleTime: 300000, // 5 minutes - sectors don't change often
    gcTime: 600000, // 10 minutes
  });
}

/**
 * Hook to fetch stocks in a specific sector
 */
export function useStocksBySector(sector: string | null) {
  return useQuery({
    queryKey: queryKeys.sectors.stocks(sector || ''),
    queryFn: () => (sector ? getStocksBySector(sector) : []),
    enabled: !!sector && sector.trim() !== '',
    staleTime: 30000,
  });
}

/**
 * Hook to fetch sector summary statistics
 */
export function useSectorSummary(sector: string | null) {
  return useQuery({
    queryKey: queryKeys.sectors.summary(sector || ''),
    queryFn: () => (sector ? getSectorSummary(sector) : null),
    enabled: !!sector && sector.trim() !== '',
    staleTime: 60000,
  });
}

/**
 * Hook to fetch all sector summaries
 */
export function useAllSectorSummaries() {
  return useQuery({
    queryKey: queryKeys.sectors.summaries(),
    queryFn: getAllSectorSummaries,
    staleTime: 60000,
    gcTime: 300000,
  });
}

// ----------------------------------------------------------------------------
// Search Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to search stocks by symbol or name
 * @param query - Search query (null or empty to disable)
 * @param limit - Maximum number of results
 */
export function useSearchStocks(query: string | null, limit = 10) {
  const trimmedQuery = query?.trim() || '';
  
  return useQuery({
    queryKey: queryKeys.search(trimmedQuery),
    queryFn: () => searchStocks(trimmedQuery, limit),
    enabled: !!trimmedQuery && trimmedQuery.length >= 1,
    staleTime: 60000,
    gcTime: 300000,
  });
}

// ----------------------------------------------------------------------------
// Mutation Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to refresh data for a specific stock
 */
export function useRefreshStock() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (symbol: string) => refreshStock(symbol),
    onSuccess: (_, symbol) => {
      // Invalidate related queries
      queryClient.invalidateQueries({ queryKey: queryKeys.detail(symbol) });
      queryClient.invalidateQueries({ queryKey: queryKeys.lists() });
    },
  });
}

/**
 * Hook to refresh all stock data
 */
export function useRefreshAllStocks() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: refreshAllStocks,
    onSuccess: () => {
      // Invalidate all stock-related queries
      queryClient.invalidateQueries({ queryKey: queryKeys.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.sectors.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.heatDistribution() });
    },
  });
}

// ----------------------------------------------------------------------------
// Health Check Hook
// ----------------------------------------------------------------------------

/**
 * Hook to check API health status
 */
export function useHealthCheck(enabled = true) {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: checkHealth,
    enabled,
    staleTime: 10000, // 10 seconds
    retry: false,
    refetchOnWindowFocus: false,
  });
}

// ----------------------------------------------------------------------------
// Combined/Derived Hooks
// ----------------------------------------------------------------------------

/**
 * Hook that combines heat type filter with additional parameters
 */
export function useFilteredStocks(filters: {
  heatType?: HeatType | null;
  sector?: string | null;
  minScore?: number;
  maxScore?: number;
}) {
  const { heatType, sector, minScore, maxScore } = filters;

  return useQuery({
    queryKey: ['filtered-stocks', filters],
    queryFn: async () => {
      let stocks: Stock[] = [];

      if (heatType) {
        stocks = await getStocksByHeat(heatType, { 
          sector: sector || undefined 
        });
      } else if (sector) {
        stocks = await getStocksBySector(sector);
      } else {
        stocks = await getStocks();
      }

      // Apply score filters client-side
      return stocks.filter(stock => {
        const score = stock.totalScore || 0;
        if (minScore !== undefined && score < minScore) return false;
        if (maxScore !== undefined && score > maxScore) return false;
        return true;
      });
    },
    enabled: true,
    staleTime: 30000,
  });
}

/**
 * Hook to get top performing stocks across different heat types
 */
export function useTopStocksByHeat(limit = 5) {
  const trend = useStocksByHeat('trend', undefined, { select: (data) => data.slice(0, limit) });
  const event = useStocksByHeat('event', undefined, { select: (data) => data.slice(0, limit) });
  const hedge = useStocksByHeat('hedge', undefined, { select: (data) => data.slice(0, limit) });

  return {
    trend,
    event,
    hedge,
    isLoading: trend.isLoading || event.isLoading || hedge.isLoading,
    isError: trend.isError || event.isError || hedge.isError,
  };
}

/**
 * Hook to prefetch stock detail (useful for hover previews)
 */
export function usePrefetchStockDetail() {
  const queryClient = useQueryClient();

  return (symbol: string) => {
    queryClient.prefetchQuery({
      queryKey: queryKeys.detail(symbol),
      queryFn: () => getStockDetail(symbol),
      staleTime: 30000,
    });
  };
}

// ----------------------------------------------------------------------------
// Utility Hooks
// ----------------------------------------------------------------------------

/**
 * Hook to manage query invalidation
 */
export function useInvalidateQueries() {
  const queryClient = useQueryClient();

  return {
    invalidateStocks: () => 
      queryClient.invalidateQueries({ queryKey: queryKeys.all }),
    invalidateSectors: () => 
      queryClient.invalidateQueries({ queryKey: queryKeys.sectors.all }),
    invalidateStock: (symbol: string) => 
      queryClient.invalidateQueries({ queryKey: queryKeys.detail(symbol) }),
    invalidateAll: () => 
      queryClient.invalidateQueries(),
  };
}

// ----------------------------------------------------------------------------
// ETF Hooks
// ----------------------------------------------------------------------------

export const etfQueryKeys = {
  all: ['etfs'] as const,
  lists: () => [...etfQueryKeys.all, 'list'] as const,
  list: (type: 'sector' | 'industry') => [...etfQueryKeys.lists(), type] as const,
  detail: (symbol: string) => [...etfQueryKeys.all, 'detail', symbol] as const,
};

/**
 * Hook to fetch ETFs by type (sector or industry)
 */
export function useETFs(type: 'sector' | 'industry') {
  return useQuery({
    queryKey: etfQueryKeys.list(type),
    queryFn: () => getETFs(type),
    staleTime: 60000, // 1 minute
    gcTime: 300000, // 5 minutes
  });
}

/**
 * Hook to fetch single ETF details
 */
export function useETF(symbol: string | null) {
  return useQuery({
    queryKey: etfQueryKeys.detail(symbol || ''),
    queryFn: () => (symbol ? getETF(symbol) : null),
    enabled: !!symbol && symbol.trim() !== '',
    staleTime: 60000,
    gcTime: 300000,
  });
}

/**
 * Hook to refresh ETF data
 */
export function useRefreshETF() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (symbol: string) => refreshETF(symbol),
    onSuccess: (_, symbol) => {
      queryClient.invalidateQueries({ queryKey: etfQueryKeys.detail(symbol) });
      queryClient.invalidateQueries({ queryKey: etfQueryKeys.lists() });
    },
  });
}

// ----------------------------------------------------------------------------
// Task Hooks
// ----------------------------------------------------------------------------

export const taskQueryKeys = {
  all: ['tasks'] as const,
  lists: () => [...taskQueryKeys.all, 'list'] as const,
  detail: (id: string) => [...taskQueryKeys.all, 'detail', id] as const,
};

/**
 * Hook to fetch all tasks
 */
export function useTasks() {
  return useQuery({
    queryKey: taskQueryKeys.lists(),
    queryFn: getTasks,
    staleTime: 60000, // 1 minute
    gcTime: 300000, // 5 minutes
  });
}

/**
 * Hook to create a new task
 */
export function useCreateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateTaskInput) => createTask(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskQueryKeys.lists() });
    },
  });
}

/**
 * Hook to delete a task
 */
export function useDeleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskQueryKeys.lists() });
    },
  });
}