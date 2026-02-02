import React from 'react';
import type { HeatType } from '../../types';
import { Select } from '../common';

interface ControlsBarProps {
  // Filter states
  industryFilter: string;
  heatFilter: HeatType | 'all';
  
  // Compare mode state
  isCompareMode: boolean;
  
  // Callbacks
  onIndustryChange: (value: string) => void;
  onHeatChange: (value: HeatType | 'all') => void;
  onToggleCompareMode: () => void;
  
  // Options data
  industryOptions?: { value: string; label: string }[];
}

/**
 * ControlsBar Component
 * 
 * Provides filtering and mode control options for the MomentumPool page
 * 
 * Features:
 * - Industry filter dropdown
 * - Heat type filter dropdown
 * - Compare mode toggle button
 */
export function ControlsBar({
  industryFilter,
  heatFilter,
  isCompareMode,
  onIndustryChange,
  onHeatChange,
  onToggleCompareMode,
  industryOptions = []
}: ControlsBarProps) {
  
  // Heat filter options
  const heatOptions = [
    { value: 'all', label: '全部热度' },
    { value: 'trend', label: '📈 趋势热度' },
    { value: 'event', label: '⚡ 事件热度' },
    { value: 'hedge', label: '🛡️ 对冲热度' },
    { value: 'normal', label: '📊 正常' }
  ];

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-4 mb-6">
      <div className="flex items-center justify-between gap-4">
        
        {/* Left: Filters */}
        <div className="flex items-center gap-3">
          {/* Industry Filter */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-[var(--text-secondary)] whitespace-nowrap">
              行业筛选:
            </span>
            <Select
              options={industryOptions}
              value={industryFilter}
              onChange={(e) => onIndustryChange(e.target.value)}
            />
          </div>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--border-light)]" />

          {/* Heat Filter */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-[var(--text-secondary)] whitespace-nowrap">
              热度筛选:
            </span>
            <Select
              options={heatOptions}
              value={heatFilter}
              onChange={(e) => onHeatChange(e.target.value as HeatType | 'all')}
            />
          </div>
        </div>

        {/* Right: Compare Mode Toggle */}
        <div>
          <button
            onClick={onToggleCompareMode}
            className={`
              px-4 py-2 rounded-[var(--radius-md)]
              text-sm font-medium
              transition-all
              ${isCompareMode
                ? 'bg-[var(--accent-blue)] text-white hover:bg-blue-600'
                : 'bg-[var(--bg-secondary)] text-[var(--text-primary)] hover:bg-gray-200 border border-[var(--border-medium)]'
              }
            `}
          >
            {isCompareMode ? (
              <span className="flex items-center gap-2">
                <span>✓</span>
                <span>对比模式</span>
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span>⚖️</span>
                <span>开启对比</span>
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
