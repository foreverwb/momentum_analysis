import type { Stock, ETF, Task, RefreshResult } from '../types';
import type { RefreshBreakdown } from '../types';

const API_BASE = '/api';

// Helper function for API calls
async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });
  
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API Error: ${response.status} - ${errorText}`);
  }
  
  return response.json();
}

// Stock APIs
export async function getStocks(params?: { 
  industry?: string; 
  sector?: string;
  minScore?: number;
  limit?: number;
}): Promise<Stock[]> {
  const queryParams = new URLSearchParams();
  if (params?.industry) queryParams.append('industry', params.industry);
  if (params?.sector) queryParams.append('sector', params.sector);
  if (params?.minScore !== undefined) queryParams.append('min_score', params.minScore.toString());
  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString());
  
  const query = queryParams.toString();
  return fetchApi<Stock[]>(`/stocks${query ? `?${query}` : ''}`);
}

export async function getStockById(id: number): Promise<Stock | undefined> {
  try {
    return await fetchApi<Stock>(`/stocks/${id}`);
  } catch (error) {
    console.error('Failed to fetch stock:', error);
    return undefined;
  }
}

export async function getStockBySymbol(symbol: string): Promise<Stock | undefined> {
  try {
    return await fetchApi<Stock>(`/stocks/symbol/${symbol}`);
  } catch (error) {
    console.error('Failed to fetch stock:', error);
    return undefined;
  }
}

export async function getTopStocks(n: number = 10, sector?: string): Promise<Stock[]> {
  const query = sector ? `?sector=${sector}` : '';
  return fetchApi<Stock[]>(`/stocks/top/${n}${query}`);
}

// ETF APIs
export async function getETFs(type?: 'sector' | 'industry', includeHoldings?: boolean): Promise<ETF[]> {
  const params = new URLSearchParams();
  if (type) params.append('type', type);
  if (includeHoldings) params.append('include_holdings', 'true');
  const query = params.toString();
  return fetchApi<ETF[]>(`/etfs${query ? `?${query}` : ''}`);
}

export async function getSectorETFs(includeHoldings?: boolean): Promise<ETF[]> {
  const query = includeHoldings ? '?include_holdings=true' : '';
  return fetchApi<ETF[]>(`/etfs/sectors${query}`);
}

export async function getIndustryETFs(sector?: string, includeHoldings?: boolean): Promise<ETF[]> {
  const params = new URLSearchParams();
  if (sector) params.append('sector', sector);
  if (includeHoldings) params.append('include_holdings', 'true');
  const query = params.toString();
  return fetchApi<ETF[]>(`/etfs/industries${query ? `?${query}` : ''}`);
}

export async function getETFById(id: number, includeHoldings?: boolean): Promise<ETF | undefined> {
  try {
    const query = includeHoldings ? '?include_holdings=true' : '';
    return await fetchApi<ETF>(`/etfs/${id}${query}`);
  } catch (error) {
    console.error('Failed to fetch ETF:', error);
    return undefined;
  }
}

export async function getETFBySymbol(symbol: string, includeHoldings?: boolean): Promise<ETF | undefined> {
  try {
    const query = includeHoldings ? '?include_holdings=true' : '';
    return await fetchApi<ETF>(`/etfs/symbol/${symbol}${query}`);
  } catch (error) {
    console.error('Failed to fetch ETF:', error);
    return undefined;
  }
}

export interface EtfScoreSnapshot {
  symbol: string;
  date?: string | null;
  total_score?: number | null;
  score_breakdown?: RefreshBreakdown | null;
  thresholds_pass?: boolean | null;
}

export async function getEtfScoreSnapshots(symbols: string[]): Promise<EtfScoreSnapshot[]> {
  const params = new URLSearchParams();
  if (symbols?.length) {
    params.append('symbols', symbols.join(','));
  }
  const query = params.toString();
  return fetchApi<EtfScoreSnapshot[]>(`/etfs/score-snapshots${query ? `?${query}` : ''}`);
}

export async function getETFHoldings(etfId: number, dataDate?: string): Promise<Array<{ ticker: string; weight: number; dataDate?: string }>> {
  const query = dataDate ? `?data_date=${dataDate}` : '';
  return fetchApi(`/etfs/${etfId}/holdings${query}`);
}

export async function getETFHoldingsBySymbol(symbol: string, dataDate?: string): Promise<Array<{ ticker: string; weight: number; dataDate?: string }>> {
  const query = dataDate ? `?data_date=${dataDate}` : '';
  return fetchApi(`/etfs/symbol/${symbol}/holdings${query}`);
}

export async function getValidSectorSymbols(): Promise<string[]> {
  return fetchApi<string[]>('/etfs/valid-sectors');
}

// Task APIs
export async function getTasks(): Promise<Task[]> {
  return fetchApi<Task[]>('/tasks');
}

export async function getTaskById(id: number): Promise<Task | undefined> {
  try {
    return await fetchApi<Task>(`/tasks/${id}`);
  } catch (error) {
    console.error('Failed to fetch task:', error);
    return undefined;
  }
}

export async function createTask(task: Omit<Task, 'id' | 'createdAt'>): Promise<Task> {
  return fetchApi<Task>('/tasks', {
    method: 'POST',
    body: JSON.stringify(task),
  });
}

export async function updateTask(id: number, task: Omit<Task, 'id' | 'createdAt'>): Promise<Task> {
  return fetchApi<Task>(`/tasks/${id}`, {
    method: 'PUT',
    body: JSON.stringify(task),
  });
}

export async function deleteTask(id: number): Promise<void> {
  await fetchApi(`/tasks/${id}`, {
    method: 'DELETE',
  });
}

export interface MomentumRefreshResult {
  status: string;
  task_id: number;
  coverage?: string;
  total_candidates?: number;
  updated_count?: number;
  errors?: Array<{ symbol: string; reason: string }>;
  updated?: Array<{
    symbol: string;
    score: number;
    sector?: string;
    industry?: string;
    weight?: number;
  }>;
  message?: string;
}

export async function refreshMomentumStocks(
  taskId: number,
  params?: { coverage?: string; limit?: number }
): Promise<MomentumRefreshResult> {
  const queryParams = new URLSearchParams();
  if (params?.coverage) queryParams.append('coverage', params.coverage);
  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString());
  const query = queryParams.toString();
  return fetchApi<MomentumRefreshResult>(`/tasks/${taskId}/refresh-stocks${query ? `?${query}` : ''}`, {
    method: 'POST',
  });
}

// Holdings Import APIs
export interface HoldingsUploadResponse {
  status: string;
  etfSymbol: string;
  etfType: string;
  dataDate: string;
  recordsImported: number;
  recordsSkipped: number;
  skippedDetails?: Array<{ row: string; ticker: string; reason: string }>;
}

export async function uploadHoldingsXlsx(
  file: File,
  etfType: 'sector' | 'industry',
  etfSymbol: string,
  dataDate: string,
  parentSector?: string
): Promise<HoldingsUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('etf_type', etfType);
  formData.append('etf_symbol', etfSymbol);
  formData.append('data_date', dataDate);
  if (parentSector) {
    formData.append('parent_sector', parentSector);
  }
  
  const response = await fetch(`${API_BASE}/import/holdings/xlsx`, {
    method: 'POST',
    body: formData,
  });
  
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Upload failed: ${response.status} - ${errorText}`);
  }
  
  return response.json();
}

export async function getHoldingsUploadLogs(etfSymbol?: string, limit?: number): Promise<Array<{
  id: number;
  etfSymbol: string;
  etfType: string;
  dataDate: string;
  fileName: string;
  recordsCount: number;
  skippedCount: number;
  status: string;
  errorMessage?: string;
  createdAt: string;
}>> {
  const params = new URLSearchParams();
  if (etfSymbol) params.append('etf_symbol', etfSymbol);
  if (limit) params.append('limit', limit.toString());
  
  const query = params.toString();
  return fetchApi(`/import/holdings/logs${query ? `?${query}` : ''}`);
}

export async function getHoldingsTemplate(): Promise<{
  description: string;
  fileFormat: string;
  requiredColumns: string[];
  allColumns: string[];
  sampleData: Array<{ Name: string; Ticker: string; Weight: number }>;
  validationRules: string[];
  validSectorEtfs: string[];
  uploadCommands: { sectorEtf: string; industryEtf: string };
}> {
  return fetchApi('/import/templates/holdings');
}

// Market APIs
export async function getMarketRegime(): Promise<{
  status: string;
  regimeText?: string;
  spy?: { price: number; sma20: number; sma50: number; dist_to_sma20?: number | null; dist_to_sma50?: number | null; return_20d?: number; sma20_slope?: number };
  vix?: number;
  indicators?: { price_above_sma20: boolean; price_above_sma50: boolean; sma20_slope_positive: boolean; sma20_slope?: number; sma20_above_sma50: boolean; return_20d: number; dist_to_sma20?: number | null; dist_to_sma50?: number | null; near_sma50?: boolean };
  error?: string;
}> {
  return fetchApi('/market/regime');
}

export async function getMarketSnapshot(): Promise<{
  timestamp: string;
  broker_status: Record<string, unknown>;
  regime: Record<string, unknown>;
  spy?: Record<string, unknown>;
  vix?: number;
  sector_etf_rankings: Array<Record<string, unknown>>;
}> {
  return fetchApi('/market/snapshot');
}

export async function getETFRankings(
  type: 'sector' | 'industry' = 'sector',
  benchmark: string = 'SPY',
  topN: number = 11
): Promise<{
  type: string;
  benchmark: string;
  count: number;
  rankings: Array<{
    symbol: string;
    name?: string;
    totalScore: number;
    rank: number;
    thresholdsPass: boolean;
    type: string;
    breakdown?: Record<string, unknown>;
  }>;
}> {
  return fetchApi(`/market/etf-rankings?type=${type}&benchmark=${benchmark}&top_n=${topN}`);
}

// Health Check
export async function healthCheck(): Promise<{
  status: string;
  apiVersion: string;
  brokers?: { ibkr: boolean; futu: boolean };
}> {
  return fetchApi('/health');
}

// Refresh Holdings Data API
export async function refreshHoldingsData(symbol: string): Promise<{
  status: string;
  symbol: string;
  message: string;
  holdingsCount?: number;
}> {
  return fetchApi(`/etfs/symbol/${symbol}/refresh-holdings`, {
    method: 'POST',
  });
}

// Broker APIs
export async function getBrokerStatus(): Promise<{
  ibkr: { isConnected: boolean; lastConnectedAt?: string; lastError?: string };
  futu: { isConnected: boolean; lastConnectedAt?: string; lastError?: string };
}> {
  return fetchApi('/broker/status');
}

export async function connectIBKR(config?: { 
  host?: string; 
  port?: number; 
  client_id?: number 
}): Promise<{
  status: string;
  message: string;
}> {
  return fetchApi('/broker/ibkr/connect', {
    method: 'POST',
    body: JSON.stringify(config || {}),
  });
}

export async function disconnectIBKR(): Promise<{
  status: string;
  message: string;
}> {
  return fetchApi('/broker/ibkr/disconnect', {
    method: 'POST',
  });
}

export async function connectFutu(config?: {
  host?: string;
  port?: number;
}): Promise<{
  status: string;
  message: string;
}> {
  return fetchApi('/broker/futu/connect', {
    method: 'POST',
    body: JSON.stringify(config || {}),
  });
}

export async function disconnectFutu(): Promise<{
  status: string;
  message: string;
}> {
  return fetchApi('/broker/futu/disconnect', {
    method: 'POST',
  });
}

// Finviz Data Import API
export interface FinvizImportResponse {
  status: string;
  etf_symbol: string;
  coverage: string;
  records_imported: number;
  breadth_metrics: Record<string, unknown>;
  validation: Record<string, unknown>;
  statistics?: Record<string, unknown>;
}

export async function importFinvizData(
  etfSymbol: string,
  coverage: string,
  data: Array<Record<string, unknown>>
): Promise<FinvizImportResponse> {
  return fetchApi('/import/finviz', {
    method: 'POST',
    body: JSON.stringify({
      etf_symbol: etfSymbol,
      coverage: coverage,
      data: data,
    }),
  });
}

// MarketChameleon Data Import API
export interface MCImportResponse {
  status: string;
  records_imported: number;
  heat_distribution: Record<string, number>;
  data?: Array<Record<string, unknown>>;
}

export async function importMCData(
  data: Array<Record<string, unknown>>
): Promise<MCImportResponse> {
  return fetchApi('/import/marketchameleon', {
    method: 'POST',
    body: JSON.stringify({
      data: data,
    }),
  });
}

// Task Refresh APIs
export interface RefreshTaskAllETFsResponse {
  status: string;
  task_id: number;
  total: number;
  completed: number;
  failed: number;
  results: RefreshResult[];
  message: string;
}

export async function refreshTaskAllETFs(taskId: number): Promise<RefreshTaskAllETFsResponse> {
  return fetchApi(`/tasks/${taskId}/refresh-all-etfs`, {
    method: 'POST',
  });
}

// Holdings Refresh API
export interface RefreshHoldingsByCoverageResponse {
  status: string;
  symbol: string;
  coverage: string;
  stocks_count: number;
  total_weight: number;
  completeness: {
    coverage: string;
    total_stocks: number;
    complete_count: number;
    pending_count: number;
    missing_count: number;
    average_completeness: number;
  };
  updated_stocks: Array<{
    ticker: string;
    weight: number;
    price?: number;
    change_1d?: number;
    data_sources?: string[];
    data_status?: 'complete' | 'pending' | 'missing';
    completeness?: number;
    iv30?: number;
    updated_at?: string;
    score?: number;
  }>;
  updated_at: string;
  message: string;
}

export async function refreshHoldingsByCoverage(
  symbol: string,
  coverageType: 'top' | 'weight',
  coverageValue: number
): Promise<RefreshHoldingsByCoverageResponse> {
  return fetchApi(`/etfs/symbol/${symbol}/refresh-holdings-by-coverage`, {
    method: 'POST',
    body: JSON.stringify({
      coverage_type: coverageType,
      coverage_value: coverageValue,
      // 支持多数据源并发处理
      sources: ['finviz', 'marketchameleon', 'market_data', 'options_data'],
      concurrent: true, // 启用并发处理
    }),
  });
}

// 多数据源并发刷新接口 (高级用法)
export interface MultiSourceRefreshResponse extends RefreshHoldingsByCoverageResponse {
  data_sources_status?: Array<{
    source: 'finviz' | 'marketchameleon' | 'market_data' | 'options_data';
    status: 'pending' | 'processing' | 'completed' | 'failed';
    records_count?: number;
    error?: string;
    elapsed_time?: number;
  }>;
  concurrent_processing?: {
    enabled: boolean;
    total_sources: number;
    completed_sources: number;
    start_time?: string;
    end_time?: string;
  };
}

/**
 * 并发刷新多个数据源的Holdings数据
 * 后端会同时处理多个数据源，提高效率
 */
export async function refreshHoldingsConcurrent(
  symbol: string,
  coverageType: 'top' | 'weight',
  coverageValue: number,
  sources?: string[]
): Promise<MultiSourceRefreshResponse> {
  return fetchApi(`/etfs/symbol/${symbol}/refresh-holdings-concurrent`, {
    method: 'POST',
    body: JSON.stringify({
      coverage_type: coverageType,
      coverage_value: coverageValue,
      sources: sources || ['finviz', 'marketchameleon', 'market_data', 'options_data'],
      concurrent: true,
    }),
  });
}
