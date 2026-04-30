/**
 * ChainSignalBar — 产业链三维共振信号条（Phase 4 DD-8）。
 *
 * 职责：渲染上游共振 / 同层扩散 / 下游确认 三个 badge + 综合标签。
 * 样式严格对齐 HTML prototype L961-978。
 *
 * 不做：数据拉取（由父组件传入 signals prop）。
 */
import type { ChainSignalResult } from '../../types';

// ─── 信号 badge 定义 ──────────────────────────────────────────────────────────
const SIGNAL_DEFS: Array<{ label: string; key: keyof Pick<ChainSignalResult, 'upstream' | 'broad' | 'downstream'> }> = [
  { label: '上游共振', key: 'upstream' },
  { label: '同层扩散', key: 'broad' },
  { label: '下游确认', key: 'downstream' },
];

interface ChainSignalBarProps {
  signals: ChainSignalResult | null;
}

export function ChainSignalBar({ signals }: ChainSignalBarProps) {
  if (!signals) return null;

  return (
    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
      {SIGNAL_DEFS.map(({ label, key }) => {
        const ok = signals[key];
        return (
          <div
            key={label}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '4px 10px',
              borderRadius: 20,
              background: ok ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.07)',
              border: `1px solid ${ok ? 'rgba(34,197,94,0.22)' : 'rgba(245,158,11,0.22)'}`,
            }}
          >
            <span style={{ fontSize: 11, color: ok ? '#059669' : '#d97706', fontWeight: 700 }}>
              {ok ? '✓' : '○'}
            </span>
            <span style={{ fontSize: 11, color: ok ? '#059669' : '#d97706', fontWeight: 500 }}>
              {label}
            </span>
          </div>
        );
      })}
      <div
        style={{
          padding: '4px 12px',
          borderRadius: 20,
          fontSize: 12,
          fontWeight: 700,
          color: signals.color,
          // hex18 = hex + '18' approximates 10% opacity overlay without rgba
          background: `${signals.color}18`,
          border: `1px solid ${signals.color}40`,
        }}
      >
        {signals.label}
      </div>
    </div>
  );
}
