import React, { useMemo } from 'react';

export interface TrendDataPoint {
  date: string;
  baseline: number;
  sector: number;
  industry: number;
  sectorVsBaseline: number;
  industryVsSector: number;
}

interface TrendChartProps {
  data: TrendDataPoint[];
  period: '3d' | '5d';
  onPeriodChange?: (period: '3d' | '5d') => void;
  baselineName?: string;
  sectorName?: string;
  industryName?: string;
}

export function TrendChart({
  data,
  period,
  onPeriodChange,
  baselineName = 'SPY',
  sectorName = 'XLK',
  industryName = 'SOXX',
}: TrendChartProps) {
  const chartWidth = 500;
  const chartHeight = 200;
  const padding = { top: 20, right: 60, bottom: 30, left: 50 };

  const { minValue, maxValue, baselinePoints, sectorPoints, industryPoints } = useMemo(() => {
    if (!data || data.length === 0) {
      return {
        minValue: 0,
        maxValue: 100,
        baselinePoints: '',
        sectorPoints: '',
        industryPoints: '',
      };
    }

    const allValues = data.flatMap((d) => [d.baseline, d.sector, d.industry]);
    const min = Math.min(...allValues);
    const max = Math.max(...allValues);
    const range = max - min || 1;
    const paddedMin = min - range * 0.1;
    const paddedMax = max + range * 0.1;

    const getX = (index: number) =>
      padding.left + (index / (data.length - 1)) * (chartWidth - padding.left - padding.right);
    const getY = (value: number) =>
      padding.top + ((paddedMax - value) / (paddedMax - paddedMin)) * (chartHeight - padding.top - padding.bottom);

    const createPoints = (key: 'baseline' | 'sector' | 'industry') =>
      data.map((d, i) => `${getX(i)},${getY(d[key])}`).join(' ');

    return {
      minValue: paddedMin,
      maxValue: paddedMax,
      baselinePoints: createPoints('baseline'),
      sectorPoints: createPoints('sector'),
      industryPoints: createPoints('industry'),
    };
  }, [data]);

  const yAxisTicks = useMemo(() => {
    const ticks = [];
    const step = (maxValue - minValue) / 4;
    for (let i = 0; i <= 4; i++) {
      ticks.push(minValue + step * i);
    }
    return ticks.reverse();
  }, [minValue, maxValue]);

  const gridLines = useMemo(() => {
    return yAxisTicks.map((tick) => {
      const y =
        padding.top +
        ((maxValue - tick) / (maxValue - minValue)) * (chartHeight - padding.top - padding.bottom);
      return y;
    });
  }, [yAxisTicks, maxValue, minValue]);

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold">趋势对比</h3>
        {onPeriodChange && (
          <div className="flex gap-1 bg-[var(--bg-tertiary)] p-1 rounded-[var(--radius-sm)]">
            <button
              onClick={() => onPeriodChange('3d')}
              className={`
                px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] transition-colors
                ${period === '3d'
                  ? 'bg-[var(--bg-primary)] text-[var(--text-primary)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                }
              `}
            >
              3天
            </button>
            <button
              onClick={() => onPeriodChange('5d')}
              className={`
                px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] transition-colors
                ${period === '5d'
                  ? 'bg-[var(--bg-primary)] text-[var(--text-primary)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                }
              `}
            >
              5天
            </button>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex gap-5 mb-4 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-3 h-0.5 bg-[#94a3b8] rounded-full" />
          <span className="text-[var(--text-muted)]">{baselineName} (基准)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-0.5 bg-[var(--accent-blue)] rounded-full" />
          <span className="text-[var(--text-muted)]">{sectorName} (板块)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-0.5 bg-[var(--accent-purple)] rounded-full" />
          <span className="text-[var(--text-muted)]">{industryName} (行业)</span>
        </div>
      </div>

      {/* Chart */}
      <div className="relative">
        <svg
          width="100%"
          height={chartHeight}
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Grid lines */}
          {gridLines.map((y, i) => (
            <line
              key={i}
              x1={padding.left}
              y1={y}
              x2={chartWidth - padding.right}
              y2={y}
              stroke="#e2e8f0"
              strokeWidth="1"
              strokeDasharray="4,4"
            />
          ))}

          {/* Y-axis labels */}
          {yAxisTicks.map((tick, i) => (
            <text
              key={i}
              x={padding.left - 10}
              y={gridLines[i] + 4}
              textAnchor="end"
              fontSize="10"
              fill="#94a3b8"
            >
              {tick.toFixed(1)}
            </text>
          ))}

          {/* X-axis labels */}
          {data.map((d, i) => (
            <text
              key={i}
              x={
                padding.left +
                (i / (data.length - 1)) * (chartWidth - padding.left - padding.right)
              }
              y={chartHeight - 10}
              textAnchor="middle"
              fontSize="10"
              fill="#94a3b8"
            >
              {d.date}
            </text>
          ))}

          {/* Baseline line */}
          {baselinePoints && (
            <polyline
              fill="none"
              stroke="#94a3b8"
              strokeWidth="2"
              points={baselinePoints}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Sector line */}
          {sectorPoints && (
            <polyline
              fill="none"
              stroke="var(--accent-blue)"
              strokeWidth="2.5"
              points={sectorPoints}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Industry line */}
          {industryPoints && (
            <polyline
              fill="none"
              stroke="var(--accent-purple)"
              strokeWidth="2.5"
              points={industryPoints}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Data points */}
          {data.map((d, i) => {
            const x =
              padding.left +
              (i / (data.length - 1)) * (chartWidth - padding.left - padding.right);
            const getY = (value: number) =>
              padding.top +
              ((maxValue - value) / (maxValue - minValue)) *
                (chartHeight - padding.top - padding.bottom);

            return (
              <g key={i}>
                <circle cx={x} cy={getY(d.baseline)} r="3" fill="#94a3b8" />
                <circle cx={x} cy={getY(d.sector)} r="4" fill="var(--accent-blue)" />
                <circle cx={x} cy={getY(d.industry)} r="4" fill="var(--accent-purple)" />
              </g>
            );
          })}
        </svg>
      </div>

      {/* Summary */}
      {data.length > 0 && (
        <div className="mt-4 pt-4 border-t border-[var(--border-light)]">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-[var(--text-muted)]">{sectorName} vs {baselineName}:</span>
              <span
                className={`ml-2 font-semibold ${
                  data[data.length - 1].sectorVsBaseline >= 0
                    ? 'text-[var(--accent-green)]'
                    : 'text-[var(--accent-red)]'
                }`}
              >
                {data[data.length - 1].sectorVsBaseline >= 0 ? '+' : ''}
                {data[data.length - 1].sectorVsBaseline.toFixed(2)}%
              </span>
            </div>
            <div>
              <span className="text-[var(--text-muted)]">{industryName} vs {sectorName}:</span>
              <span
                className={`ml-2 font-semibold ${
                  data[data.length - 1].industryVsSector >= 0
                    ? 'text-[var(--accent-green)]'
                    : 'text-[var(--accent-red)]'
                }`}
              >
                {data[data.length - 1].industryVsSector >= 0 ? '+' : ''}
                {data[data.length - 1].industryVsSector.toFixed(2)}%
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
