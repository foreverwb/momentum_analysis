/**
 * NodeHoldingsTable — Card 4 of the center panel in DrilldownView.
 *
 * 职责：可排序持仓表格，默认按动能分降序，8 行截断 + 展开全部按钮。
 *       偶数行浅灰背景，hover 蓝色高亮，行点击回调 onRowClick(ticker)。
 * 不做：数据拉取（holdings 由父组件传入）、状态持久化。
 */
import React, { useMemo, useState } from 'react';
import type { NodeHolding, NodeProxyType } from '../../types';
import { scoreTierColor, deltaColor } from './nodeStyles';

// ─── Row count before truncation — 需求文档 §Card 4 ───────────────────────────
const DEFAULT_ROWS = 8;

// ─── Status pill config — 需求文档 §Card 4 Status badges ──────────────────────
const STATUS_CFG: Record<string, { label: string; bg: string; color: string }> = {
  complete: { label: '已更新', bg: 'rgba(34,197,94,0.1)',  color: '#16a34a' },
  pending:  { label: '待计算', bg: 'rgba(245,158,11,0.1)', color: '#d97706' },
  missing:  { label: '缺失',   bg: 'rgba(239,68,68,0.1)',  color: '#dc2626' },
};

type SortKey = keyof Pick<NodeHolding, 'weight' | 'score' | 'return20d' | 'rs20d' | 'delta3d' | 'delta5d'>;

const SORT_KEYS: SortKey[] = ['weight', 'score', 'return20d', 'rs20d', 'delta3d', 'delta5d'];

function fmtPctDirect(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--';
  return (v > 0 ? '+' : '') + v.toFixed(1) + '%';
}

function fmtDeltaNum(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--';
  return (v > 0 ? '+' : '') + v.toFixed(1);
}

function SortArrow({ active, asc }: { active: boolean; asc: boolean }): React.ReactElement {
  return (
    <span style={{ marginLeft: 2, opacity: active ? 1 : 0.3, fontSize: 9 }}>
      {active && asc ? '▲' : '▼'}
    </span>
  );
}

// ─── Compact mode: top-5 rows, no thead, no sort — NodeDetailPanel 侧边栏嵌入用 ──
const COMPACT_ROWS = 5;

export interface NodeHoldingsTableProps {
  holdings: NodeHolding[];
  showAll: boolean;
  onShowAll: () => void;
  onRowClick?: (ticker: string) => void;
  isLoading: boolean;
  nodeProxyType?: NodeProxyType;
  nodeProxy?: string | null;
  nodeProxyLabel?: string | null;
  /** compact 模式：仅渲 top 5，无表头无排序，列：# ticker name score 20D% 权重% 状态 */
  compact?: boolean;
}

export function NodeHoldingsTable({
  holdings,
  showAll,
  onShowAll,
  onRowClick,
  isLoading,
  nodeProxyType,
  nodeProxy,
  compact = false,
}: NodeHoldingsTableProps): React.ReactElement {
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortAsc, setSortAsc] = useState(false);
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);

  const sorted = useMemo(() => {
    return [...holdings].sort((a, b) => {
      const va = (a[sortKey] as number) ?? 0;
      const vb = (b[sortKey] as number) ?? 0;
      return sortAsc ? va - vb : vb - va;
    });
  }, [holdings, sortKey, sortAsc]);

  const displayed = showAll ? sorted : sorted.slice(0, DEFAULT_ROWS);
  const remaining = sorted.length - DEFAULT_ROWS;

  // computed unconditionally to satisfy Rules of Hooks
  const top5 = useMemo(
    () => [...holdings].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, COMPACT_ROWS),
    [holdings],
  );

  // ── Compact mode: top-5 by score, no thead/sort ────────────────────────────
  if (compact) {
    if (isLoading) {
      return (
        <div style={{ padding: '8px 0', textAlign: 'center', color: '#94a3b8', fontSize: 12 }}>
          加载中…
        </div>
      );
    }
    if (top5.length === 0) return <></>;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {top5.map((h, i) => {
          const sc = STATUS_CFG[h.status ?? 'missing'] ?? STATUS_CFG.missing;
          const tierColor = scoreTierColor(h.score ?? 0);
          return (
            <div
              key={h.ticker}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '5px 6px', borderRadius: 7, background: '#f8fafc',
                cursor: onRowClick ? 'pointer' : 'default',
              }}
              onClick={() => onRowClick?.(h.ticker)}
            >
              <span style={{ fontSize: 10, color: '#94a3b8', minWidth: 14, textAlign: 'center' }}>
                #{i + 1}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b' }}>{h.ticker}</div>
                <div style={{
                  fontSize: 10, color: '#94a3b8',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {h.name ?? ''}
                </div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: tierColor, fontVariantNumeric: 'tabular-nums' }}>
                  {(h.score ?? 0).toFixed(1)}
                </div>
                <div style={{ fontSize: 10, color: deltaColor(h.return20d), fontVariantNumeric: 'tabular-nums' }}>
                  {fmtPctDirect(h.return20d)}
                </div>
              </div>
              <div style={{ width: 36, textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 10, color: '#475569', fontVariantNumeric: 'tabular-nums' }}>
                  {h.weight.toFixed(1)}%
                </div>
                <span style={{
                  fontSize: 10, padding: '1px 5px', borderRadius: 4,
                  background: sc.bg, color: sc.color, fontWeight: 500,
                }}>
                  {sc.label}
                </span>
              </div>
            </div>
          );
        })}
        {holdings.length > COMPACT_ROWS && (
          <div style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', paddingTop: 2 }}>
            +{holdings.length - COMPACT_ROWS} 只标的
          </div>
        )}
      </div>
    );
  }

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  const colHeaderStyle: React.CSSProperties = {
    fontSize: 11,
    color: '#64748b',
    fontWeight: 600,
    cursor: 'pointer',
    userSelect: 'none',
    whiteSpace: 'nowrap',
    padding: '7px 10px',
  };

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: 16,
        padding: '16px 20px',
      }}
    >
      {/* Section header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>持仓标的</span>
          <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>
            {nodeProxyType === 'etf' && nodeProxy
              ? `${nodeProxy} 成分股 · 共 ${holdings.length} 只`
              : nodeProxyType === 'synthetic'
              ? `合成篮成分股 · 共 ${holdings.length} 只`
              : `共 ${holdings.length} 只`}
          </span>
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: '16px 0', textAlign: 'center', color: '#94a3b8', fontSize: 12 }}>
          加载中…
        </div>
      ) : holdings.length === 0 ? (
        <div style={{ padding: '16px 0', textAlign: 'center', color: '#94a3b8', fontSize: 12 }}>
          暂无持仓数据
        </div>
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr
                  style={{
                    background: '#f8fafc',
                    borderBottom: '1px solid #e2e8f0',
                  }}
                >
                  <th style={{ ...colHeaderStyle, textAlign: 'center', width: 28 }}>#</th>
                  <th style={{ ...colHeaderStyle, textAlign: 'left' }}>标的</th>
                  {SORT_KEYS.map((k) => {
                    const labels: Record<SortKey, string> = {
                      weight: '权重',
                      score: '动能分',
                      return20d: '20D收益',
                      rs20d: 'RS节点',
                      delta3d: '3D Δ',
                      delta5d: '5D Δ',
                    };
                    return (
                      <th
                        key={k}
                        style={{ ...colHeaderStyle, textAlign: 'right' }}
                        onClick={() => handleSort(k)}
                      >
                        {labels[k]}
                        <SortArrow active={sortKey === k} asc={sortAsc} />
                      </th>
                    );
                  })}
                  <th style={{ ...colHeaderStyle, textAlign: 'center' }}>状态</th>
                </tr>
              </thead>
              <tbody>
                {displayed.map((h, i) => {
                  const sc = STATUS_CFG[h.status ?? 'missing'] ?? STATUS_CFG.missing;
                  const isEven = i % 2 === 1;
                  const isHovered = hoveredRow === h.ticker;
                  const rowBg = isHovered ? '#eff6ff' : isEven ? '#fafbfc' : 'transparent';
                  const tierColor = scoreTierColor(h.score ?? 0);

                  return (
                    <tr
                      key={h.ticker}
                      style={{
                        borderBottom: '1px solid #f1f5f9',
                        background: rowBg,
                        cursor: onRowClick ? 'pointer' : 'default',
                        transition: 'background 0.1s ease',
                      }}
                      onMouseEnter={() => setHoveredRow(h.ticker)}
                      onMouseLeave={() => setHoveredRow(null)}
                      onClick={() => onRowClick?.(h.ticker)}
                    >
                      {/* # */}
                      <td
                        style={{
                          padding: '7px 8px',
                          fontSize: 11,
                          color: '#94a3b8',
                          textAlign: 'center',
                        }}
                      >
                        {i + 1}
                      </td>

                      {/* 标的 */}
                      <td style={{ padding: '7px 8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          {/* Score tier color bar */}
                          <div
                            style={{
                              width: 3,
                              height: 28,
                              borderRadius: 2,
                              background: tierColor,
                              flexShrink: 0,
                            }}
                          />
                          <div>
                            <div
                              style={{
                                fontSize: 13,
                                fontWeight: 700,
                                color: '#1e293b',
                                letterSpacing: '0.01em',
                              }}
                            >
                              {h.ticker}
                            </div>
                            <div
                              style={{
                                fontSize: 10,
                                color: '#94a3b8',
                                maxWidth: 140,
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                              }}
                            >
                              {h.name ?? ''}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* 权重 */}
                      <td
                        style={{
                          padding: '7px 10px',
                          textAlign: 'right',
                          fontSize: 12,
                          color: '#475569',
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {h.weight.toFixed(1)}%
                      </td>

                      {/* 动能分 */}
                      <td
                        style={{
                          padding: '7px 10px',
                          textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        <span
                          style={{ fontSize: 12, fontWeight: 700, color: tierColor }}
                        >
                          {(h.score ?? 0).toFixed(1)}
                        </span>
                      </td>

                      {/* 20D收益 */}
                      <td
                        style={{
                          padding: '7px 10px',
                          textAlign: 'right',
                          fontSize: 12,
                          fontWeight: 600,
                          color: deltaColor(h.return20d),
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {fmtPctDirect(h.return20d)}
                      </td>

                      {/* RS节点 */}
                      <td
                        style={{
                          padding: '7px 10px',
                          textAlign: 'right',
                          fontSize: 12,
                          fontWeight: 600,
                          color: deltaColor(h.rs20d),
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {fmtPctDirect(h.rs20d)}
                      </td>

                      {/* 3D Δ */}
                      <td
                        style={{
                          padding: '7px 10px',
                          textAlign: 'right',
                          fontSize: 12,
                          fontWeight: 500,
                          color: deltaColor(h.delta3d),
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {fmtDeltaNum(h.delta3d)}
                      </td>

                      {/* 5D Δ */}
                      <td
                        style={{
                          padding: '7px 10px',
                          textAlign: 'right',
                          fontSize: 12,
                          fontWeight: 500,
                          color: deltaColor(h.delta5d),
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {fmtDeltaNum(h.delta5d)}
                      </td>

                      {/* 状态 */}
                      <td style={{ padding: '7px 10px', textAlign: 'center' }}>
                        <span
                          style={{
                            fontSize: 10,
                            padding: '2px 7px',
                            borderRadius: 5,
                            background: sc.bg,
                            color: sc.color,
                            fontWeight: 500,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {sc.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Show-all button */}
          {!showAll && remaining > 0 && (
            <div style={{ paddingTop: 10, textAlign: 'center' }}>
              <button
                onClick={onShowAll}
                style={{
                  fontSize: 12,
                  color: '#2563eb',
                  background: 'none',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  padding: '5px 16px',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                展开全部 ({remaining} 更多)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
