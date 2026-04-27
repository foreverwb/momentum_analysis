/**
 * DataSourceBar — Card 5 of the center panel in DrilldownView.
 *
 * 职责：展示 4 个数据源（Finviz / MarketChameleon / IBKR 市场数据 / Futu 期权数据）
 *       的状态 pill，以及最后更新时间戳。
 *       状态从 task.sourceUpdatedAt 或 ETF detail 的 sourceUpdatedAt 推导：
 *         全部有时间戳 → OK；任一缺失 → pending。
 * 不做：数据拉取、用户交互。
 */
import React from 'react';

// ─── Data source definitions — 需求文档 §Card 5 ───────────────────────────────
const DATA_SOURCES = [
  'Finviz',
  'MarketChameleon',
  'IBKR 市场数据',
  'Futu 期权数据',
] as const;

type SourceStatus = 'ok' | 'pending';

const STATUS_STYLE: Record<SourceStatus, { bg: string; border: string; dot: string }> = {
  ok: {
    bg: 'rgba(34,197,94,0.07)',
    border: '1px solid rgba(34,197,94,0.2)',
    dot: '#22c55e',
  },
  pending: {
    bg: 'rgba(245,158,11,0.07)',
    border: '1px solid rgba(245,158,11,0.25)',
    dot: '#f59e0b',
  },
};

interface SourcePillProps {
  label: string;
  status: SourceStatus;
}

function SourcePill({ label, status }: SourcePillProps): React.ReactElement {
  const cfg = STATUS_STYLE[status];
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: 20,
        background: cfg.bg,
        border: cfg.border,
        flexShrink: 0,
      }}
    >
      {/* Status dot */}
      <div
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: cfg.dot,
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize: 11, color: '#475569', fontWeight: 500, whiteSpace: 'nowrap' }}>
        {label}
      </span>
    </div>
  );
}

function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${mm}/${dd} ${hh}:${min}`;
  } catch {
    return ts;
  }
}

export interface DataSourceBarProps {
  /** sourceUpdatedAt 来自 ETF detail 或 task — 每个 key 为数据源名，值为 ISO 时间戳或 null */
  sourceUpdatedAt?: Record<string, string | null>;
}

export function DataSourceBar({ sourceUpdatedAt }: DataSourceBarProps): React.ReactElement {
  // 根据 sourceUpdatedAt 推断每个数据源状态
  const sourceStatuses = DATA_SOURCES.map((src): SourceStatus => {
    if (!sourceUpdatedAt) return 'pending';
    const keys = Object.keys(sourceUpdatedAt);
    // 模糊匹配：key 包含数据源名称（忽略大小写、空格）
    const normalizedSrc = src.toLowerCase().replace(/\s+/g, '');
    const matchedKey = keys.find((k) =>
      k.toLowerCase().replace(/\s+/g, '').includes(normalizedSrc.slice(0, 5))
    );
    if (!matchedKey) return 'pending';
    return sourceUpdatedAt[matchedKey] ? 'ok' : 'pending';
  });

  // Newest timestamp among all present values
  const timestamps = sourceUpdatedAt
    ? Object.values(sourceUpdatedAt).filter((v): v is string => !!v)
    : [];
  const sorted = timestamps.slice().sort();
  const latestTs = sorted.length ? sorted[sorted.length - 1] : null;

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: 12,
        padding: '10px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}
    >
      {/* Label */}
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: '#475569',
          flexShrink: 0,
          whiteSpace: 'nowrap',
        }}
      >
        数据来源
      </span>

      {/* Pill badges */}
      {DATA_SOURCES.map((src, i) => (
        <SourcePill key={src} label={src} status={sourceStatuses[i]} />
      ))}

      {/* Timestamp right-aligned */}
      {latestTs && (
        <span
          style={{
            fontSize: 10,
            color: '#94a3b8',
            marginLeft: 'auto',
            whiteSpace: 'nowrap',
          }}
        >
          更新于 {formatTimestamp(latestTs)}
        </span>
      )}
    </div>
  );
}
