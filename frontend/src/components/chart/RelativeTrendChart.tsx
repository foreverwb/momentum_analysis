import React, { useCallback, useEffect, useMemo, useState } from 'react';

export interface RelativeTrendSeries {
  symbol: string;
  values: Array<number | null>;
  color?: string;
}

export interface TrendMetricOption {
  value: string;
  label: string;
}

export type TrendSymbolRole = 'market' | 'sector' | 'industry' | 'stock' | 'other';

interface RelativeTrendChartProps {
  title?: string;
  dates: string[];
  series: RelativeTrendSeries[];
  comparisonPriceSeries?: RelativeTrendSeries[];
  comparisonSma20Series?: RelativeTrendSeries[];
  period: '5d' | '20d' | '63d';
  onPeriodChange?: (period: '5d' | '20d' | '63d') => void;
  metric?: string;
  metricOptions?: TrendMetricOption[];
  onMetricChange?: (metric: string) => void;
  valueFormatter?: (value: number) => string;
  baseSymbol?: string;
  symbolRoleMap?: Record<string, TrendSymbolRole>;
  isLoading?: boolean;
  loadingText?: string;
}

const DEFAULT_COLORS = ['#22c55e', '#3b82f6', '#8b5cf6', '#94a3b8', '#64748b', '#f59e0b'];
const MARKET_SYMBOLS = new Set(['SPY', 'QQQ', 'IWM', 'DIA']);
const SYMBOL_COLOR_OVERRIDES: Record<string, string> = {
  SPY: '#4472C4',
  QQQ: '#00B0A0',
};
const SPECTRUM_STOPS = ['#E53935', '#FB8C00', '#43A047', '#8E24AA', '#1E88E5', '#00ACC1'];
const ROLE_LABEL: Record<TrendSymbolRole, string> = {
  market: '大盘',
  sector: '板块',
  industry: '行业',
  stock: '个股',
  other: '',
};

const toPositiveHex = (color: string): string => {
  if (typeof color !== 'string') return '#3b82f6';
  const normalized = color.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(normalized)) return normalized;
  if (/^#[0-9a-fA-F]{3}$/.test(normalized)) {
    const [, r, g, b] = normalized;
    return `#${r}${r}${g}${g}${b}${b}`;
  }
  return '#3b82f6';
};

const toRgba = (hexColor: string, alpha: number): string => {
  const hex = toPositiveHex(hexColor).replace('#', '');
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const interpolateHexColor = (from: string, to: string, ratio: number): string => {
  const start = toPositiveHex(from).replace('#', '');
  const end = toPositiveHex(to).replace('#', '');
  const clamped = Math.max(0, Math.min(1, ratio));

  const r = Math.round(parseInt(start.slice(0, 2), 16) + (parseInt(end.slice(0, 2), 16) - parseInt(start.slice(0, 2), 16)) * clamped);
  const g = Math.round(parseInt(start.slice(2, 4), 16) + (parseInt(end.slice(2, 4), 16) - parseInt(start.slice(2, 4), 16)) * clamped);
  const b = Math.round(parseInt(start.slice(4, 6), 16) + (parseInt(end.slice(4, 6), 16) - parseInt(start.slice(4, 6), 16)) * clamped);

  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
};

const getSpectrumColorAt = (position: number): string => {
  const clamped = Math.max(0, Math.min(1, position));
  if (SPECTRUM_STOPS.length === 1) return SPECTRUM_STOPS[0];

  const segments = SPECTRUM_STOPS.length - 1;
  const scaled = clamped * segments;
  const leftIndex = Math.min(segments - 1, Math.floor(scaled));
  const ratio = scaled - leftIndex;
  return interpolateHexColor(SPECTRUM_STOPS[leftIndex], SPECTRUM_STOPS[leftIndex + 1], ratio);
};

const buildSpectrumPalette = (count: number): string[] => {
  if (count <= 0) return [];
  if (count === 1) return [SPECTRUM_STOPS[0]];
  return Array.from({ length: count }, (_, index) => getSpectrumColorAt(index / (count - 1)));
};

const normalizeMetricKey = (metric?: string): string => (metric || 'relative').toLowerCase().trim();

const sanitizeSymbolKey = (symbol: string): string => symbol.toUpperCase().trim();

export function RelativeTrendChart({
  title = '相对走势对比',
  dates,
  series,
  period,
  onPeriodChange,
  metric,
  metricOptions,
  onMetricChange,
  valueFormatter,
  baseSymbol,
  symbolRoleMap,
  isLoading = false,
  loadingText,
}: RelativeTrendChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [hiddenSymbols, setHiddenSymbols] = useState<Record<string, boolean>>({});
  const chartWidth = 1120;
  const chartHeight = 360;
  const padding = { top: 26, right: 56, bottom: 44, left: 56 };

  const resolvedSeries = useMemo(() => {
    const normalizedSymbols = series
      .map((item) => sanitizeSymbolKey(item.symbol || ''))
      .filter((symbol) => symbol !== '');
    const otherSymbols = Array.from(new Set(normalizedSymbols.filter((symbol) => !SYMBOL_COLOR_OVERRIDES[symbol])));
    const otherPalette = buildSpectrumPalette(otherSymbols.length);
    const otherColorMap: Record<string, string> = {};
    otherSymbols.forEach((symbol, index) => {
      otherColorMap[symbol] = otherPalette[index] || DEFAULT_COLORS[index % DEFAULT_COLORS.length];
    });

    return series.map((item, index) => {
      const symbol = sanitizeSymbolKey(item.symbol || '');
      const overriddenColor = SYMBOL_COLOR_OVERRIDES[symbol];
      return {
        symbol,
        values: Array.isArray(item.values) ? item.values : [],
        color: overriddenColor || otherColorMap[symbol] || DEFAULT_COLORS[index % DEFAULT_COLORS.length],
      };
    }).filter((item) => item.symbol !== '');
  }, [baseSymbol, series, symbolRoleMap]);

  const metricKey = normalizeMetricKey(metric);
  const isSma20ComparisonMode = metricKey === 'sma20';

  useEffect(() => {
    setHiddenSymbols((prev) => {
      const available = new Set(resolvedSeries.map((item) => item.symbol));
      const next: Record<string, boolean> = {};
      let changed = false;
      Object.entries(prev).forEach(([symbol, hidden]) => {
        if (hidden && available.has(symbol)) {
          next[symbol] = true;
          return;
        }
        if (hidden && !available.has(symbol)) {
          changed = true;
        }
      });
      if (!changed && Object.keys(prev).length === Object.keys(next).length) {
        return prev;
      }
      return next;
    });
  }, [resolvedSeries]);

  const visibleSeries = useMemo(
    () => resolvedSeries.filter((item) => !hiddenSymbols[item.symbol]),
    [hiddenSymbols, resolvedSeries]
  );

  const hasUnderlyingData =
    dates.length > 1 &&
    resolvedSeries.some((item) => item.values.some((value) => value !== null && !Number.isNaN(value)));

  const hasData =
    dates.length > 1 &&
    visibleSeries.some((item) => item.values.some((value) => value !== null && !Number.isNaN(value)));

  const chartDomain = useMemo(() => {
    const values = visibleSeries.flatMap(
      (item) => item.values.filter((v) => v !== null && !Number.isNaN(v)) as number[]
    );
    if (!values.length) {
      return { minValue: -2, maxValue: 10 };
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const includeZero = metricKey === 'relative' || metricKey === 'return20d' || metricKey === 'sma20';
    const rawMin = includeZero ? Math.min(0, min) : min;
    const rawMax = includeZero ? Math.max(0, max) : max;
    const range = rawMax - rawMin || 1;
    return {
      minValue: rawMin - range * 0.15,
      maxValue: rawMax + range * 0.15,
    };
  }, [metricKey, visibleSeries]);

  const minValue = chartDomain.minValue;
  const maxValue = chartDomain.maxValue;

  const getX = useCallback(
    (index: number): number =>
      padding.left + (index / Math.max(1, dates.length - 1)) * (chartWidth - padding.left - padding.right),
    [dates.length, padding.left, padding.right]
  );

  const getY = useCallback(
    (value: number): number =>
      padding.top + ((maxValue - value) / Math.max(1e-9, maxValue - minValue)) * (chartHeight - padding.top - padding.bottom),
    [maxValue, minValue, padding.bottom, padding.top]
  );

  const pointsBySeries = useMemo(() => {
    const points: Record<string, { x: number; y: number; index: number; value: number }[][]> = {};
    visibleSeries.forEach((item) => {
      const segments: { x: number; y: number; index: number; value: number }[][] = [];
      let current: { x: number; y: number; index: number; value: number }[] = [];
      item.values.forEach((value, index) => {
        if (value === null || Number.isNaN(value)) {
          if (current.length > 1) segments.push(current);
          current = [];
          return;
        }
        current.push({ x: getX(index), y: getY(value), index, value });
      });
      if (current.length > 1) segments.push(current);
      points[item.symbol] = segments;
    });
    return points;
  }, [getX, getY, visibleSeries]);

  const niceTicks = useMemo(() => {
    if (maxValue === minValue) {
      return [maxValue];
    }
    const niceNum = (range: number, round: boolean) => {
      const exponent = Math.floor(Math.log10(Math.abs(range)));
      const fraction = Math.abs(range) / Math.pow(10, exponent);
      let niceFraction = 1;
      if (round) {
        if (fraction < 1.5) niceFraction = 1;
        else if (fraction < 3) niceFraction = 2;
        else if (fraction < 7) niceFraction = 5;
        else niceFraction = 10;
      } else {
        if (fraction <= 1) niceFraction = 1;
        else if (fraction <= 2) niceFraction = 2;
        else if (fraction <= 5) niceFraction = 5;
        else niceFraction = 10;
      }
      return niceFraction * Math.pow(10, exponent);
    };

    const desiredTicks = 5;
    const range = niceNum(maxValue - minValue, false);
    const step = niceNum(range / (desiredTicks - 1), true);
    const niceMin = Math.floor(minValue / step) * step;
    const niceMax = Math.ceil(maxValue / step) * step;
    const ticks: number[] = [];
    for (let value = niceMin; value <= niceMax + step * 0.5; value += step) {
      ticks.push(Number(value.toFixed(6)));
    }
    return ticks;
  }, [maxValue, minValue]);

  const gridLines = useMemo(() => {
    return niceTicks.map((tick) => {
      return getY(tick);
    });
  }, [getY, niceTicks]);

  const xTicks = useMemo(() => {
    if (dates.length < 2) return [];
    return dates.map((_, index) => getX(index));
  }, [dates, getX]);

  const xLabelStep = useMemo(() => {
    if (dates.length <= 1) return 1;
    const maxLabels = 10;
    return Math.max(1, Math.ceil((dates.length - 1) / (maxLabels - 1)));
  }, [dates.length]);

  const baselineValue = minValue <= 0 && maxValue >= 0 ? 0 : minValue;
  const baselineY = getY(baselineValue);

  const buildSmoothPath = (points: { x: number; y: number }[]) => {
    if (points.length === 0) return '';
    if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const c1x = p1.x + (p2.x - p0.x) / 6;
      const c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6;
      const c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
    }
    return d;
  };

  const formatValue =
    valueFormatter ?? ((value: number) => `${value.toFixed(1)}%`);

  const getSymbolRole = useCallback((symbol: string): TrendSymbolRole => {
    const key = sanitizeSymbolKey(symbol);
    const fromMap = symbolRoleMap?.[key];
    if (fromMap) return fromMap;
    if (baseSymbol && key === sanitizeSymbolKey(baseSymbol)) return 'market';
    if (MARKET_SYMBOLS.has(key)) return 'market';
    return 'other';
  }, [baseSymbol, symbolRoleMap]);

  const getSymbolDisplayLabel = useCallback((symbol: string): string => {
    const role = getSymbolRole(symbol);
    const suffix = ROLE_LABEL[role];
    return suffix ? `${symbol} (${suffix})` : symbol;
  }, [getSymbolRole]);

  const formatLegendValue = useCallback((value: number | null): string => {
    if (value === null || Number.isNaN(value)) return '--';
    if (metricKey === 'relative' || metricKey === 'return20d' || metricKey === 'sma20') {
      const signed = value > 0 ? `+${value.toFixed(1)}` : value.toFixed(1);
      return `${signed}%`;
    }
    if (metricKey === 'score') return value.toFixed(1);
    return value.toFixed(2);
  }, [metricKey]);

  const toggleSeriesVisibility = useCallback((symbol: string) => {
    setHiddenSymbols((prev) => {
      if (prev[symbol]) {
        const next = { ...prev };
        delete next[symbol];
        return next;
      }
      return {
        ...prev,
        [symbol]: true,
      };
    });
    setHoveredIndex(null);
  }, []);

  const legendRows = useMemo(() => {
    return resolvedSeries.map((item) => {
      const validValues = item.values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
      const lastValue = validValues.length > 0 ? validValues[validValues.length - 1] : null;
      const deltaValue = metricKey === 'relative' || metricKey === 'return20d' || metricKey === 'sma20'
        ? lastValue
        : validValues.length > 1
          ? lastValue! - validValues[0]
          : null;
      return {
        symbol: item.symbol,
        color: item.color,
        label: getSymbolDisplayLabel(item.symbol),
        value: lastValue,
        delta: deltaValue,
        isVisible: !hiddenSymbols[item.symbol],
      };
    });
  }, [getSymbolDisplayLabel, hiddenSymbols, metricKey, resolvedSeries]);

  const hoveredX = hoveredIndex !== null && hoveredIndex >= 0 && hoveredIndex < xTicks.length
    ? xTicks[hoveredIndex]
    : null;

  const hoveredRows = useMemo(() => {
    if (hoveredIndex === null || hoveredIndex < 0) return [];
    return visibleSeries
      .map((item) => {
        const raw = item.values[hoveredIndex];
        if (raw === null || raw === undefined || Number.isNaN(raw)) return null;
        return {
          symbol: item.symbol,
          label: getSymbolDisplayLabel(item.symbol),
          color: item.color,
          value: raw,
          y: getY(raw),
        };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null)
      .sort((a, b) => b.value - a.value);
  }, [getSymbolDisplayLabel, getY, hoveredIndex, visibleSeries]);

  const tooltipRect = useMemo(() => {
    if (hoveredX === null || hoveredRows.length === 0) return null;
    const width = 196;
    const height = 36 + hoveredRows.length * 22;
    const preferredX = hoveredX + 14;
    const leftLimit = padding.left + 4;
    const rightLimit = chartWidth - padding.right - width;
    const x = Math.min(rightLimit, Math.max(leftLimit, preferredX > rightLimit ? hoveredX - width - 14 : preferredX));

    const highestPoint = Math.min(...hoveredRows.map((row) => row.y));
    const topLimit = padding.top + 6;
    const bottomLimit = chartHeight - padding.bottom - height - 6;
    const y = Math.max(topLimit, Math.min(bottomLimit, highestPoint - height - 10));
    return { x, y, width, height };
  }, [chartHeight, chartWidth, hoveredRows, hoveredX, padding.bottom, padding.left, padding.right, padding.top]);

  const onPointerMove = useCallback((event: React.MouseEvent<SVGRectElement>) => {
    if (dates.length < 2) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = (event.clientX - rect.left) / rect.width;
    const svgX = ratio * chartWidth;
    const normalized = (svgX - padding.left) / Math.max(1e-9, chartWidth - padding.left - padding.right);
    const index = Math.round(normalized * (dates.length - 1));
    const clamped = Math.max(0, Math.min(dates.length - 1, index));
    setHoveredIndex(clamped);
  }, [chartWidth, dates.length, padding.left, padding.right]);

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2.5">
          <span className="text-base font-semibold">{title}</span>
          <span className="text-xs px-2 py-1 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
            {period === '5d' ? '5日' : period === '20d' ? '20日' : '63日'}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          {metricOptions && metricOptions.length > 0 && onMetricChange && (
            <div className="flex gap-1 bg-[var(--bg-tertiary)] p-1 rounded-[var(--radius-sm)]">
              {metricOptions.map((option) => (
                <button
                  key={option.value}
                  onClick={() => onMetricChange(option.value)}
                  className={`
                    px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] transition-colors
                    ${metric === option.value
                      ? 'bg-[var(--accent-blue)] text-white shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                    }
                  `}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}
          {onPeriodChange && (
            <div className="flex gap-1 bg-[var(--bg-tertiary)] p-1 rounded-[var(--radius-sm)]">
              {(['5d', '20d', '63d'] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => onPeriodChange(option)}
                  className={`
                    px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] transition-colors
                    ${period === option
                      ? 'bg-[var(--accent-blue)] text-white shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                    }
                  `}
                >
                  {option === '5d' ? '5日' : option === '20d' ? '20日' : '63日'}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {isSma20ComparisonMode && (
        <div className="text-xs text-[var(--text-muted)] mb-2">
          价格相对20DMA偏离度（%） 正值：价格高于20DMA；负值：价格低于20DMA
        </div>
      )}

      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: `${chartWidth} / ${chartHeight}`, minHeight: 260 }}
      >
        {isLoading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[var(--bg-primary)]/60 backdrop-blur-[1px] rounded-[var(--radius-md)]">
            <div className="flex items-center gap-2.5">
              <svg className="animate-spin h-4 w-4 text-[var(--accent-blue)]" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" opacity="0.2" />
                <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
              </svg>
              <span className="text-sm text-[var(--text-muted)]">{loadingText || '加载中...'}</span>
            </div>
          </div>
        )}
        {!hasData && !isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-[var(--text-muted)]">
            {!hasUnderlyingData ? '暂无可用走势数据' : '当前已隐藏全部曲线，请点击下方图例显示'}
          </div>
        ) : (
          <svg width="100%" height="100%" viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="xMidYMid meet">
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

            {xTicks.map((x, i) => (
              <line
                key={`x-${i}`}
                x1={x}
                y1={padding.top}
                x2={x}
                y2={chartHeight - padding.bottom}
                stroke="#e5e7eb"
                strokeWidth="1"
              />
            ))}

            {niceTicks.map((tick, i) => (
              <text
                key={i}
                x={padding.left - 10}
                y={gridLines[i] + 4}
                textAnchor="end"
                fontSize="11"
                fill="#64748b"
              >
                {formatValue(tick)}
              </text>
            ))}

            {dates.map((label, i) => {
              const isLast = i === dates.length - 1;
              const shouldShow = i % xLabelStep === 0 || isLast;
              if (!shouldShow) {
                return null;
              }
              return (
                <text
                  key={`${label}-${i}`}
                  x={getX(i)}
                  y={chartHeight - 18}
                  textAnchor="middle"
                  fontSize="11"
                  fill="#64748b"
                >
                  {label}
                </text>
              );
            })}

            {baselineValue === 0 && (
              <line
                x1={padding.left}
                y1={baselineY}
                x2={chartWidth - padding.right}
                y2={baselineY}
                stroke="#94a3b8"
                strokeWidth="1.2"
              />
            )}

            {visibleSeries.map((item) =>
              (pointsBySeries[item.symbol] || []).map((segment, idx) => (
                <path
                  key={`${item.symbol}-line-${idx}`}
                  d={buildSmoothPath(segment)}
                  fill="none"
                  stroke={item.color}
                  strokeWidth="1.35"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ))
            )}

            {hoveredX !== null && (
              <line
                x1={hoveredX}
                y1={padding.top}
                x2={hoveredX}
                y2={chartHeight - padding.bottom}
                stroke="#334155"
                strokeWidth="1.1"
                strokeDasharray="4,3"
                opacity="0.55"
              />
            )}

            {hoveredRows.map((row) => (
              <g key={`hover-point-${row.symbol}`}>
                <circle cx={hoveredX ?? 0} cy={row.y} r="5.5" fill={toRgba(row.color, 0.14)} />
                <circle cx={hoveredX ?? 0} cy={row.y} r="4" fill="#ffffff" stroke={row.color} strokeWidth="1.6" />
              </g>
            ))}

            {tooltipRect && hoveredIndex !== null && hoveredRows.length > 0 && (
              <g>
                <rect
                  x={tooltipRect.x}
                  y={tooltipRect.y}
                  width={tooltipRect.width}
                  height={tooltipRect.height}
                  rx="8"
                  fill="#0f172a"
                  opacity="0.92"
                  stroke="#1e293b"
                  strokeWidth="1"
                />
                <text x={tooltipRect.x + 12} y={tooltipRect.y + 20} fill="#f8fafc" fontSize="12" fontWeight="700">
                  {dates[hoveredIndex]}
                </text>
                {hoveredRows.map((row, rowIndex) => (
                  <g key={`tooltip-row-${row.symbol}`} transform={`translate(${tooltipRect.x + 12}, ${tooltipRect.y + 35 + rowIndex * 20})`}>
                    <rect x={0} y={-9} width={11} height={11} fill={row.color} />
                    <text x={16} y={0} fill="#cbd5e1" fontSize="11.5">
                      {row.label}: {formatLegendValue(row.value)}
                    </text>
                  </g>
                ))}
              </g>
            )}

            <rect
              x={padding.left}
              y={padding.top}
              width={chartWidth - padding.left - padding.right}
              height={chartHeight - padding.top - padding.bottom}
              fill="transparent"
              onMouseMove={onPointerMove}
              onMouseLeave={() => setHoveredIndex(null)}
            />
          </svg>
        )}
      </div>

      {hasUnderlyingData && (
        <div className="mt-4 rounded-[var(--radius-md)] bg-[var(--bg-tertiary)] px-4 py-3">
          <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2">
            {legendRows.map((row) => {
              const delta = row.delta;
              const isDown = typeof delta === 'number' && delta < 0;
              const valueClass = isDown
                ? 'text-[var(--accent-red)]'
                : 'text-[var(--text-secondary)]';
              const valueStyle =
                !isDown && row.isVisible
                  ? ({ color: row.color } as React.CSSProperties)
                  : undefined;
              return (
                <button
                  key={`legend-${row.symbol}`}
                  type="button"
                  onClick={() => toggleSeriesVisibility(row.symbol)}
                  aria-pressed={row.isVisible}
                  className={`flex items-center gap-2.5 text-sm min-w-0 rounded-[var(--radius-sm)] px-2 py-1 transition-opacity ${
                    row.isVisible
                      ? 'opacity-100 hover:opacity-85'
                      : 'opacity-45 hover:opacity-70'
                  }`}
                  title={row.isVisible ? '点击隐藏曲线' : '点击显示曲线'}
                >
                  <span
                    className="w-4 h-4 rounded-[4px] flex-shrink-0"
                    style={{ backgroundColor: row.color }}
                  />
                  <span className="font-semibold text-[var(--text-primary)] truncate">{row.label}</span>
                  <span className={`font-semibold ${valueClass}`} style={valueStyle}>
                    {formatLegendValue(row.value)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}