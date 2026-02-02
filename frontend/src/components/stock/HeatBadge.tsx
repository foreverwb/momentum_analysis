import React from 'react';
import type { HeatType } from '../../types';

interface HeatBadgeProps {
  type: HeatType;
  className?: string;
}

// Heat type display configuration
const heatConfig = {
  trend: {
    label: '趋势热度',
    emoji: '📈',
    bgColor: 'bg-green-100',
    textColor: 'text-green-700',
    borderColor: 'border-green-200'
  },
  event: {
    label: '事件热度',
    emoji: '⚡',
    bgColor: 'bg-amber-100',
    textColor: 'text-amber-700',
    borderColor: 'border-amber-200'
  },
  hedge: {
    label: '对冲热度',
    emoji: '🛡️',
    bgColor: 'bg-red-100',
    textColor: 'text-red-700',
    borderColor: 'border-red-200'
  },
  normal: {
    label: '正常',
    emoji: '📊',
    bgColor: 'bg-gray-100',
    textColor: 'text-gray-600',
    borderColor: 'border-gray-200'
  }
} as const;

/**
 * HeatBadge Component
 * 
 * Displays a styled badge indicating the heat type of a stock
 * 
 * @param type - The heat type (trend/event/hedge/normal)
 * @param className - Optional additional CSS classes
 */
export function HeatBadge({ type, className = '' }: HeatBadgeProps) {
  const config = heatConfig[type];

  return (
    <span 
      className={`
        inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
        text-sm font-medium border
        ${config.bgColor} ${config.textColor} ${config.borderColor}
        ${className}
      `}
    >
      <span className="text-base leading-none">{config.emoji}</span>
      <span>{config.label}</span>
    </span>
  );
}

/**
 * Compact version of HeatBadge for use in tables or tight spaces
 */
export function HeatBadgeCompact({ type, className = '' }: HeatBadgeProps) {
  const config = heatConfig[type];

  return (
    <span 
      className={`
        inline-flex items-center justify-center
        w-8 h-8 rounded-full
        text-lg border
        ${config.bgColor} ${config.borderColor}
        ${className}
      `}
      title={config.label}
    >
      {config.emoji}
    </span>
  );
}
