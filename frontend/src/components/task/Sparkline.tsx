/**
 * Sparkline — 小型 SVG 折线图，用于 NodeTree 行内与 NodeDetailPanel。
 *
 * 职责：将数值序列渲染为 SVG polyline，data.length < 2 时返回占位 span。
 * 不做：数据拉取、状态管理。
 */
import React from 'react';

export interface SparklineProps {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}

export function Sparkline({
  data,
  color = '#3b82f6',
  width = 44,
  height = 18,
}: SparklineProps): React.ReactElement {
  if (!data || data.length < 2) {
    return <span style={{ display: 'inline-block', width, height }} />;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      // 留 1px 上下边距防止 stroke 被裁剪
      const y = height - ((v - min) / range) * (height - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      width={width}
      height={height}
      style={{ display: 'block', overflow: 'visible' }}
    >
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
