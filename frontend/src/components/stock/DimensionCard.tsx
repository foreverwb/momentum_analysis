import React from 'react';

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

export function DimensionCard({ 
  title, 
  subtitle, 
  score, 
  scoreColor, 
  metrics 
}: DimensionCardProps) {
  const scoreColorClasses = {
    green: 'text-[var(--accent-green)]',
    amber: 'text-[var(--accent-amber)]',
    blue: 'text-[var(--accent-blue)]',
    purple: 'text-[var(--accent-purple)]',
    orange: 'text-[var(--accent-orange)]'
  };

  const metricValueClasses = {
    default: 'text-[var(--text-primary)]',
    highlight: 'text-[var(--accent-green)]',
    warning: 'text-[var(--accent-amber)]',
    muted: 'text-[var(--text-muted)]'
  };

  return (
    <div className="bg-[var(--bg-secondary)] rounded-[var(--radius-md)] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3.5">
        <span className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]">
          {title}
          {subtitle && <span className="text-[var(--text-muted)]">({subtitle})</span>}
        </span>
        <span className={`text-2xl font-bold ${scoreColorClasses[scoreColor]}`}>
          {score}
        </span>
      </div>

      {/* Metrics */}
      <div className="flex flex-col gap-2">
        {metrics.map((metric, index) => (
          <div key={index} className="flex items-center justify-between text-[13px]">
            <span className="text-[var(--text-secondary)]">{metric.label}</span>
            <span className={`font-medium ${metricValueClasses[metric.variant ?? 'default']}`}>
              {metric.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
