// Stock types
export interface StockScores {
  momentum: number;
  trend: number;
  volume: number;
  quality: number;
  options: number;
}

export interface StockChanges {
  delta3d: number | null;
  delta5d: number | null;
}

export interface StockMetrics {
  return20d: number;
  return63d: number;
  sma20Slope: number;
  ivr: number;
  iv30: number;
}

export interface Stock {
  id: number;
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  price: number;
  scoreTotal: number;
  scores: StockScores;
  changes: StockChanges;
  metrics: StockMetrics;
}

// ETF types
export interface ETFDelta {
  delta3d: number | null;
  delta5d: number | null;
}

// 新版本的 ETF 相关类型定义 - 参考 data_config_etf_panel.html 板块 ETF 设计
export interface RelMomentum {
  score: number;
  value: string;   // 如 '+12.3%'
  rank: number;
}

export interface TrendQuality {
  score: number;
  structure: string;  // 如 'Strong', 'Weak'
  slope: string;      // 如 '+0.08'
}

export interface Breadth {
  score: number;
  above50ma: string;   // 如 '75%'
  above200ma: string;  // 如 '68%'
}

export interface OptionsConfirm {
  score: number;
  heat: string;     // 如 'High', 'Very High'
  relVol: string;   // 如 '1.8x'
  ivr: number;
}

export interface Holding {
  ticker: string;
  weight: number;
}

export interface ETF {
  id: number;
  symbol: string;
  name: string;
  type: 'sector' | 'industry';
  score: number;
  rank: number;
  delta: ETFDelta;
  completeness: number;
  holdingsCount: number;
  // 新增字段 - 板块 ETF 详细分析
  compositeScore?: number;
  relMomentum?: RelMomentum;
  trendQuality?: TrendQuality;
  breadth?: Breadth;
  optionsConfirm?: OptionsConfirm;
  holdings?: Holding[];
  // 行业 ETF 额外字段
  parentSector?: string;  // 父板块符号 (后端返回的字段名)
  sector?: string;        // 别名，兼容旧代码
  sectorName?: string;
}

// Task types
export type TaskType = 'rotation' | 'drilldown' | 'momentum';

export interface Task {
  id: number;
  title: string;
  type: TaskType;
  baseIndex: string;
  sector?: string;
  etfs: string[];
  createdAt: string;
}

// API Response types
export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
}

// Navigation types
export type NavSection = 'core' | 'sector' | 'industry' | 'momentum' | 'tracking';