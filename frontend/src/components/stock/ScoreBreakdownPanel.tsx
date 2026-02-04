import React from 'react';

interface ScoreBreakdownPanelProps {
  title: string;
  icon: string | null;
  score: number | string | null | undefined;
  weight: string;  // 如 "40%"
  breakdown: Record<string, number | string | null | undefined>;  // 各项得分
  data: Record<string, unknown>;       // 原始数据
  description?: string;
  compact?: boolean;
  className?: string;
}

export function ScoreBreakdownPanel({
  title,
  icon,
  score,
  weight,
  breakdown,
  data,
  description,
  compact = false,
  className = '',
}: ScoreBreakdownPanelProps) {
  const getScoreColor = (score: number): string => {
    if (score >= 60) return 'var(--accent-green)';
    if (score >= 40) return 'var(--accent-amber)';
    return 'var(--accent-blue)';
  };

  const getScoreColorClass = (score: number): string => {
    if (score >= 60) return 'text-[var(--accent-green)]';
    if (score >= 40) return 'text-[var(--accent-amber)]';
    return 'text-[var(--accent-blue)]';
  };

  const toNumber = (value: unknown): number | null => {
    if (typeof value === 'number') {
      return Number.isNaN(value) ? null : value;
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) return null;
      const parsed = Number(trimmed);
      return Number.isNaN(parsed) ? null : parsed;
    }
    return null;
  };

  const formatValue = (value: unknown): string => {
    if (value === null || value === undefined) return '--';
    if (typeof value === 'number') {
      if (Number.isNaN(value)) return '--';
      return value.toFixed(2);
    }
    return String(value);
  };

  const formatMetricLabel = (key: string): string => {
    const labelMap: Record<string, string> = {
      // Price momentum
      'return_20d': '20日收益',
      'return_63d': '63日收益',
      'rs_20d': '相对强度',
      'dist_from_20d_high': '距20日高点',
      // Technical/Trend
      'price': '当前价格',
      'sma20': '20日均线',
      'sma50': '50日均线',
      'sma200': '200日均线',
      'rsi': 'RSI',
      'dist_from_52w_high': '距52周高点',
      'ma_alignment': '均线排列',
      'sma20_slope': '20DMA斜率',
      'trend_persistence': '趋势持续度',
      // Volume
      'volume': '成交量',
      'avg_volume': '平均成交量',
      'volume_ratio': '量比',
      'breakout_volume': '突破放量',
      'obv_trend': 'OBV趋势',
      // Options
      'heat_score': '热度评分',
      'risk_score': '风险评分',
      'heat_type': '热度类型',
      'ivr': 'IV排名',
      'implied_volatility': '隐含波动率',
      'open_interest': '持仓量',
    };
    return labelMap[key] || key;
  };

  const scoreValue = toNumber(score);
  const scoreColor = scoreValue === null ? 'var(--text-muted)' : getScoreColor(scoreValue);
  const scoreDisplay = scoreValue === null ? '--' : scoreValue.toFixed(1);

  return (
    <div
      className={`bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] ${
        compact ? 'p-4' : 'p-6'
      } ${compact ? '' : 'mb-6'} ${className}`}
    >
      {/* Header */}
      <div className={`flex items-center justify-between ${compact ? 'mb-4 pb-3' : 'mb-6 pb-4'} border-b border-[var(--border-light)]`}>
        <div className="flex items-center gap-3">
          <span className={compact ? 'text-xl' : 'text-2xl'}>{icon}</span>
          <div>
            <h3 className={`${compact ? 'text-base' : 'text-lg'} font-semibold text-[var(--text-primary)]`}>
              {title}
            </h3>
            {description && (
              <p className="text-sm text-[var(--text-muted)] mt-1">
                {description}
              </p>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-[var(--text-muted)] mb-1">
            权重: {weight}
          </div>
          <div 
            className={`${compact ? 'text-3xl' : 'text-4xl'} font-bold`}
            style={{ color: scoreColor }}
          >
            {scoreDisplay}
          </div>
        </div>
      </div>

      {/* Score Breakdown Table */}
      {Object.keys(breakdown).length > 0 && (
        <div className={compact ? 'mb-4' : 'mb-6'}>
          <h4 className="text-sm font-semibold text-[var(--text-secondary)] mb-3">
            评分细分
          </h4>
          <div className="space-y-1">
            {Object.entries(breakdown).map(([key, itemScore]) => {
              const numericScore = toNumber(itemScore);
              const clampedScore = numericScore === null
                ? 0
                : Math.min(100, Math.max(0, numericScore));
              const scoreClass = numericScore === null ? 'text-[var(--text-muted)]' : getScoreColorClass(clampedScore);
              const displayScore = numericScore === null ? '--' : Math.round(clampedScore).toString();

              return (
                <div 
                  key={key}
                  className={`flex items-center justify-between ${compact ? 'py-1' : 'py-1.5'} px-3 rounded-lg`}
                >
                  <span className="text-sm text-[var(--text-primary)]">
                    {formatMetricLabel(key)}
                  </span>
                  <span className={`text-sm font-semibold ${scoreClass}`}>
                    {displayScore}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Raw Data Table */}
      {Object.keys(data).length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-[var(--text-secondary)] mb-3">
            原始数据
          </h4>
          <div className={`grid ${compact ? 'grid-cols-1' : 'grid-cols-2'} gap-2`}>
            {Object.entries(data).map(([key, value]) => (
              <div 
                key={key}
                className={`flex items-center justify-between ${compact ? 'py-1' : 'py-1.5'} px-3 rounded-lg`}
              >
                <span className="text-xs text-[var(--text-muted)]">
                  {formatMetricLabel(key)}
                </span>
                <span className="text-sm font-medium text-[var(--text-primary)]">
                  {formatValue(value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
