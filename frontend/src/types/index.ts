// ============================================================================
// Type Definitions for Momentum Analysis Frontend
// ============================================================================

// ----------------------------------------------------------------------------
// Heat Type Classification
// ----------------------------------------------------------------------------
export type HeatType = 'trend' | 'event' | 'hedge' | 'normal';

// ----------------------------------------------------------------------------
// Threshold Check Results
// ----------------------------------------------------------------------------
export interface ThresholdResult {
  price_above_sma50: 'PASS' | 'FAIL' | 'NO_DATA';
  rs_positive: 'PASS' | 'FAIL' | 'NO_DATA';
}

// ----------------------------------------------------------------------------
// Base Stock Interface
// ----------------------------------------------------------------------------
export interface Stock {
  symbol: string;
  name: string;
  sector?: string;
  industry?: string;
  
  // Price data
  price: number;
  change?: number;
  changePercent?: number;
  
  // Technical indicators
  sma20?: number;
  sma50?: number;
  sma200?: number;
  rsi?: number;
  
  // Momentum metrics
  return20d?: number;
  return63d?: number;
  rs20d?: number | null;
  
  // Volume metrics
  volume?: number;
  avgVolume?: number;
  volumeRatio?: number;
  
  // Options metrics
  impliedVolatility?: number;
  ivr?: number | null;
  openInterest?: number;
  
  // Composite scores
  totalScore?: number;
  technicalScore?: number;
  momentumScore?: number;
  volumeScore?: number;
  optionsScore?: number;
  
  // Heat analysis (new fields)
  heatType?: HeatType;
  heatScore?: number;
  riskScore?: number;
  thresholdsPass?: boolean;
  thresholds?: ThresholdResult;
  
  // Metadata
  lastUpdated?: string;
  marketCap?: number;
}

// ----------------------------------------------------------------------------
// Score Breakdown Interfaces
// ----------------------------------------------------------------------------
export interface TechnicalScoreData {
  price: number;
  sma20: number;
  sma50: number;
  sma200: number | null;
  rsi: number;
  dist_from_52w_high: number;
  score_breakdown: Record<string, number>;
}

export interface TechnicalScore {
  score: number;
  data: TechnicalScoreData;
}

export interface MomentumScoreData {
  return_20d: number;
  return_63d: number;
  rs_20d: number | null;
}

export interface MomentumScore {
  score: number;
  data: MomentumScoreData;
}

export interface VolumeScoreData {
  volume: number;
  avg_volume: number;
  volume_ratio: number;
  [key: string]: unknown;
}

export interface VolumeScore {
  score: number;
  data: VolumeScoreData;
}

export interface OptionsScoreData {
  heat_score: number;
  risk_score: number;
  heat_type: string;
  ivr: number | null;
  implied_volatility?: number;
  open_interest?: number;
}

export interface OptionsScore {
  score: number;
  data: OptionsScoreData;
}

export interface ScoreBreakdown {
  technical: TechnicalScore;
  momentum: MomentumScore;
  volume: VolumeScore;
  options: OptionsScore;
}

// ----------------------------------------------------------------------------
// Stock Detail Interface (Extended with Score Breakdown)
// ----------------------------------------------------------------------------
export interface StockDetail extends Stock {
  scoreBreakdown: ScoreBreakdown;
}

// ----------------------------------------------------------------------------
// Compare Data Interface
// ----------------------------------------------------------------------------
export interface CompareData {
  stocks: StockDetail[];
  metrics: string[];  // List of metrics to compare
}

// ----------------------------------------------------------------------------
// API Response Types
// ----------------------------------------------------------------------------
export interface ApiResponse<T> {
  data: T;
  status: 'success' | 'error';
  message?: string;
  timestamp?: string;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

// ----------------------------------------------------------------------------
// Filter and Query Parameters
// ----------------------------------------------------------------------------
export interface StockFilters {
  sector?: string;
  industry?: string;
  heatType?: HeatType;
  minScore?: number;
  maxScore?: number;
  minPrice?: number;
  maxPrice?: number;
  thresholdsPass?: boolean;
}

export interface StockQueryParams extends StockFilters {
  limit?: number;
  offset?: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
}

// ----------------------------------------------------------------------------
// Heat Analysis Types
// ----------------------------------------------------------------------------
export interface HeatAnalysis {
  heatType: HeatType;
  heatScore: number;
  riskScore: number;
  characteristics: string[];
  recommendation?: string;
}

// ----------------------------------------------------------------------------
// Sector Summary Types
// ----------------------------------------------------------------------------
export interface SectorSummary {
  sector: string;
  stockCount: number;
  avgScore: number;
  topStocks: Stock[];
  heatDistribution: Record<HeatType, number>;
}

// ----------------------------------------------------------------------------
// Watchlist Types
// ----------------------------------------------------------------------------
export interface WatchlistItem {
  id: string;
  symbol: string;
  addedAt: string;
  notes?: string;
  alerts?: Alert[];
}

export interface Alert {
  id: string;
  type: 'price' | 'score' | 'heat';
  condition: 'above' | 'below';
  threshold: number;
  active: boolean;
}

// ----------------------------------------------------------------------------
// Chart Data Types
// ----------------------------------------------------------------------------
export interface TimeSeriesData {
  date: string;
  value: number;
}

export interface ChartDataPoint {
  timestamp: string;
  price: number;
  volume?: number;
  sma20?: number;
  sma50?: number;
  sma200?: number;
}

// ----------------------------------------------------------------------------
// Error Types
// ----------------------------------------------------------------------------
export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

// ----------------------------------------------------------------------------
// User Preferences
// ----------------------------------------------------------------------------
export interface UserPreferences {
  defaultView: 'table' | 'cards' | 'chart';
  defaultSortBy: string;
  defaultFilters: StockFilters;
  watchlist: string[];
  notifications: {
    enabled: boolean;
    types: string[];
  };
}

// ----------------------------------------------------------------------------
// Type Guards
// ----------------------------------------------------------------------------
export function isStockDetail(stock: Stock | StockDetail): stock is StockDetail {
  return 'scoreBreakdown' in stock;
}

export function isHeatType(value: string): value is HeatType {
  return ['trend', 'event', 'hedge', 'normal'].includes(value);
}

export function hasThresholds(stock: Stock): stock is Stock & { thresholds: ThresholdResult } {
  return stock.thresholds !== undefined;
}

// ----------------------------------------------------------------------------
// ETF Types
// ----------------------------------------------------------------------------

export interface Holding {
  ticker: string;
  weight: number;
  score?: number | null;
  updatedAt?: string | null;
}

export interface ETFDelta {
  delta3d: number | null;
  delta5d: number | null;
}

export interface ETFDimensionScore {
  score: number;
  value?: string | number;
  rank?: number;
  structure?: string;
  slope?: string | number;
  above50ma?: string | number;
  above200ma?: string | number;
  heat?: string;
  relVol?: string | number;
}

export interface ETF {
  id: string;
  symbol: string;
  name: string;
  type: 'sector' | 'industry';
  parentSector?: string;
  
  // Scores
  score: number;
  compositeScore?: number;
  rank: number;
  
  // Delta tracking
  delta?: ETFDelta;
  
  // Data quality
  completeness: number;
  holdingsCount: number;
  
  // Detailed dimension scores (optional, only when calculated)
  relMomentum?: ETFDimensionScore;
  trendQuality?: ETFDimensionScore;
  breadth?: ETFDimensionScore;
  optionsConfirm?: ETFDimensionScore;
  
  // Holdings data
  holdings?: Holding[];
  
  // Metadata
  lastUpdated?: string;
}

export type TaskType = 'rotation' | 'drilldown' | 'momentum';

export interface Task {
  id: string;
  title: string;
  type: TaskType;
  baseIndex: 'SPY' | 'QQQ' | 'IWM';
  sector?: string;
  etfs: string[];
  createdAt: string;
  updatedAt?: string;
  status?: 'active' | 'paused' | 'completed';
}

export interface CreateTaskInput {
  title: string;
  type: TaskType;
  baseIndex: 'SPY' | 'QQQ' | 'IWM';
  sector?: string;
  etfs: string[];
}

export interface RefreshResult {
  status: 'success' | 'error' | 'partial' | 'snapshot';
  symbol: string;
  message?: string;
  score?: number;
  thresholds_pass?: boolean;
  breakdown?: Record<string, number>;
  completeness?: number;
  data_sources?: Record<string, boolean>;
}