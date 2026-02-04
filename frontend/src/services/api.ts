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
const API_BASE_URL = (
  (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env
    ?.VITE_API_BASE_URL || 'http://localhost:8000/api'
);
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
    const responseText = await response.text();

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      const errorDetails: Record<string, unknown> = {
        endpoint,
        responseText,
      };

      if (responseText.trim()) {
        try {
          const parsed: unknown = JSON.parse(responseText);
          if (isRecord(parsed)) {
            const message = toStringValue(parsed.message);
            const detail = parsed.detail;
            if (message) {
              errorMessage = message;
            } else if (typeof detail === 'string' && detail.trim()) {
              errorMessage = detail;
            } else if (Array.isArray(detail) && detail.length > 0) {
              errorMessage = detail
                .map((item) => (isRecord(item) ? toStringValue(item.msg) || JSON.stringify(item) : String(item)))
                .join('; ');
            } else {
              errorMessage = responseText.trim();
            }
            errorDetails.payload = parsed;
          } else {
            errorMessage = responseText.trim();
          }
        } catch {
          errorMessage = responseText.trim();
        }
      }

      throw new ApiError(
        errorMessage,
        response.status,
        response.status.toString(),
        errorDetails
      );
    }

    if (!responseText.trim()) {
      return {} as T;
    }

    try {
      return JSON.parse(responseText) as T;
    } catch {
      return responseText as unknown as T;
    }
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

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function toStringValue(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed === '' ? undefined : trimmed;
  }
  return undefined;
}

function toBoolean(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'string') {
    if (value.toLowerCase() === 'true') return true;
    if (value.toLowerCase() === 'false') return false;
  }
  return undefined;
}

function toStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const normalized = value
    .map((item) => toStringValue(item) || String(item))
    .map((item) => item.trim())
    .filter((item) => item !== '');
  return normalized.length > 0 ? normalized : undefined;
}

function toNumberRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) {
    return {};
  }
  const result: Record<string, number> = {};
  Object.entries(value).forEach(([key, val]) => {
    const parsed = toNumber(val);
    if (parsed !== undefined) {
      result[key] = parsed;
    }
  });
  return result;
}

function normalizeHeatType(value: unknown): HeatType {
  const normalized = (toStringValue(value) || '').toLowerCase();
  if (normalized === 'trend' || normalized === 'event' || normalized === 'hedge') {
    return normalized;
  }
  return 'normal';
}

function normalizeThresholdStatus(
  value: unknown
): 'PASS' | 'FAIL' | 'NO_DATA' | undefined {
  const normalized = (toStringValue(value) || '').toUpperCase();
  if (normalized === 'PASS' || normalized === 'FAIL' || normalized === 'NO_DATA') {
    return normalized;
  }
  return undefined;
}

function normalizeComparisonType(value: unknown): 'industry' | 'sector' | 'market' {
  const normalized = (toStringValue(value) || '').toLowerCase();
  if (normalized === 'industry' || normalized === 'sector') {
    return normalized;
  }
  return 'market';
}

function normalizeStock(raw: unknown): Stock {
  const source = isRecord(raw) ? raw : {};
  const metricsRaw = isRecord(source.metrics) ? source.metrics : {};
  const scoresRaw = isRecord(source.scores) ? source.scores : {};
  const changesRaw = isRecord(source.changes) ? source.changes : {};
  const thresholdsRaw = isRecord(source.thresholds) ? source.thresholds : {};

  const thresholdPrice = normalizeThresholdStatus(thresholdsRaw.price_above_sma50);
  const thresholdRs = normalizeThresholdStatus(
    thresholdsRaw.rs_positive ?? thresholdsRaw.rs_20d_positive
  );
  const normalizedThresholds =
    thresholdPrice || thresholdRs
      ? {
          price_above_sma50: thresholdPrice ?? 'NO_DATA',
          rs_positive: thresholdRs ?? 'NO_DATA',
        }
      : undefined;

  const scoreTotal = toNumber(source.scoreTotal) ?? toNumber(source.totalScore) ?? 0;
  const return20d = toNumber(source.return20d) ?? toNumber(metricsRaw.return20d);
  const return63d = toNumber(source.return63d) ?? toNumber(metricsRaw.return63d);
  const relativeStrength = toNumber(source.rs20d) ?? toNumber(metricsRaw.relativeStrength);

  const comparisons = Array.isArray(source.comparisons)
    ? source.comparisons
        .filter(isRecord)
        .map((item) => {
          const symbol = toStringValue(item.symbol);
          if (!symbol) {
            return null;
          }
          return {
            symbol,
            type: normalizeComparisonType(item.type),
            return20d: toNumber(item.return20d) ?? null,
            rs20d: toNumber(item.rs20d) ?? null,
            sma20Slope: toNumber(item.sma20Slope) ?? null,
            beta: toNumber(item.beta) ?? null,
          };
        })
        .filter((item): item is NonNullable<typeof item> => item !== null)
    : undefined;

  return {
    id: toNumber(source.id),
    symbol: toStringValue(source.symbol) ?? '',
    name: toStringValue(source.name) ?? toStringValue(source.symbol) ?? '',
    sector: toStringValue(source.sector),
    industry: toStringValue(source.industry),
    industryEtfs: toStringArray(source.industryEtfs),

    price: toNumber(source.price) ?? 0,
    change: toNumber(source.change) ?? toNumber(source.change_1d) ?? toNumber(metricsRaw.change),
    changePercent:
      toNumber(source.changePercent) ??
      toNumber(source.change_percent) ??
      toNumber(metricsRaw.changePercent),

    sma20: toNumber(source.sma20) ?? toNumber(source.sma_20) ?? toNumber(metricsRaw.sma20) ?? toNumber(metricsRaw.sma_20),
    sma50: toNumber(source.sma50) ?? toNumber(source.sma_50) ?? toNumber(metricsRaw.sma50) ?? toNumber(metricsRaw.sma_50),
    sma200: toNumber(source.sma200) ?? toNumber(source.sma_200) ?? toNumber(metricsRaw.sma200) ?? toNumber(metricsRaw.sma_200),
    rsi: toNumber(source.rsi) ?? toNumber(metricsRaw.rsi),
    beta: toNumber(source.beta) ?? toNumber(metricsRaw.beta),

    return20d,
    return63d,
    rs20d: relativeStrength ?? null,

    volume:
      toNumber(source.volume) ??
      toNumber(source.latestVolume) ??
      toNumber(source.latest_volume) ??
      toNumber(metricsRaw.volume),
    avgVolume:
      toNumber(source.avgVolume) ??
      toNumber(source.avg_volume) ??
      toNumber(metricsRaw.avgVolume) ??
      toNumber(metricsRaw.avg_volume),
    volumeRatio: toNumber(source.volumeRatio) ?? toNumber(metricsRaw.volumeRatio),

    impliedVolatility:
      toNumber(source.impliedVolatility) ??
      toNumber(source.implied_volatility) ??
      toNumber(metricsRaw.impliedVolatility) ??
      toNumber(metricsRaw.implied_volatility) ??
      toNumber(metricsRaw.iv30),
    ivr: toNumber(source.ivr) ?? toNumber(metricsRaw.ivr) ?? null,
    openInterest:
      toNumber(source.openInterest) ??
      toNumber(source.open_interest) ??
      toNumber(metricsRaw.openInterest) ??
      toNumber(metricsRaw.open_interest) ??
      toNumber(metricsRaw.total_oi),

    scoreTotal,
    totalScore: scoreTotal,
    technicalScore: toNumber(source.technicalScore) ?? toNumber(scoresRaw.trend),
    momentumScore: toNumber(source.momentumScore) ?? toNumber(scoresRaw.momentum),
    volumeScore: toNumber(source.volumeScore) ?? toNumber(scoresRaw.volume),
    optionsScore: toNumber(source.optionsScore) ?? toNumber(scoresRaw.options),

    scores: {
      momentum: toNumber(scoresRaw.momentum) ?? 0,
      trend: toNumber(scoresRaw.trend) ?? 0,
      volume: toNumber(scoresRaw.volume) ?? 0,
      quality: toNumber(scoresRaw.quality) ?? 0,
      options: toNumber(scoresRaw.options) ?? 0,
    },
    changes: {
      delta3d: toNumber(changesRaw.delta3d) ?? null,
      delta5d: toNumber(changesRaw.delta5d) ?? null,
    },

    heatType: normalizeHeatType(source.heatType ?? source.heat_type),
    heatScore: toNumber(source.heatScore) ?? toNumber(source.heat_score) ?? toNumber(metricsRaw.heat_score),
    riskScore: toNumber(source.riskScore) ?? toNumber(source.risk_score) ?? toNumber(metricsRaw.risk_score),
    thresholdsPass: toBoolean(source.thresholdsPass ?? source.thresholds_pass),
    thresholds: normalizedThresholds,

    lastUpdated: toStringValue(source.lastUpdated) ?? toStringValue(source.updatedAt) ?? toStringValue(source.updated_at),
    marketCap: toNumber(source.marketCap) ?? toNumber(metricsRaw.marketCap),
    metrics: isRecord(source.metrics) ? (source.metrics as Stock['metrics']) : undefined,
    comparisons,
  };
}

function buildDefaultScoreBreakdown(stock: Stock): StockDetail['scoreBreakdown'] {
  const metrics = (stock.metrics || {}) as UnknownRecord;
  return {
    momentum: {
      score: stock.momentumScore ?? 0,
      data: {
        return_20d: stock.return20d ?? 0,
        return_63d: stock.return63d ?? 0,
        rs_20d: stock.rs20d ?? null,
      },
    },
    technical: {
      score: stock.technicalScore ?? 0,
      data: {
        price: stock.price ?? 0,
        sma20: stock.sma20 ?? 0,
        sma50: stock.sma50 ?? 0,
        sma200: stock.sma200 ?? null,
        rsi: stock.rsi ?? 0,
        dist_from_52w_high: toNumber(metrics.distanceToHigh20d) ?? 0,
        score_breakdown: {},
      },
    },
    volume: {
      score: stock.volumeScore ?? 0,
      data: {
        volume: stock.volume ?? toNumber(metrics.volumeMultiple) ?? 0,
        avg_volume: stock.avgVolume ?? 0,
        volume_ratio: stock.volumeRatio ?? toNumber(metrics.volumeRatio) ?? 0,
      },
    },
    options: {
      score: stock.optionsScore ?? 0,
      data: {
        heat_type: stock.heatType ?? 'normal',
        heat_score: stock.heatScore ?? 0,
        risk_score: stock.riskScore ?? 0,
        ivr: stock.ivr ?? null,
        implied_volatility: stock.impliedVolatility,
        open_interest: stock.openInterest,
      },
    },
  };
}

function transformStockDetailResponse(data: unknown): StockDetail {
  const source = isRecord(data) ? data : {};
  const detail = isRecord(source.detail) ? source.detail : {};
  const scoresBreakdown = isRecord(detail.scoresBreakdown)
    ? detail.scoresBreakdown
    : isRecord(detail.scores_breakdown)
      ? detail.scores_breakdown
      : {};
  const metrics = isRecord(source.metrics) ? source.metrics : {};
  const scores = isRecord(source.scores) ? source.scores : {};

  const momentum = isRecord(scoresBreakdown.momentum) ? scoresBreakdown.momentum : {};
  const momentumComponents = isRecord(momentum.components) ? momentum.components : {};

  const trend = isRecord(scoresBreakdown.trend) ? scoresBreakdown.trend : {};
  const trendComponents = isRecord(trend.components) ? trend.components : {};

  const volume = isRecord(scoresBreakdown.volume) ? scoresBreakdown.volume : {};
  const volumeComponents = isRecord(volume.components) ? volume.components : {};

  const options = isRecord(scoresBreakdown.options) ? scoresBreakdown.options : {};
  const optionsComponents = isRecord(options.components) ? options.components : {};

  const baseStock = normalizeStock(source);
  const defaultBreakdown = buildDefaultScoreBreakdown(baseStock);

  return {
    ...baseStock,
    scoreBreakdown: {
      momentum: {
        score: toNumber(momentum.score) ?? toNumber(scores.momentum) ?? defaultBreakdown.momentum.score,
        data: {
          return_20d:
            toNumber(momentumComponents.return20d) ??
            toNumber(momentumComponents.return_20d) ??
            baseStock.return20d ??
            defaultBreakdown.momentum.data.return_20d,
          return_63d:
            toNumber(momentumComponents.return63d) ??
            toNumber(momentumComponents.return_63d) ??
            baseStock.return63d ??
            defaultBreakdown.momentum.data.return_63d,
          rs_20d:
            toNumber(momentumComponents.relativeStrength) ??
            toNumber(momentumComponents.relative_strength) ??
            baseStock.rs20d ??
            null,
          score_breakdown: toNumberRecord(momentumComponents),
        },
      },
      technical: {
        score: toNumber(trend.score) ?? toNumber(scores.trend) ?? defaultBreakdown.technical.score,
        data: {
          price: baseStock.price ?? 0,
          sma20:
            toNumber(trendComponents.sma20) ??
            toNumber(trendComponents.sma_20) ??
            baseStock.sma20 ??
            0,
          sma50:
            toNumber(trendComponents.sma50) ??
            toNumber(trendComponents.sma_50) ??
            baseStock.sma50 ??
            0,
          sma200:
            toNumber(trendComponents.sma200) ??
            toNumber(trendComponents.sma_200) ??
            baseStock.sma200 ??
            null,
          rsi: baseStock.rsi ?? 0,
          dist_from_52w_high: toNumber(trendComponents.distanceToHigh20d) ?? toNumber(metrics.distanceToHigh20d) ?? 0,
          score_breakdown: toNumberRecord(trendComponents),
        },
      },
      volume: {
        score: toNumber(volume.score) ?? toNumber(scores.volume) ?? defaultBreakdown.volume.score,
        data: {
          volume:
            toNumber(volumeComponents.volume) ??
            toNumber(volumeComponents.latestVolume) ??
            baseStock.volume ??
            0,
          avg_volume:
            toNumber(volumeComponents.avgVolume) ??
            toNumber(volumeComponents.avg_volume) ??
            baseStock.avgVolume ??
            0,
          volume_ratio:
            toNumber(volumeComponents.volumeRatio) ??
            toNumber(volumeComponents.volume_ratio) ??
            toNumber(volumeComponents.volumeMultiple) ??
            baseStock.volumeRatio ??
            0,
        },
      },
      options: {
        score: toNumber(options.score) ?? toNumber(scores.options) ?? defaultBreakdown.options.score,
        data: {
          heat_type:
            toStringValue(isRecord(detail.heatAnalysis) ? detail.heatAnalysis.type : undefined) ??
            toStringValue(isRecord(detail.heatAnalysis) ? detail.heatAnalysis.heat_type : undefined) ??
            baseStock.heatType ??
            'normal',
          heat_score:
            toNumber(isRecord(detail.heatAnalysis) ? detail.heatAnalysis.score : undefined) ??
            toNumber(metrics.heat_score) ??
            baseStock.heatScore ??
            0,
          risk_score:
            toNumber(isRecord(detail.heatAnalysis) ? detail.heatAnalysis.riskScore : undefined) ??
            toNumber(metrics.risk_score) ??
            baseStock.riskScore ??
            0,
          ivr: toNumber(optionsComponents.ivr) ?? baseStock.ivr ?? null,
          implied_volatility:
            toNumber(optionsComponents.iv30) ??
            toNumber(optionsComponents.iv_30) ??
            toNumber(metrics.iv30) ??
            baseStock.impliedVolatility,
          open_interest:
            toNumber(optionsComponents.openInterest) ??
            toNumber(optionsComponents.open_interest) ??
            baseStock.openInterest,
        },
      },
    },
  };
}

function buildStocksApiQuery(params?: StockQueryParams, limitOverride?: number): string {
  const queryParams = new URLSearchParams();

  if (params?.industry) {
    queryParams.set('industry', params.industry);
  }
  if (params?.sector) {
    queryParams.set('sector', params.sector.toUpperCase());
  }
  if (params?.minScore !== undefined) {
    queryParams.set('min_score', params.minScore.toString());
  }

  const limit = limitOverride ?? params?.limit;
  if (limit !== undefined) {
    queryParams.set('limit', Math.max(1, Math.floor(limit)).toString());
  }

  return queryParams.toString();
}

function getStockSortValue(stock: Stock, sortBy: string): number | string | undefined {
  const directValue = (stock as unknown as UnknownRecord)[sortBy];
  if (typeof directValue === 'number' || typeof directValue === 'string') {
    return directValue;
  }

  const metrics = stock.metrics as unknown;
  if (isRecord(metrics)) {
    const metricValue = metrics[sortBy];
    if (typeof metricValue === 'number' || typeof metricValue === 'string') {
      return metricValue;
    }
  }

  return undefined;
}

function applyStockClientFilters(
  stocks: Stock[],
  params?: StockQueryParams,
  applyPagination = true
): Stock[] {
  let filtered = [...stocks];

  if (params?.heatType) {
    filtered = filtered.filter((stock) => stock.heatType === params.heatType);
  }

  if (params?.maxScore !== undefined) {
    filtered = filtered.filter((stock) => (stock.scoreTotal ?? stock.totalScore ?? 0) <= params.maxScore!);
  }

  if (params?.minPrice !== undefined) {
    filtered = filtered.filter((stock) => stock.price >= params.minPrice!);
  }

  if (params?.maxPrice !== undefined) {
    filtered = filtered.filter((stock) => stock.price <= params.maxPrice!);
  }

  if (params?.thresholdsPass !== undefined) {
    filtered = filtered.filter((stock) => (stock.thresholdsPass ?? false) === params.thresholdsPass);
  }

  if (params?.sortBy) {
    const order = params.sortOrder === 'asc' ? 1 : -1;
    filtered.sort((a, b) => {
      const left = getStockSortValue(a, params.sortBy!);
      const right = getStockSortValue(b, params.sortBy!);

      if (left === undefined && right === undefined) return 0;
      if (left === undefined) return 1;
      if (right === undefined) return -1;

      if (typeof left === 'number' && typeof right === 'number') {
        return (left - right) * order;
      }

      return String(left).localeCompare(String(right)) * order;
    });
  }

  if (!applyPagination) {
    return filtered;
  }

  const offset = Math.max(0, Math.floor(params?.offset ?? 0));
  const limit = params?.limit !== undefined ? Math.max(0, Math.floor(params.limit)) : undefined;
  if (limit === undefined) {
    return filtered.slice(offset);
  }
  return filtered.slice(offset, offset + limit);
}

async function fetchStocksFromApi(params?: StockQueryParams, limitOverride?: number): Promise<Stock[]> {
  const query = buildStocksApiQuery(params, limitOverride);
  const endpoint = query ? `/stocks?${query}` : '/stocks';
  const response = await fetchApi<unknown>(endpoint);
  if (!Array.isArray(response)) {
    return [];
  }
  return response.map((item) => normalizeStock(item));
}

/**
 * Get all stocks with optional filtering and pagination
 */
export async function getStocks(params?: StockQueryParams): Promise<Stock[]> {
  const stocks = await fetchStocksFromApi(params);
  return applyStockClientFilters(stocks, params, true);
}

/**
 * Get paginated stocks
 */
export async function getStocksPaginated(
  params?: StockQueryParams
): Promise<PaginatedResponse<Stock>> {
  const pageSize = Math.max(1, Math.floor(params?.limit ?? 20));
  const offset = Math.max(0, Math.floor(params?.offset ?? 0));
  const stocks = await fetchStocksFromApi(params, offset + pageSize);

  const filtered = applyStockClientFilters(
    stocks,
    { ...params, limit: undefined, offset: undefined },
    false
  );

  const data = filtered.slice(offset, offset + pageSize);
  return {
    data,
    total: filtered.length,
    page: Math.floor(offset / pageSize) + 1,
    pageSize,
    hasMore: offset + pageSize < filtered.length,
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
  const response = await fetchApi<unknown>(`/stocks/symbol/${symbol.toUpperCase()}/detail`);
  return transformStockDetailResponse(response);
}

/**
 * Get basic stock information
 */
export async function getStock(symbol: string): Promise<Stock> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  const response = await fetchApi<unknown>(`/stocks/symbol/${symbol.toUpperCase()}`);
  return normalizeStock(response);
}

// ----------------------------------------------------------------------------
// Stock Comparison APIs
// ----------------------------------------------------------------------------

/**
 * Compare multiple stocks side by side
 * @param symbols - Array of stock symbols (minimum 2, maximum 4)
 */
export async function compareStocks(symbols: string[]): Promise<StockDetail[]> {
  if (!symbols || symbols.length < 2) {
    throw new Error('At least 2 stock symbols are required for comparison');
  }

  const cleanedSymbols = Array.from(
    new Set(symbols.map((s) => s.trim().toUpperCase()).filter((s) => s !== ''))
  );

  if (cleanedSymbols.length < 2) {
    throw new Error('At least 2 unique stock symbols are required for comparison');
  }

  if (cleanedSymbols.length > 4) {
    throw new Error('Cannot compare more than 4 stocks at once');
  }

  const response = await fetchApi<unknown>('/stocks/compare', {
    method: 'POST',
    body: JSON.stringify(cleanedSymbols),
  });

  if (!Array.isArray(response)) {
    return [];
  }

  return response.map((item) => {
    const stock = normalizeStock(item);
    return {
      ...stock,
      scoreBreakdown: buildDefaultScoreBreakdown(stock),
    };
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
  const response = await fetchApi<unknown>(
    `/stocks/by-heat/${heatType}${query ? `?${query}` : ''}`
  );
  if (!Array.isArray(response)) {
    return [];
  }
  return response.map((item) => normalizeStock(item));
}

/**
 * Get heat distribution across all stocks
 */
export async function getHeatDistribution(): Promise<Record<HeatType, number>> {
  const baseDistribution: Record<HeatType, number> = {
    trend: 0,
    event: 0,
    hedge: 0,
    normal: 0,
  };

  const heatTypes: HeatType[] = ['trend', 'event', 'hedge', 'normal'];
  const counts = await Promise.all(
    heatTypes.map(async (type) => {
      try {
        const stocks = await getStocksByHeat(type, { limit: 1000 });
        return [type, stocks.length] as const;
      } catch {
        return [type, 0] as const;
      }
    })
  );

  counts.forEach(([type, count]) => {
    baseDistribution[type] = count;
  });

  return baseDistribution;
}

// ----------------------------------------------------------------------------
// Sector APIs
// ----------------------------------------------------------------------------

/**
 * Get list of all sectors
 */
export async function getSectors(): Promise<string[]> {
  const response = await fetchApi<unknown>('/etfs/sectors');
  if (!Array.isArray(response)) {
    return [];
  }
  const symbols = response
    .map((item) => normalizeETF(item).symbol)
    .filter((symbol) => symbol !== '');
  return Array.from(new Set(symbols));
}

/**
 * Get stocks by sector
 */
export async function getStocksBySector(sector: string): Promise<Stock[]> {
  if (!sector || sector.trim() === '') {
    throw new Error('Sector name is required');
  }
  return getStocks({ sector: sector.toUpperCase() });
}

/**
 * Get sector summary with statistics
 */
export async function getSectorSummary(sector: string): Promise<SectorSummary> {
  if (!sector || sector.trim() === '') {
    throw new Error('Sector name is required');
  }
  const normalizedSector = sector.toUpperCase();
  const stocks = await getStocksBySector(normalizedSector);
  const sorted = [...stocks].sort(
    (a, b) => (b.scoreTotal ?? b.totalScore ?? 0) - (a.scoreTotal ?? a.totalScore ?? 0)
  );
  const avgScore = stocks.length
    ? stocks.reduce((sum, stock) => sum + (stock.scoreTotal ?? stock.totalScore ?? 0), 0) / stocks.length
    : 0;

  const heatDistribution: Record<HeatType, number> = {
    trend: 0,
    event: 0,
    hedge: 0,
    normal: 0,
  };
  stocks.forEach((stock) => {
    const type = stock.heatType || 'normal';
    heatDistribution[type] = (heatDistribution[type] || 0) + 1;
  });

  return {
    sector: normalizedSector,
    stockCount: stocks.length,
    avgScore: Number(avgScore.toFixed(2)),
    topStocks: sorted.slice(0, 5),
    heatDistribution,
  };
}

/**
 * Get all sector summaries
 */
export async function getAllSectorSummaries(): Promise<SectorSummary[]> {
  const sectors = await getSectors();
  const summaries = await Promise.all(
    sectors.map(async (sector) => {
      try {
        return await getSectorSummary(sector);
      } catch {
        return null;
      }
    })
  );
  return summaries.filter((item): item is SectorSummary => item !== null);
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

  const keyword = query.trim().toUpperCase();
  const stocks = await fetchStocksFromApi({ limit: Math.max(limit * 10, 200) });
  return stocks
    .filter((stock) => {
      const symbolMatched = stock.symbol.toUpperCase().includes(keyword);
      const nameMatched = (stock.name || '').toUpperCase().includes(keyword);
      return symbolMatched || nameMatched;
    })
    .slice(0, limit);
}

// ----------------------------------------------------------------------------
// Refresh APIs
// ----------------------------------------------------------------------------

interface MarketSyncApiResponse {
  status?: string;
  synced?: string[];
  failed?: string[];
  total?: number;
  success_count?: number;
}

const marketPriceSyncInFlight = new Map<string, Promise<{ synced: string[]; failed: string[] }>>();
const marketPriceSyncLastSuccessAt = new Map<string, number>();
const MARKET_PRICE_SYNC_MAX_AGE_MS = 5 * 60 * 1000;

interface SyncPriceDataOptions {
  force?: boolean;
  maxAgeMs?: number;
}

export async function syncPriceDataForSymbols(
  symbols: string[],
  options?: SyncPriceDataOptions
): Promise<{
  synced: string[];
  failed: string[];
}> {
  const cleanedSymbols = Array.from(
    new Set(
      (symbols || [])
        .map((symbol) => symbol.trim().toUpperCase())
        .filter((symbol) => symbol !== '')
    )
  );

  if (cleanedSymbols.length === 0) {
    return { synced: [], failed: [] };
  }

  const key = cleanedSymbols.join('|');
  const maxAgeMs = options?.maxAgeMs ?? MARKET_PRICE_SYNC_MAX_AGE_MS;
  if (!options?.force && maxAgeMs > 0) {
    const lastSyncedAt = marketPriceSyncLastSuccessAt.get(key);
    if (typeof lastSyncedAt === 'number' && Date.now() - lastSyncedAt < maxAgeMs) {
      return { synced: cleanedSymbols, failed: [] };
    }
  }

  const existing = marketPriceSyncInFlight.get(key);
  if (existing) {
    return existing;
  }

  const request = (async () => {
    const response = await fetchApi<MarketSyncApiResponse>('/market/sync', {
      method: 'POST',
      timeout: 120000,
      body: JSON.stringify({
        symbols: cleanedSymbols,
        sync_type: 'price',
      }),
    });

    const result = {
      synced: Array.isArray(response.synced) ? response.synced : [],
      failed: Array.isArray(response.failed) ? response.failed : [],
    };
    if (result.failed.length === 0) {
      marketPriceSyncLastSuccessAt.set(key, Date.now());
    }
    return result;
  })();

  marketPriceSyncInFlight.set(key, request);
  try {
    return await request;
  } finally {
    marketPriceSyncInFlight.delete(key);
  }
}

/**
 * Trigger data refresh for a specific stock
 */
export async function refreshStock(symbol: string): Promise<{ success: boolean; message: string }> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }

  const normalizedSymbol = symbol.toUpperCase();
  const response = await fetchApi<MarketSyncApiResponse>('/market/sync', {
    method: 'POST',
    timeout: 120000,
    body: JSON.stringify({
      symbols: [normalizedSymbol],
      sync_type: 'all',
    }),
  });

  const synced = Array.isArray(response.synced) ? response.synced : [];
  const failed = Array.isArray(response.failed) ? response.failed : [];
  const success = synced.includes(normalizedSymbol) && failed.length === 0;

  return {
    success,
    message: success
      ? `Synced ${normalizedSymbol} successfully`
      : `Sync finished: ${synced.length} success, ${failed.length} failed`,
  };
}

/**
 * Trigger full data refresh for all stocks
 */
export async function refreshAllStocks(): Promise<{ success: boolean; message: string }> {
  const stocks = await fetchStocksFromApi({ limit: 500 });
  const symbols = stocks.map((stock) => stock.symbol).filter((symbol) => symbol !== '');

  if (symbols.length === 0) {
    return { success: false, message: 'No stocks available for refresh' };
  }

  const response = await fetchApi<MarketSyncApiResponse>('/market/sync', {
    method: 'POST',
    timeout: 180000,
    body: JSON.stringify({
      symbols,
      sync_type: 'all',
    }),
  });

  const synced = Array.isArray(response.synced) ? response.synced : [];
  const failed = Array.isArray(response.failed) ? response.failed : [];
  return {
    success: failed.length === 0,
    message: `Synced ${synced.length}/${symbols.length} symbols`,
  };
}

// ----------------------------------------------------------------------------
// Health Check API
// ----------------------------------------------------------------------------

/**
 * Check API health status
 */
export async function checkHealth(): Promise<{
  status: string;
  timestamp: string;
  apiVersion?: string;
  brokerStatus?: Record<string, unknown>;
}> {
  const response = await fetchApi<{
    status?: string;
    api_version?: string;
    broker_status?: Record<string, unknown>;
  }>('/status');

  return {
    status: response.status || 'unknown',
    timestamp: new Date().toISOString(),
    apiVersion: response.api_version,
    brokerStatus: response.broker_status,
  };
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

function normalizeETF(raw: unknown): ETF {
  const source = isRecord(raw) ? raw : {};
  const deltaRaw = isRecord(source.delta) ? source.delta : {};

  const holdings = Array.isArray(source.holdings)
    ? source.holdings
        .filter(isRecord)
        .map((item) => {
          const dataSourcesRaw = isRecord(item.dataSources) ? item.dataSources : {};
          const dataSources: Record<string, boolean> = {};
          Object.entries(dataSourcesRaw).forEach(([key, value]) => {
            const parsed = toBoolean(value);
            if (parsed !== undefined) {
              dataSources[key] = parsed;
            }
          });
          return {
            ticker: toStringValue(item.ticker) ?? '',
            weight: toNumber(item.weight) ?? 0,
            score: toNumber(item.score) ?? null,
            updatedAt: toStringValue(item.updatedAt) ?? null,
            dataSources: Object.keys(dataSources).length > 0 ? dataSources : undefined,
            dataStatus: (toStringValue(item.dataStatus) as 'complete' | 'pending' | 'missing' | 'loading' | undefined) ?? undefined,
            completeness: toNumber(item.completeness),
          };
        })
        .filter((item) => item.ticker !== '')
    : undefined;

  const delta = isRecord(source.delta)
    ? {
        delta3d: toNumber(deltaRaw.delta3d) ?? null,
        delta5d: toNumber(deltaRaw.delta5d) ?? null,
      }
    : undefined;

  return {
    id: toNumber(source.id) ?? 0,
    symbol: toStringValue(source.symbol) ?? '',
    name: toStringValue(source.name) ?? toStringValue(source.symbol) ?? '',
    type: toStringValue(source.type) === 'industry' ? 'industry' : 'sector',
    parentSector: toStringValue(source.parentSector),
    score: toNumber(source.score) ?? 0,
    rank: toNumber(source.rank) ?? 0,
    delta,
    completeness: toNumber(source.completeness) ?? 0,
    holdingsCount: toNumber(source.holdingsCount) ?? 0,
    holdings,
    coverageRanges: toStringArray(source.coverageRanges),
    lastUpdated: toStringValue(source.lastUpdated),
  };
}

/**
 * Get ETFs by type (sector or industry)
 * @param type - ETF type: 'sector' or 'industry'
 * @param includeHoldings - Whether to include holdings data (default: true for sector/industry overview)
 */
export async function getETFs(type: 'sector' | 'industry', includeHoldings = true): Promise<ETF[]> {
  const query = `type=${type}&include_holdings=${includeHoldings}`;
  const response = await fetchApi<unknown>(`/etfs?${query}`);
  if (!Array.isArray(response)) {
    return [];
  }
  return response.map((item) => normalizeETF(item));
}

/**
 * Get single ETF details
 */
export async function getETF(symbol: string): Promise<ETF> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  return getETFBySymbol(symbol, false);
}

/**
 * Refresh ETF data
 */
export async function refreshETF(symbol: string): Promise<{ success: boolean; message: string }> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  const normalizedSymbol = symbol.toUpperCase();
  const response = await fetchApi<Record<string, unknown>>(
    `/etfs/symbol/${normalizedSymbol}/refresh`,
    { method: 'POST' }
  );
  const status = toStringValue(response.status) || 'error';
  return {
    success: status === 'success' || status === 'partial_success',
    message: toStringValue(response.message) || `Refresh ${status}: ${normalizedSymbol}`,
  };
}

function normalizeTaskType(value: unknown): Task['type'] {
  const normalized = toStringValue(value);
  if (normalized === 'drilldown' || normalized === 'momentum') {
    return normalized;
  }
  return 'rotation';
}

function normalizeTaskBaseIndex(value: unknown): Task['baseIndex'] {
  const normalized = (toStringValue(value) || '').toUpperCase();
  if (normalized === 'QQQ' || normalized === 'IWM') {
    return normalized;
  }
  return 'SPY';
}

function normalizeTaskEtfs(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => toStringValue(item) || String(item))
      .map((item) => item.trim().toUpperCase())
      .filter((item) => item !== '');
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) {
      return [];
    }
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed
          .map((item) => toStringValue(item) || String(item))
          .map((item) => item.trim().toUpperCase())
          .filter((item) => item !== '');
      }
    } catch {
      // fallback to comma separated format
    }
    return trimmed
      .split(',')
      .map((item) => item.trim().toUpperCase())
      .filter((item) => item !== '');
  }
  return [];
}

function normalizeTask(raw: unknown): Task {
  const source = isRecord(raw) ? raw : {};
  return {
    id: toNumber(source.id) ?? 0,
    title: toStringValue(source.title) ?? '',
    type: normalizeTaskType(source.type),
    baseIndex: normalizeTaskBaseIndex(source.baseIndex),
    sector: toStringValue(source.sector),
    etfs: normalizeTaskEtfs(source.etfs),
    createdAt: toStringValue(source.createdAt) ?? '',
    updatedAt: toStringValue(source.updatedAt),
  };
}

function normalizeTaskId(id: string | number): string {
  if (typeof id === 'number') {
    return String(id);
  }
  const normalized = id.trim();
  if (!normalized) {
    throw new Error('Task ID is required');
  }
  return normalized;
}


/**
 * Get all tasks
 */
export async function getTasks(): Promise<Task[]> {
  const response = await fetchApi<unknown>('/tasks');
  if (!Array.isArray(response)) {
    return [];
  }
  return response.map((item) => normalizeTask(item));
}

/**
 * Get single task by ID
 */
export async function getTask(id: string | number): Promise<Task> {
  const taskId = normalizeTaskId(id);
  const response = await fetchApi<unknown>(`/tasks/${taskId}`);
  return normalizeTask(response);
}

/**
 * Create a new task
 */
export async function createTask(input: CreateTaskInput): Promise<Task> {
  const response = await fetchApi<unknown>('/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return normalizeTask(response);
}

/**
 * Delete a task
 */
export async function deleteTask(id: string | number): Promise<{ success: boolean; message: string }> {
  const taskId = normalizeTaskId(id);
  const response = await fetchApi<{ message?: string }>(`/tasks/${taskId}`, {
    method: 'DELETE',
  });
  return {
    success: true,
    message: response.message || 'Task deleted successfully',
  };
}

/**
 * Get ETF by symbol (alias for getETF with optional includeHoldings)
 */
export async function getETFBySymbol(symbol: string, includeHoldings = false): Promise<ETF> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  const query = includeHoldings ? '?include_holdings=true' : '';
  const response = await fetchApi<unknown>(`/etfs/symbol/${symbol.toUpperCase()}${query}`);
  return normalizeETF(response);
}

/**
 * Get ETF score snapshots for multiple symbols
 */
export async function getEtfScoreSnapshots(symbols: string[]): Promise<Array<{
  symbol: string;
  date?: string;
  total_score?: number;
  thresholds_pass?: boolean;
  score_breakdown?: Record<string, unknown>;
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
    score_breakdown?: Record<string, unknown>;
  }>>(`/etfs/score-snapshots?symbols=${cleanedSymbols.join(',')}`);
}

/**
 * Get task by ID
 */
export async function getTaskById(id: string | number): Promise<Task> {
  return getTask(id);
}

export async function getTaskTrendComparison(
  taskId: string | number,
  period: 5 | 20 | 63 = 20,
  metric: 'relative' | 'sma20' | 'return20d' | 'score' = 'relative'
): Promise<{
  task_id: number;
  period: number;
  metric: string;
  symbols: string[];
  dates: string[];
  series: Array<{ symbol: string; values: Array<number | null> }>;
  price_series?: Array<{ symbol: string; values: Array<number | null> }>;
  sma20_series?: Array<{ symbol: string; values: Array<number | null> }>;
  deviation_series?: Array<{ symbol: string; values: Array<number | null> }>;
}> {
  if (!taskId) {
    throw new Error('Task ID is required');
  }
  return fetchApi<{
    task_id: number;
    period: number;
    metric: string;
    symbols: string[];
    dates: string[];
    series: Array<{ symbol: string; values: Array<number | null> }>;
    price_series?: Array<{ symbol: string; values: Array<number | null> }>;
    sma20_series?: Array<{ symbol: string; values: Array<number | null> }>;
    deviation_series?: Array<{ symbol: string; values: Array<number | null> }>;
  }>(`/tasks/${taskId}/trend-comparison?period=${period}&metric=${metric}`);
}

export async function getStockTrendComparison(
  symbol: string,
  period: 5 | 20 | 63 = 20,
  metric: 'relative' | 'sma20' | 'return20d' | 'score' = 'relative'
): Promise<{
  symbol: string;
  period: number;
  metric: string;
  symbols: string[];
  dates: string[];
  series: Array<{ symbol: string; values: Array<number | null> }>;
  price_series?: Array<{ symbol: string; values: Array<number | null> }>;
  sma20_series?: Array<{ symbol: string; values: Array<number | null> }>;
  deviation_series?: Array<{ symbol: string; values: Array<number | null> }>;
}> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  return fetchApi<{
    symbol: string;
    period: number;
    metric: string;
    symbols: string[];
    dates: string[];
    series: Array<{ symbol: string; values: Array<number | null> }>;
    price_series?: Array<{ symbol: string; values: Array<number | null> }>;
    sma20_series?: Array<{ symbol: string; values: Array<number | null> }>;
    deviation_series?: Array<{ symbol: string; values: Array<number | null> }>;
  }>(`/stocks/symbol/${symbol.toUpperCase()}/trend-comparison?period=${period}&metric=${metric}`);
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
    thresholds_pass?: boolean;
    breakdown?: Record<string, unknown>;
    data_sources?: Record<string, boolean>;
    message?: string;
  }>;
  message: string;
}> {
  if (!taskId) {
    throw new Error('Task ID is required');
  }
  return fetchApi<{
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
      thresholds_pass?: boolean;
      breakdown?: Record<string, unknown>;
      data_sources?: Record<string, boolean>;
      message?: string;
    }>;
    message: string;
  }>(`/tasks/${taskId}/refresh-all-etfs`, {
    method: 'POST',
    timeout: 180000,
  });
}

const DEFAULT_HOLDINGS_REFRESH_SYMBOLS = 10;
const HOLDINGS_REFRESH_BASE_TIMEOUT_MS = 120000;
const HOLDINGS_REFRESH_PER_SYMBOL_TIMEOUT_MS = 18000;
const HOLDINGS_REFRESH_MIN_TIMEOUT_MS = 120000;
const HOLDINGS_REFRESH_MAX_TIMEOUT_MS = 900000;

function clampTimeout(timeoutMs: number): number {
  if (!Number.isFinite(timeoutMs)) return HOLDINGS_REFRESH_MIN_TIMEOUT_MS;
  return Math.max(
    HOLDINGS_REFRESH_MIN_TIMEOUT_MS,
    Math.min(HOLDINGS_REFRESH_MAX_TIMEOUT_MS, Math.round(timeoutMs))
  );
}

function estimateRefreshSymbolsCount(
  coverageType: string,
  coverageValue: number,
  expectedSymbolsCount?: number
): number {
  if (typeof expectedSymbolsCount === 'number' && Number.isFinite(expectedSymbolsCount) && expectedSymbolsCount > 0) {
    return Math.max(1, Math.round(expectedSymbolsCount));
  }

  if (coverageType.toLowerCase() === 'top') {
    return Math.max(1, Math.round(coverageValue));
  }

  // weight coverage without local holdings fallback: use conservative estimate.
  return DEFAULT_HOLDINGS_REFRESH_SYMBOLS;
}

function calcHoldingsRefreshTimeoutMs(symbolsCount: number): number {
  return clampTimeout(
    HOLDINGS_REFRESH_BASE_TIMEOUT_MS +
      Math.max(0, symbolsCount) * HOLDINGS_REFRESH_PER_SYMBOL_TIMEOUT_MS
  );
}

/**
 * Refresh holdings by coverage range
 */
export async function refreshHoldingsByCoverage(
  symbol: string,
  coverageType: string,
  coverageValue: number,
  expectedSymbolsCount?: number,
  progressToken?: string
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

  const estimatedSymbols = estimateRefreshSymbolsCount(
    coverageType,
    coverageValue,
    expectedSymbolsCount
  );
  const timeoutMs = calcHoldingsRefreshTimeoutMs(estimatedSymbols);

  return fetchApi<{
    status: string;
    symbol: string;
    coverage: string;
    stocks_count: number;
    total_weight: number;
    completeness: Record<string, unknown>;
    updated_stocks: Array<Record<string, unknown>>;
    message: string;
  }>(`/etfs/symbol/${symbol.toUpperCase()}/refresh-holdings-by-coverage`, {
    method: 'POST',
    timeout: timeoutMs,
    body: JSON.stringify({
      coverage_type: coverageType,
      coverage_value: coverageValue,
      ...(progressToken && progressToken.trim() !== '' ? { progress_token: progressToken } : {}),
    }),
  });
}

export interface HoldingsRefreshProgress {
  status: 'pending' | 'running' | 'completed' | 'error';
  symbol: string;
  coverage: string | null;
  completed: number;
  total: number;
  failed: number;
  current_item: string;
  message: string;
  progress_percentage: number;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

/**
 * Query real-time progress of refresh-holdings-by-coverage
 */
export async function getHoldingsRefreshProgress(
  symbol: string,
  progressToken: string
): Promise<HoldingsRefreshProgress> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('ETF symbol is required');
  }
  if (!progressToken || progressToken.trim() === '') {
    throw new Error('progressToken is required');
  }
  return fetchApi<HoldingsRefreshProgress>(
    `/etfs/symbol/${symbol.toUpperCase()}/refresh-holdings-progress/${encodeURIComponent(progressToken)}`,
    {
      timeout: 60000,
    }
  );
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
  return fetchApi<{
    status: string;
    etf_symbol: string;
    coverage: string;
    records_imported: number;
    breadth_metrics: Record<string, unknown>;
    validation: Record<string, unknown>;
  }>('/import/finviz', {
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
  return fetchApi<{
    status: string;
    records_imported: number;
    heat_distribution: Record<string, number>;
    data?: Array<Record<string, unknown>>;
  }>('/import/marketchameleon', {
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

export interface MarketSymbolSnapshotResponse {
  symbol?: string;
  price?: number;
  sma20?: number;
  sma50?: number;
  sma200?: number | null;
  dist_to_sma20?: number | null;
  dist_to_sma50?: number | null;
  return_20d?: number;
  sma20_slope?: number;
  date?: string;
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

/**
 * Get market symbol snapshot, e.g. SPY / QQQ
 */
export async function getMarketSymbolSnapshot(
  symbol: string
): Promise<MarketSymbolSnapshotResponse> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('symbol is required');
  }
  return fetchApi<MarketSymbolSnapshotResponse>(`/market/symbol/${symbol.toUpperCase()}`);
}

// ----------------------------------------------------------------------------
// Options Data APIs
// ----------------------------------------------------------------------------

/**
 * Options positioning data for a stock
 */
export interface OptionsPositioningData {
  bucket: string;        // 期限桶: "0-7天", "8-30天", "31-90天"
  callOI: number | null; // Call Open Interest 变化
  putOI: number | null;  // Put Open Interest 变化
  netOI: number | null;  // 净持仓变化
  delta3d?: number | null;
  delta5d?: number | null;
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
  iv60?: number | null;
  iv90?: number | null;
  iv30Change: number | null;
  
  // Term structure metrics
  termStructureScore: number;
  slope: number | null;
  slopeChange: number | null;
  termStructureInterpretation: string | null;
  earningsEvent: string | null;      // 财报事件日期
  
  // Positioning data
  positioning: OptionsPositioningData[];
  
  // Metadata
  dataSource: string;
  updatedAt: string | null;
}

function normalizeOptionsOverlayData(raw: unknown, fallbackSymbol: string): OptionsOverlayData {
  const source = isRecord(raw) ? raw : {};
  const toMaybeNumber = (value: unknown): number | null => {
    const parsed = toNumber(value);
    return parsed === undefined ? null : parsed;
  };

  const normalizePositioningRow = (value: unknown): OptionsPositioningData | null => {
    if (!isRecord(value)) return null;
    const bucket = toStringValue(value.bucket ?? value.term ?? value.range ?? value.label);
    if (!bucket) return null;
    const callOI = toMaybeNumber(value.callOI ?? value.call_oi);
    const putOI = toMaybeNumber(value.putOI ?? value.put_oi);
    const netOI = toMaybeNumber(value.netOI ?? value.net_oi) ?? (
      callOI != null && putOI != null ? callOI - putOI : null
    );
    const delta3d = toMaybeNumber(value.delta3d ?? value.delta_3d);
    const delta5d = toMaybeNumber(value.delta5d ?? value.delta_5d);
    const trend = toStringValue(value.trend ?? value.direction ?? value.signal) ?? (
      netOI == null ? '中性' : netOI >= 0 ? '偏多' : '偏空'
    );
    return {
      bucket,
      callOI,
      putOI,
      netOI,
      delta3d,
      delta5d,
      trend,
    };
  };

  const positioningRaw = Array.isArray(source.positioning)
    ? source.positioning
    : Array.isArray(source.positionings)
      ? source.positionings
      : [];

  return {
    symbol: toStringValue(source.symbol) ?? fallbackSymbol.toUpperCase(),
    heatScore: toNumber(source.heatScore ?? source.heat_score) ?? 0,
    heatType: toStringValue(source.heatType ?? source.heat_type)?.toLowerCase() ?? 'normal',
    relativeNominal: toMaybeNumber(source.relativeNominal ?? source.relative_nominal),
    relativeVolume: toMaybeNumber(source.relativeVolume ?? source.relative_volume),
    tradeCount: toStringValue(source.tradeCount ?? source.trade_count) ?? '--',
    riskScore: toNumber(source.riskScore ?? source.risk_score) ?? 0,
    ivr: toMaybeNumber(source.ivr),
    iv30: toMaybeNumber(source.iv30 ?? source.iv_30),
    iv60: toMaybeNumber(source.iv60 ?? source.iv_60),
    iv90: toMaybeNumber(source.iv90 ?? source.iv_90),
    iv30Change: toMaybeNumber(source.iv30Change ?? source.iv30_change),
    termStructureScore: toNumber(source.termStructureScore ?? source.term_structure_score) ?? 0,
    slope: toMaybeNumber(source.slope),
    slopeChange: toMaybeNumber(source.slopeChange ?? source.slope_change),
    termStructureInterpretation: toStringValue(source.termStructureInterpretation ?? source.term_structure_interpretation) ?? null,
    earningsEvent: toStringValue(source.earningsEvent ?? source.earnings_event ?? source.Earnings ?? source.earnings) ?? null,
    positioning: positioningRaw
      .map((item) => normalizePositioningRow(item))
      .filter((item): item is OptionsPositioningData => item !== null),
    dataSource: toStringValue(source.dataSource ?? source.data_source) ?? 'Database',
    updatedAt: toStringValue(source.updatedAt ?? source.updated_at) ?? null,
  };
}

/**
 * Get options overlay data for a stock
 * This fetches real-time options data from the backend
 */
export async function getOptionsOverlayData(symbol: string): Promise<OptionsOverlayData> {
  if (!symbol || symbol.trim() === '') {
    throw new Error('Stock symbol is required');
  }
  const response = await fetchApi<unknown>(`/stocks/symbol/${symbol.toUpperCase()}/options-overlay`);
  return normalizeOptionsOverlayData(response, symbol);
}
