// ============================================================================
// API Service Layer for Momentum Analysis Frontend
// ============================================================================

import type {
  Stock,
  StockDetail,
  HeatType,
  StockQueryParams,
  ApiResponse,
  PaginatedResponse,
  SectorSummary,
  CompareData,
  ETF,
  Task, 
  CreateTaskInput
} from '../types';

// ----------------------------------------------------------------------------
// Configuration
// ----------------------------------------------------------------------------
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
const DEFAULT_TIMEOUT = 30000; // 30 seconds

// ----------------------------------------------------------------------------
// Error Classes
// ----------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public code?: string,
    public details?: Record<string, unknown>
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

export class TimeoutError extends Error {
  constructor(message: string = 'Request timeout') {
    super(message);
    this.name = 'TimeoutError';
  }
}

// ----------------------------------------------------------------------------
// Core Fetch Utility
// ----------------------------------------------------------------------------
interface FetchOptions extends RequestInit {
  timeout?: number;
}

async function fetchApi<T>(
  endpoint: string,
  options: FetchOptions = {}
): Promise<T> {
  const { timeout = DEFAULT_TIMEOUT, ...fetchOptions } = options;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  const url = `${API_BASE_URL}${endpoint}`;

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers: {
        'Content-Type': 'application/json',
        ...fetchOptions.headers,
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      let errorDetails;

      try {
        const errorData = await response.json();
        errorMessage = errorData.message || errorMessage;
        errorDetails = errorData.details;
      } catch {
        // If error response is not JSON, use default message
      }

      throw new ApiError(
        errorMessage,
        response.status,
        response.status.toString(),
        errorDetails
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        throw new TimeoutError();
      }
      throw new NetworkError(error.message);
    }

    throw new Error('An unknown error occurred');
  }
}

// ----------------------------------------------------------------------------
// Stock List APIs
// ----------------------------------------------------------------------------

/**
 * Get all stocks with optional filtering and pagination
 */
export async function getStocks(params?: StockQueryParams): Promise<Stock[]> {
  const queryParams = new URLSearchParams();

  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        queryParams.append(key, value.toString());
      }
    });
  }

  const query = queryParams.toString();
  return fetchApi<Stock[]>(`/stocks${query ? `?${query}` : ''}`);
}

/**
 * Get paginated stocks
 */
export async function getStocksPaginated(
  params?: StockQueryParams
): Promise<PaginatedResponse<Stock>> {
  const queryParams = new URLSearchParams();

  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        queryParams.append(key, value.toString());
      }
    });
  }

  const query = queryParams.toString();
  return fetchApi<PaginatedResponse<Stock>>(`/stocks/paginated${query ? `?${query}` : ''}`);
}
function transformStockDetailResponse(data: any): StockDetail {
  const metrics = data.metrics || {};
  const scores = data.scores || {};
  const detail = data.detail || {};
  const scoresBreakdown = detail.scoresBreakdown || {};
  
  return {
    // 基础信息
    symbol: data.symbol,
    name: data.name,
    sector: data.sector,
    industry: data.industry,
    
    // 价格数据
    price: data.price,
    change: metrics.change,
    changePercent: metrics.changePercent,
    
    // 技术指标
    sma20: metrics.sma20,
    sma50: metrics.sma50,
    sma200: metrics.sma200,
    rsi: metrics.rsi,
    
    // 动量指标
    return20d: metrics.return20d,
    return63d: metrics.return63d,
    rs20d: metrics.relativeStrength,
    
    // 成交量指标
    volume: metrics.volume,
    avgVolume: metrics.avgVolume,
    volumeRatio: metrics.volumeRatio,
    
    // 期权指标
    impliedVolatility: metrics.impliedVolatility || metrics.iv30,
    ivr: metrics.ivr,
    openInterest: metrics.openInterest,
    
    // 综合评分
    totalScore: data.scoreTotal,
    momentumScore: scores.momentum,
    technicalScore: scores.trend,
    volumeScore: scores.volume,
    optionsScore: scores.options,
    
    // 热度分析
    heatType: data.heatType,
    heatScore: data.heatScore,
    riskScore: data.riskScore,
    thresholdsPass: data.thresholdsPass,
    thresholds: data.thresholds,
    
    // 市值
    marketCap: metrics.marketCap,
    
    // 评分细分
    scoreBreakdown: {
      momentum: {
        score: scoresBreakdown.momentum?.score || scores.momentum || 0,
        data: {
          return_20d: scoresBreakdown.momentum?.components?.return20d || metrics.return20d || 0,
          return_63d: scoresBreakdown.momentum?.components?.return63d || metrics.return63d || 0,
          rs_20d: scoresBreakdown.momentum?.components?.relativeStrength || metrics.relativeStrength,
          score_breakdown: scoresBreakdown.momentum?.components || {},
        },
      },
      technical: {
        score: scoresBreakdown.trend?.score || scores.trend || 0,
        data: {
          price: data.price || 0,
          sma20: scoresBreakdown.trend?.components?.sma20 || metrics.sma20 || 0,
          sma50: scoresBreakdown.trend?.components?.sma50 || metrics.sma50 || 0,
          sma200: scoresBreakdown.trend?.components?.sma200 || metrics.sma200 || null,
          rsi: metrics.rsi || 0,
          dist_from_52w_high: scoresBreakdown.trend?.components?.distanceToHigh20d || metrics.distanceToHigh20d || 0,
          score_breakdown: scoresBreakdown.trend?.components || {},
        },
      },
      volume: {
        score: scoresBreakdown.volume?.score || scores.volume || 0,
        data: {
          volume: scoresBreakdown.volume?.components?.volumeMultiple || metrics.volume || 0,
          avg_volume: metrics.avgVolume || 0,
          volume_ratio: scoresBreakdown.volume?.components?.volumeRatio || metrics.volumeRatio || 0,
        },
      },
      options: {
        score: scoresBreakdown.options?.score || scores.options || 0,
        data: {
          heat_type: detail.heatAnalysis?.type || data.heatType || 'normal',
          heat_score: detail.heatAnalysis?.score || data.heatScore || 0,
          risk_score: detail.heatAnalysis?.riskScore || data.riskScore || 0,
          ivr: scoresBreakdown.options?.components?.ivr || metrics.ivr,
          implied_volatility: scoresBreakdown.options?.components?.iv30 || metrics.iv30 || metrics.impliedVolatility,
          open_interest: metrics.openInterest,
        },
      },
    },
  };
}
// ----------------------------------------------------------------------------
// Stock Detail APIs
// ----------------------------------------------------------------------------

/**
 * Get detailed information for a specific stock including score breakdown
 */
export async function getStockDetail(symbol: string): Promise<StockDetail> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  // 修复：后端路由是 /stocks/symbol/{symbol}/detail
  const response = await fetchApi<any>(`/stocks/symbol/${symbol.toUpperCase()}/detail`);
  
  // 数据转换：将后端格式转换为前端期望的 StockDetail 格式
  return transformStockDetailResponse(response);
}

/**
 * Get basic stock information
 */
export async function getStock(symbol: string): Promise<Stock> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  // 修复：后端路由是 /stocks/symbol/{symbol}
  return fetchApi<Stock>(`/stocks/symbol/${symbol.toUpperCase()}`);
}

// ----------------------------------------------------------------------------
// Stock Comparison APIs
// ----------------------------------------------------------------------------

/**
 * Compare multiple stocks side by side
 * @param symbols - Array of stock symbols (minimum 2, maximum 10)
 */
export async function compareStocks(symbols: string[]): Promise<StockDetail[]> {
  if (!symbols || symbols.length < 2) {
    throw new Error('At least 2 stock symbols are required for comparison');
  }

  if (symbols.length > 10) {
    throw new Error('Cannot compare more than 10 stocks at once');
  }

  // Ensure all symbols are uppercase and trimmed
  const cleanedSymbols = symbols.map(s => s.trim().toUpperCase()).filter(s => s !== '');

  return fetchApi<StockDetail[]>('/stocks/compare', {
    method: 'POST',
    body: JSON.stringify(cleanedSymbols),
  });
}

/**
 * Get comparison data with selected metrics
 */
export async function getCompareData(
  symbols: string[],
  metrics?: string[]
): Promise<CompareData> {
  const stocks = await compareStocks(symbols);
  
  const defaultMetrics = [
    'totalScore',
    'heatScore',
    'riskScore',
    'return20d',
    'return63d',
    'rsi',
    'volumeRatio',
  ];

  return {
    stocks,
    metrics: metrics || defaultMetrics,
  };
}

// ----------------------------------------------------------------------------
// Heat Type Filter APIs
// ----------------------------------------------------------------------------

/**
 * Get stocks filtered by heat type
 * @param heatType - The type of heat to filter by
 * @param params - Optional additional filters (sector, limit)
 */
export async function getStocksByHeat(
  heatType: HeatType,
  params?: { sector?: string; limit?: number }
): Promise<Stock[]> {
  if (!heatType) {
    throw new Error('Heat type is required');
  }

  const queryParams = new URLSearchParams();
  
  if (params?.sector) {
    queryParams.append('sector', params.sector);
  }
  
  if (params?.limit) {
    queryParams.append('limit', params.limit.toString());
  }

  const query = queryParams.toString();
  return fetchApi<Stock[]>(
    `/stocks/by-heat/${heatType}${query ? `?${query}` : ''}`
  );
}

/**
 * Get heat distribution across all stocks
 */
export async function getHeatDistribution(): Promise<Record<HeatType, number>> {
  return fetchApi<Record<HeatType, number>>('/stocks/heat-distribution');
}

// ----------------------------------------------------------------------------
// Sector APIs
// ----------------------------------------------------------------------------

/**
 * Get list of all sectors
 */
export async function getSectors(): Promise<string[]> {
  return fetchApi<string[]>('/sectors');
}

/**
 * Get stocks by sector
 */
export async function getStocksBySector(sector: string): Promise<Stock[]> {
  if (!sector || sector.trim() === '') {
    throw new Error('Sector name is required');
  }
  return fetchApi<Stock[]>(`/sectors/${encodeURIComponent(sector)}/stocks`);
}

/**
 * Get sector summary with statistics
 */
export async function getSectorSummary(sector: string): Promise<SectorSummary> {
  if (!sector || sector.trim() === '') {
    throw new Error('Sector name is required');
  }
  return fetchApi<SectorSummary>(`/sectors/${encodeURIComponent(sector)}/summary`);
}

/**
 * Get all sector summaries
 */
export async function getAllSectorSummaries(): Promise<SectorSummary[]> {
  return fetchApi<SectorSummary[]>('/sectors/summaries');
}

// ----------------------------------------------------------------------------
// Search APIs
// ----------------------------------------------------------------------------

/**
 * Search stocks by symbol or name
 */
export async function searchStocks(query: string, limit = 10): Promise<Stock[]> {
  if (!query || query.trim() === '') {
    return [];
  }

  const queryParams = new URLSearchParams({
    q: query.trim(),
    limit: limit.toString(),
  });

  return fetchApi<Stock[]>(`/stocks/search?${queryParams.toString()}`);
}

// ----------------------------------------------------------------------------
// Refresh APIs
// ----------------------------------------------------------------------------

/**
 * Trigger data refresh for a specific stock
 */
export async function refreshStock(symbol: string): Promise<{ success: boolean; message: string }> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  return fetchApi<{ success: boolean; message: string }>(
    `/stocks/${symbol.toUpperCase()}/refresh`,
    { method: 'POST' }
  );
}

/**
 * Trigger full data refresh for all stocks
 */
export async function refreshAllStocks(): Promise<{ success: boolean; message: string }> {
  return fetchApi<{ success: boolean; message: string }>(
    '/stocks/refresh-all',
    { method: 'POST' }
  );
}

// ----------------------------------------------------------------------------
// Health Check API
// ----------------------------------------------------------------------------

/**
 * Check API health status
 */
export async function checkHealth(): Promise<{ status: string; timestamp: string }> {
  return fetchApi<{ status: string; timestamp: string }>('/health');
}

// ----------------------------------------------------------------------------
// Utility Functions
// ----------------------------------------------------------------------------

/**
 * Build query string from parameters object
 */
export function buildQueryString(params: Record<string, unknown>): string {
  const queryParams = new URLSearchParams();
  
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      if (Array.isArray(value)) {
        value.forEach(v => queryParams.append(key, v.toString()));
      } else {
        queryParams.append(key, value.toString());
      }
    }
  });

  return queryParams.toString();
}

/**
 * Validate stock symbol format
 */
export function isValidSymbol(symbol: string): boolean {
  return /^[A-Z]{1,5}$/.test(symbol.toUpperCase());
}

/**
 * Get ETFs by type (sector or industry)
 * @param type - ETF type: 'sector' or 'industry'
 * @param includeHoldings - Whether to include holdings data (default: true for sector/industry overview)
 */
export async function getETFs(type: 'sector' | 'industry', includeHoldings = true): Promise<ETF[]> {
  const query = `type=${type}&include_holdings=${includeHoldings}`;
  return fetchApi<ETF[]>(`/etfs?${query}`);
}

/**
 * Get single ETF details
 */
export async function getETF(symbol: string): Promise<ETF> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  return fetchApi<ETF>(`/etfs/${symbol.toUpperCase()}`);
}

/**
 * Refresh ETF data
 */
export async function refreshETF(symbol: string): Promise<{ success: boolean; message: string }> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  return fetchApi<{ success: boolean; message: string }>(
    `/etfs/${symbol.toUpperCase()}/refresh`,
    { method: 'POST' }
  );
}


/**
 * Get all tasks
 */
export async function getTasks(): Promise<Task[]> {
  return fetchApi<Task[]>('/tasks');
}

/**
 * Get single task by ID
 */
export async function getTask(id: string): Promise<Task> {
  if (!id || id.trim() === '') {
    throw new Error('Task ID is required');
  }
  return fetchApi<Task>(`/tasks/${id}`);
}

/**
 * Create a new task
 */
export async function createTask(input: CreateTaskInput): Promise<Task> {
  return fetchApi<Task>('/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

/**
 * Delete a task
 */
export async function deleteTask(id: string): Promise<{ success: boolean; message: string }> {
  if (!id || id.trim() === '') {
    throw new Error('Task ID is required');
  }
  return fetchApi<{ success: boolean; message: string }>(`/tasks/${id}`, {
    method: 'DELETE',
  });
}

/**
 * Get ETF by symbol (alias for getETF with optional includeHoldings)
 */
export async function getETFBySymbol(symbol: string, includeHoldings = false): Promise<ETF> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  const query = includeHoldings ? '?include_holdings=true' : '';
  return fetchApi<ETF>(`/etfs/symbol/${symbol.toUpperCase()}${query}`);
}

/**
 * Get ETF score snapshots for multiple symbols
 */
export async function getEtfScoreSnapshots(symbols: string[]): Promise<Array<{
  symbol: string;
  date?: string;
  total_score?: number;
  thresholds_pass?: boolean;
  score_breakdown?: Record<string, number>;
}>> {
  if (!symbols || symbols.length === 0) {
    return [];
  }
  const cleanedSymbols = symbols.map(s => s.trim().toUpperCase()).filter(s => s !== '');
  return fetchApi<Array<{
    symbol: string;
    date?: string;
    total_score?: number;
    thresholds_pass?: boolean;
    score_breakdown?: Record<string, number>;
  }>>(`/etfs/score-snapshots?symbols=${cleanedSymbols.join(',')}`);
}

/**
 * Get task by ID
 */
export async function getTaskById(id: string | number): Promise<Task> {
  if (!id) {
    throw new Error('Task ID is required');
  }
  return fetchApi<Task>(`/tasks/${id}`);
}

/**
 * Refresh all ETFs for a task
 */
export async function refreshTaskAllETFs(taskId: string | number): Promise<{
  status: string;
  task_id: number;
  total: number;
  completed: number;
  failed: number;
  results: Array<{
    symbol: string;
    status: string;
    score?: number;
    completeness?: number;
    message?: string;
  }>;
  message: string;
}> {
  if (!taskId) {
    throw new Error('Task ID is required');
  }
  return fetchApi(`/tasks/${taskId}/refresh-all-etfs`, {
    method: 'POST',
    timeout: 180000,
  });
}

/**
 * Refresh holdings by coverage range
 */
export async function refreshHoldingsByCoverage(
  symbol: string,
  coverageType: string,
  coverageValue: number
): Promise<{
  status: string;
  symbol: string;
  coverage: string;
  stocks_count: number;
  total_weight: number;
  completeness: Record<string, unknown>;
  updated_stocks: Array<Record<string, unknown>>;
  message: string;
}> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  return fetchApi(`/etfs/symbol/${symbol.toUpperCase()}/refresh-holdings-by-coverage`, {
    method: 'POST',
    timeout: 180000,
    body: JSON.stringify({
      coverage_type: coverageType,
      coverage_value: coverageValue,
    }),
  });
}

/**
 * Import Finviz data for an ETF
 */
export async function importFinvizData(
  etfSymbol: string,
  coverage: string,
  data: Array<Record<string, unknown>>
): Promise<{
  status: string;
  etf_symbol: string;
  coverage: string;
  records_imported: number;
  breadth_metrics: Record<string, unknown>;
  validation: Record<string, unknown>;
}> {
  return fetchApi('/import/finviz', {
    method: 'POST',
    body: JSON.stringify({
      etf_symbol: etfSymbol.toUpperCase(),
      coverage,
      data,
    }),
  });
}

/**
 * Import MarketChameleon data
 */
export async function importMCData(
  data: Array<Record<string, unknown>>
): Promise<{
  status: string;
  records_imported: number;
  heat_distribution: Record<string, number>;
  data?: Array<Record<string, unknown>>;
}> {
  return fetchApi('/import/marketchameleon', {
    method: 'POST',
    body: JSON.stringify({
      data,
    }),
  });
}
export async function getETFHoldingsBySymbol(symbol: string): Promise<Array<{
  ticker: string;
  weight: number;
  dataDate?: string;
}>> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  return fetchApi<Array<{
    ticker: string;
    weight: number;
    dataDate?: string;
  }>>(`/etfs/symbol/${symbol.toUpperCase()}/holdings`);
}

// ----------------------------------------------------------------------------
// Market APIs
// ----------------------------------------------------------------------------

export interface MarketRegimeResponse {
  status: string;
  regime_text?: string;
  spy?: {
    price: number;
    sma20: number;
    sma50: number;
    dist_to_sma20?: number | null;
    dist_to_sma50?: number | null;
    return_20d: number;
    sma20_slope: number;
  };
  vix?: number | null;
  indicators?: {
    price_above_sma20?: boolean;
    price_above_sma50?: boolean;
    sma20_slope?: number;
    sma20_slope_positive?: boolean;
    sma20_above_sma50?: boolean;
    return_20d?: number;
    dist_to_sma20?: number | null;
    dist_to_sma50?: number | null;
    near_sma50?: boolean | null;
  };
  error?: string;
}

/**
 * Get market regime (Regime Gate)
 */
export async function getMarketRegime(
  refresh = false
): Promise<MarketRegimeResponse> {
  const query = refresh ? '?refresh=true' : '';
  return fetchApi<MarketRegimeResponse>(`/market/regime${query}`);
}

// ----------------------------------------------------------------------------
// Options Data APIs
// ----------------------------------------------------------------------------

/**
 * Options positioning data for a stock
 */
export interface OptionsPositioningData {
  bucket: string;        // 期限桶: "0-7天", "8-30天", "31-90天"
  callOI: number;        // Call Open Interest 变化
  putOI: number;         // Put Open Interest 变化
  netOI: number;         // 净持仓变化
  trend: string;         // 趋势描述
}

/**
 * Full options overlay data response
 */
export interface OptionsOverlayData {
  symbol: string;
  // Heat metrics
  heatScore: number;
  heatType: string;
  relativeNominal: number | null;    // 相对名义成交
  relativeVolume: number | null;     // 相对成交量
  tradeCount: string;                // 交易笔数等级: "高", "中", "低"
  
  // Risk pricing metrics
  riskScore: number;
  ivr: number | null;
  iv30: number | null;
  iv30Change: number | null;
  
  // Term structure metrics
  termStructureScore: number;
  slope: number | null;
  slopeChange: number | null;
  earningsEvent: string | null;      // 财报事件日期
  
  // Positioning data
  positioning: OptionsPositioningData[];
  
  // Metadata
  dataSource: string;
  updatedAt: string | null;
}

/**
 * Get options overlay data for a stock
 * This fetches real-time options data from the backend
 */
export async function getOptionsOverlayData(symbol: string): Promise<OptionsOverlayData> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  return fetchApi<OptionsOverlayData>(`/stocks/symbol/${symbol.toUpperCase()}/options-overlay`);
}
