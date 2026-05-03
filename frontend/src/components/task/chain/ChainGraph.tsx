/**
 * ChainGraph — 产业链图 SVG 渲染组件（Task DD-11）。
 *
 * 职责：纯渲染，根据后端 DD-7 /tasks/{id}/chain-graph 给出的节点坐标 + 边
 * 与 allNodes（ResearchNode）分数数据，渲染 4 层 tier bands、节点矩形、
 * 贝塞尔曲线边、选中/hover 高亮及底部图例。
 *
 * 不做：数据请求、选中态管理（由 DrilldownView 负责）。
 * 禁止：抽象通用 DAG 库；这是单一业务图。
 */
import { useState, useMemo } from 'react';
import type {
  ChainGraphNode,
  ChainGraphEdge,
  ResearchNode,
  TaskChainGraphResponse,
} from '../../../types';

// ─── 设计令牌（来自 HTML drilldown-upgrade.html L743-753） ────────────────────

const ROLE_COLORS: Record<string, string> = {
  sector:       '#1e293b',
  upstream:     '#8b5cf6',
  compute:      '#2563eb',
  memory:       '#3b82f6',
  interconnect: '#f59e0b',
  platform:     '#22c55e',
  application:  '#10b981',
  leaf:         '#94a3b8',
};

interface ScoreTier { border: string; bg: string; text: string }

function scoreTierStyle(score: number | null): ScoreTier {
  if (score === null) return { border: '#cbd5e1', bg: 'rgba(148,163,184,0.05)', text: '#64748b' };
  if (score >= 85) return { border: '#059669', bg: 'rgba(5,150,105,0.07)',   text: '#059669' };
  if (score >= 70) return { border: '#3b82f6', bg: 'rgba(59,130,246,0.07)', text: '#2563eb' };
  if (score >= 60) return { border: '#d97706', bg: 'rgba(217,119,6,0.07)',   text: '#d97706' };
  return             { border: '#cbd5e1', bg: 'rgba(148,163,184,0.05)', text: '#64748b' };
}

const TIER_BANDS = [
  { y: 0,   h: 88,  label: '板块层 L0' },
  { y: 88,  h: 88,  label: '主题层 L1' },
  { y: 176, h: 88,  label: '细分层 L2' },
  { y: 264, h: 86,  label: '叶子层 L3' },
];

const VW = 760;
const VH = 350;

// ─── Mock 数据（调试用，后端 DD-7 全量上线后可删） ─────────────────────────────
// TODO(phase5): 删除 MOCK_* 常量，确认 /tasks/{id}/chain-graph 稳定返回坐标 — 2026-05-03

const MOCK_LAYOUT_NODES: ChainGraphNode[] = [
  { node_id: 'XLK',          role: 'sector',       tier: 0, cx: 380, cy: 44,  w: 122, h: 46, proxy: null,   proxy_type: null,        proxy_label: null       },
  { node_id: 'semi',         role: 'upstream',     tier: 1, cx: 150, cy: 132, w: 110, h: 44, proxy: 'SOXX', proxy_type: 'etf',       proxy_label: 'SOXX'     },
  { node_id: 'soft',         role: 'platform',     tier: 1, cx: 385, cy: 132, w: 100, h: 44, proxy: 'IGV',  proxy_type: 'etf',       proxy_label: 'IGV'      },
  { node_id: 'hw',           role: 'upstream',     tier: 1, cx: 614, cy: 132, w: 104, h: 44, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
  { node_id: 'semi-equip',   role: 'upstream',     tier: 2, cx: 44,  cy: 218, w: 88,  h: 40, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
  { node_id: 'semi-compute', role: 'compute',      tier: 2, cx: 146, cy: 218, w: 88,  h: 40, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
  { node_id: 'semi-mem',     role: 'memory',       tier: 2, cx: 248, cy: 218, w: 88,  h: 40, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
  { node_id: 'semi-conn',    role: 'interconnect', tier: 2, cx: 350, cy: 218, w: 88,  h: 40, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
  { node_id: 'soft-cloud',   role: 'platform',     tier: 2, cx: 466, cy: 218, w: 94,  h: 40, proxy: 'SKYY', proxy_type: 'etf',       proxy_label: 'SKYY'     },
  { node_id: 'soft-cyber',   role: 'application',  tier: 2, cx: 572, cy: 218, w: 94,  h: 40, proxy: 'HACK', proxy_type: 'etf',       proxy_label: 'HACK'     },
  { node_id: 'conn-optical', role: 'leaf',         tier: 3, cx: 296, cy: 304, w: 102, h: 40, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
  { node_id: 'conn-copper',  role: 'leaf',         tier: 3, cx: 410, cy: 304, w: 92,  h: 40, proxy: null,   proxy_type: 'synthetic', proxy_label: '合成篮'   },
];

const MOCK_EDGES: ChainGraphEdge[] = [
  { src_node_id: 'XLK',       dst_node_id: 'semi',         is_cross: false },
  { src_node_id: 'XLK',       dst_node_id: 'soft',         is_cross: false },
  { src_node_id: 'XLK',       dst_node_id: 'hw',           is_cross: false },
  { src_node_id: 'semi',      dst_node_id: 'semi-equip',   is_cross: false },
  { src_node_id: 'semi',      dst_node_id: 'semi-compute', is_cross: false },
  { src_node_id: 'semi',      dst_node_id: 'semi-mem',     is_cross: false },
  { src_node_id: 'semi',      dst_node_id: 'semi-conn',    is_cross: false },
  { src_node_id: 'soft',      dst_node_id: 'soft-cloud',   is_cross: false },
  { src_node_id: 'soft',      dst_node_id: 'soft-cyber',   is_cross: false },
  { src_node_id: 'semi-conn', dst_node_id: 'conn-optical', is_cross: false },
  { src_node_id: 'semi-conn', dst_node_id: 'conn-copper',  is_cross: false },
  { src_node_id: 'hw',        dst_node_id: 'semi-conn',    is_cross: true  },
];

const MOCK_SCORE_NODES: ResearchNode[] = [
  { id: 'XLK',          label: 'XLK',   sublabel: '科技板块',    level: 0, proxy: null,   proxyType: 'etf',       score: 88, scoreVsParent: null, contribution: null, relStrength: 'strong',  breadth: null, delta3d: 0.8,  delta5d: 1.2,  children: [] },
  { id: 'semi',         label: '半导体', sublabel: 'SOXX',       level: 1, proxy: 'SOXX', proxyType: 'etf',       score: 91, scoreVsParent: null, contribution: null, relStrength: 'strong',  breadth: null, delta3d: 1.5,  delta5d: 2.1,  children: [] },
  { id: 'soft',         label: '软件',   sublabel: 'IGV',        level: 1, proxy: 'IGV',  proxyType: 'etf',       score: 74, scoreVsParent: null, contribution: null, relStrength: 'neutral', breadth: null, delta3d: 0.4,  delta5d: 0.8,  children: [] },
  { id: 'hw',           label: '硬件',   sublabel: '合成篮',      level: 1, proxy: null,   proxyType: 'synthetic', score: 62, scoreVsParent: null, contribution: null, relStrength: 'weak',    breadth: null, delta3d: -0.1, delta5d: -0.3, children: [] },
  { id: 'semi-equip',   label: '设备',   sublabel: 'AMAT+LRCX', level: 2, proxy: null,   proxyType: 'synthetic', score: 78, scoreVsParent: null, contribution: null, relStrength: 'strong',  breadth: null, delta3d: 1.0,  delta5d: 1.5,  children: [] },
  { id: 'semi-compute', label: '计算',   sublabel: 'NVDA+AMD',  level: 2, proxy: null,   proxyType: 'synthetic', score: 92, scoreVsParent: null, contribution: null, relStrength: 'strong',  breadth: null, delta3d: 2.1,  delta5d: 3.2,  children: [] },
  { id: 'semi-mem',     label: '存储',   sublabel: 'MU',        level: 2, proxy: null,   proxyType: 'synthetic', score: 58, scoreVsParent: null, contribution: null, relStrength: 'weak',    breadth: null, delta3d: -0.5, delta5d: -0.8, children: [] },
  { id: 'semi-conn',    label: '连接',   sublabel: 'MRVL',      level: 2, proxy: null,   proxyType: 'synthetic', score: 82, scoreVsParent: null, contribution: null, relStrength: 'strong',  breadth: null, delta3d: 1.3,  delta5d: 1.9,  children: [] },
  { id: 'soft-cloud',   label: '云计算', sublabel: 'SKYY',       level: 2, proxy: 'SKYY', proxyType: 'etf',       score: 71, scoreVsParent: null, contribution: null, relStrength: 'neutral', breadth: null, delta3d: 0.3,  delta5d: 0.5,  children: [] },
  { id: 'soft-cyber',   label: '网安',   sublabel: 'HACK',       level: 2, proxy: 'HACK', proxyType: 'etf',       score: 68, scoreVsParent: null, contribution: null, relStrength: 'neutral', breadth: null, delta3d: 0.1,  delta5d: 0.2,  children: [] },
  { id: 'conn-optical', label: '光',     sublabel: 'CIEN+COHR', level: 3, proxy: null,   proxyType: 'synthetic', score: 85, scoreVsParent: null, contribution: null, relStrength: 'strong',  breadth: null, delta3d: 1.8,  delta5d: 2.8,  children: [] },
  { id: 'conn-copper',  label: '铜',     sublabel: 'APH+TEL',   level: 3, proxy: null,   proxyType: 'synthetic', score: 63, scoreVsParent: null, contribution: null, relStrength: 'weak',    breadth: null, delta3d: -0.2, delta5d: -0.4, children: [] },
];

// ─── 主组件 ────────────────────────────────────────────────────────────────

export interface ChainGraphProps {
  /** Backend layout + topology data from DD-7 /tasks/{id}/chain-graph */
  chainGraph: TaskChainGraphResponse | null;
  /** Score/label/delta data from node tree; mock scores used when empty */
  allNodes: ResearchNode[];
  selectedNodeId: string | null;
  onSelect: (node: ResearchNode) => void;
}

export function ChainGraph({
  chainGraph,
  allNodes,
  selectedNodeId,
  onSelect,
}: ChainGraphProps): React.ReactElement {
  const [hoverId, setHoverId] = useState<string | null>(null);

  // Prefer backend layout; fall back to mock when backend coords not yet available
  const layoutNodes: ChainGraphNode[] =
    chainGraph?.nodes?.length ? chainGraph.nodes : MOCK_LAYOUT_NODES;
  const edges: ChainGraphEdge[] =
    chainGraph?.edges?.length ? chainGraph.edges : MOCK_EDGES;

  // Score/label lookup: mock as baseline, live allNodes overrides
  const scoreMap = useMemo<Map<string, ResearchNode>>(() => {
    const m = new Map<string, ResearchNode>();
    MOCK_SCORE_NODES.forEach((n) => m.set(n.id, n));
    allNodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [allNodes]);

  const layoutMap = useMemo<Map<string, ChainGraphNode>>(() => {
    const m = new Map<string, ChainGraphNode>();
    layoutNodes.forEach((n) => m.set(n.node_id, n));
    return m;
  }, [layoutNodes]);

  // Midpoints for cross-edge "跨链" text labels
  const crossLabelPoints = useMemo(() => {
    return edges
      .filter((e) => e.is_cross)
      .flatMap((e) => {
        const src = layoutMap.get(e.src_node_id);
        const tgt = layoutMap.get(e.dst_node_id);
        if (!src || !tgt || src.cx === null || tgt.cx === null) return [];
        const x1 = src.cx, y1 = src.cy! + src.h! / 2;
        const x2 = tgt.cx, y2 = tgt.cy! - tgt.h! / 2;
        // Offset label 30px right of the bezier midpoint so it doesn't overlap the curve
        return [{ key: `${e.src_node_id}-${e.dst_node_id}`, x: (x1 + x2) / 2 + 30, y: (y1 + y2) / 2 }];
      });
  }, [edges, layoutMap]);

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: '#fafbfc' }}>

      {/* SVG canvas — fills remaining vertical space */}
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        <svg
          viewBox={`0 0 ${VW} ${VH}`}
          style={{ width: '100%', height: '100%', display: 'block' }}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* ── Tier bands ── */}
          {TIER_BANDS.map((band, i) => (
            <g key={band.label}>
              <rect
                x={0} y={band.y} width={VW} height={band.h}
                fill={i % 2 === 0 ? '#f8fafc' : '#f1f5f9'}
              />
              <text
                x={8} y={band.y + 15}
                fontSize={9} fill="#d1d5db"
                fontFamily="Inter, sans-serif"
              >
                {band.label}
              </text>
            </g>
          ))}

          {/* ── Edges ── */}
          {edges.map((edge) => {
            const src = layoutMap.get(edge.src_node_id);
            const tgt = layoutMap.get(edge.dst_node_id);
            if (!src || !tgt || src.cx === null || tgt.cx === null) return null;

            const x1 = src.cx, y1 = src.cy! + src.h! / 2;
            const x2 = tgt.cx, y2 = tgt.cy! - tgt.h! / 2;
            const cmy = (y1 + y2) / 2;

            const srcScore = scoreMap.get(edge.src_node_id)?.score ?? 0;
            const tgtScore = scoreMap.get(edge.dst_node_id)?.score ?? 0;
            // Strong = both endpoints score>75, not a cross-chain edge
            const strong = (srcScore ?? 0) > 75 && (tgtScore ?? 0) > 75 && !edge.is_cross;

            return (
              <path
                key={`${edge.src_node_id}-${edge.dst_node_id}`}
                d={`M ${x1} ${y1} C ${x1} ${cmy}, ${x2} ${cmy}, ${x2} ${y2}`}
                fill="none"
                stroke={edge.is_cross ? '#f59e0b' : strong ? '#93c5fd' : '#dde5f0'}
                strokeWidth={strong ? 2.5 : 1.5}
                strokeDasharray={edge.is_cross ? '5,3' : undefined}
                opacity={edge.is_cross ? 0.75 : 1}
              />
            );
          })}

          {/* ── Nodes ── */}
          {layoutNodes.map((ln) => {
            if (ln.cx === null || ln.cy === null || ln.w === null || ln.h === null) return null;

            const node = scoreMap.get(ln.node_id);
            const isSelected = ln.node_id === selectedNodeId;
            const isHovered  = ln.node_id === hoverId;
            const tier = scoreTierStyle(node?.score ?? null);
            const roleColor = ROLE_COLORS[ln.role ?? ''] ?? '#94a3b8';

            const x0 = ln.cx - ln.w / 2;
            const y0 = ln.cy - ln.h / 2;

            // Proxy string: explicit proxy first, then proxy_label for synthetic nodes
            const proxyStr = ln.proxy ?? (ln.proxy_type === 'synthetic' ? (ln.proxy_label ?? '合成篮') : '');
            const delta5d = node?.delta5d ?? null;
            const scoreVal = node?.score ?? null;
            // Root node gets slightly larger text
            const isRoot = ln.tier === 0;
            const textSize = isRoot ? 13 : 11;
            const textOffsetY = ln.h > 40 ? 7 : 5;

            return (
              <g
                key={ln.node_id}
                style={{ cursor: 'pointer' }}
                onClick={() => node && onSelect(node)}
                onMouseEnter={() => setHoverId(ln.node_id)}
                onMouseLeave={() => setHoverId(null)}
              >
                {/* Outer highlight ring (selected=blue, hover=gray) */}
                {(isSelected || isHovered) && (
                  <rect
                    x={x0 - 2} y={y0 - 2}
                    width={ln.w + 4} height={ln.h + 4}
                    rx={9}
                    fill="none"
                    stroke={isSelected ? '#3b82f6' : '#cbd5e1'}
                    strokeWidth={isSelected ? 2 : 1.5}
                    opacity={0.7}
                  />
                )}

                {/* Main rect */}
                <rect
                  x={x0} y={y0} width={ln.w} height={ln.h} rx={7}
                  fill={isSelected ? '#eff6ff' : tier.bg}
                  stroke={isSelected ? '#3b82f6' : isHovered ? '#94a3b8' : tier.border}
                  strokeWidth={isSelected ? 1.5 : 1}
                />

                {/* Role stripe — 3px wide left-edge bar */}
                <rect
                  x={x0} y={y0 + 6}
                  width={3} height={ln.h - 12}
                  rx={1.5} fill={roleColor}
                />

                {/* Label (top-left area) */}
                <text
                  x={x0 + 11} y={ln.cy - textOffsetY}
                  fontSize={textSize} fontWeight="700"
                  fill={isSelected ? '#1e293b' : '#334155'}
                  fontFamily="Noto Sans SC, Inter, sans-serif"
                >
                  {node?.label ?? ln.node_id}
                </text>

                {/* Score (top-right, color-coded by tier) */}
                {scoreVal !== null && (
                  <text
                    x={x0 + ln.w - 8} y={ln.cy - textOffsetY}
                    fontSize={textSize} fontWeight="700"
                    fill={tier.text} textAnchor="end"
                    fontFamily="Inter, sans-serif"
                  >
                    {scoreVal.toFixed(0)}
                  </text>
                )}

                {/* Proxy string (bottom-left) */}
                {proxyStr && (
                  <text
                    x={x0 + 11} y={y0 + ln.h - 7}
                    fontSize={8} fill="#94a3b8"
                    fontFamily="Inter, sans-serif"
                  >
                    {proxyStr}
                  </text>
                )}

                {/* 5D delta (bottom-right, green/red) */}
                {delta5d !== null && (
                  <text
                    x={x0 + ln.w - 8} y={y0 + ln.h - 7}
                    fontSize={8} textAnchor="end"
                    fill={delta5d >= 0 ? '#22c55e' : '#ef4444'}
                    fontFamily="Inter, sans-serif"
                  >
                    {delta5d > 0 ? '+' : ''}{delta5d.toFixed(1)}
                  </text>
                )}
              </g>
            );
          })}

          {/* "跨链" text labels near cross-edge midpoints */}
          {crossLabelPoints.map((pt) => (
            <text
              key={pt.key}
              x={pt.x} y={pt.y}
              fontSize={8} fill="#f59e0b"
              fontFamily="Noto Sans SC, sans-serif"
              opacity={0.85}
            >
              跨链
            </text>
          ))}
        </svg>
      </div>

      {/* Bottom legend */}
      <div style={{
        padding: '9px 18px',
        borderTop: '1px solid #e2e8f0',
        background: '#fff',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 10, fontWeight: 600, color: '#94a3b8' }}>链条角色</span>
        {(
          [['上游', '#8b5cf6'], ['算力', '#2563eb'], ['存储', '#3b82f6'],
           ['互联', '#f59e0b'], ['平台', '#22c55e'], ['应用', '#10b981']] as [string, string][]
        ).map(([label, color]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 7, height: 7, borderRadius: 2, background: color }} />
            <span style={{ fontSize: 10, color: '#64748b' }}>{label}</span>
          </div>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <svg width="22" height="6">
              <line x1="0" y1="3" x2="22" y2="3" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4,3" />
            </svg>
            <span style={{ fontSize: 10, color: '#94a3b8' }}>跨链关联</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <svg width="22" height="6">
              <line x1="0" y1="3" x2="22" y2="3" stroke="#93c5fd" strokeWidth="2.5" />
            </svg>
            <span style={{ fontSize: 10, color: '#94a3b8' }}>强关联边</span>
          </div>
        </div>
      </div>
    </div>
  );
}
