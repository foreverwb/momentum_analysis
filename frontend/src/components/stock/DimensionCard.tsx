import React, { memo, useMemo } from 'react';

interface Metric {
  label: string;
  value: string | number;
  variant?: 'default' | 'highlight' | 'warning' | 'muted';
}

interface DimensionCardProps {
  title: string;
  subtitle?: string;
  score: number;
  scoreColor: 'green' | 'amber' | 'blue' | 'purple' | 'orange';
  metrics: Metric[];
}

// 静态样式映射（移到组件外部避免重复创建）
const scoreColorClasses: Record<DimensionCardProps['scoreColor'], string> = {
  green: 'text-[var(--accent-green)]',
  amber: 'text-[var(--accent-amber)]',
  blue: 'text-[var(--accent-blue)]',
  purple: 'text-[var(--accent-purple)]',
  orange: 'text-[var(--accent-orange)]'
};

const metricValueClasses: Record<NonNullable<Metric['variant']>, string> = {
  default: 'text-[var(--text-primary)]',
  highlight: 'text-[var(--accent-green)]',
  warning: 'text-[var(--accent-amber)]',
  muted: 'text-[var(--text-muted)]'
};

/**
 * MetricRow - 单个指标行组件
 * 使用 memo 优化，避免不必要的重渲染
 */
const MetricRow = memo(function MetricRow({ metric }: { metric: Metric }) {
  return (
    <div className="flex items-center justify-between text-[13px]">
      <span className="text-[var(--text-secondary)]">{metric.label}</span>
      <span className={`font-medium ${metricValueClasses[metric.variant ?? 'default']}`}>
        {metric.value}
      </span>
    </div>
  );
});

/**
 * DimensionCard - 维度评分卡片组件
 * 
 * 性能优化:
 * - 使用 React.memo 避免父组件更新导致的不必要重渲染
 * - 静态样式映射移到组件外部
 * - 子组件 MetricRow 也使用 memo 优化
 */
export const DimensionCard = memo(function DimensionCard({ 
  title, 
  subtitle, 
  score, 
  scoreColor, 
  metrics 
}: DimensionCardProps) {
  // 使用 useMemo 缓存样式类名
  const scoreClassName = useMemo(
    () => `text-2xl font-bold ${scoreColorClasses[scoreColor]}`,
    [scoreColor]
  );

  return (
    <div className="bg-[var(--bg-secondary)] rounded-[var(--radius-md)] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3.5">
        <span className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]">
          {title}
          {subtitle && <span className="text-[var(--text-muted)]">({subtitle})</span>}
        </span>
        <span className={scoreClassName}>
          {score}
        </span>
      </div>

      {/* Metrics */}
      <div className="flex flex-col gap-2">
        {metrics.map((metric, index) => (
          <MetricRow key={`${metric.label}-${index}`} metric={metric} />
        ))}
      </div>
    </div>
  );
});
