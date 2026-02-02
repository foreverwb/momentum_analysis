import React from 'react';

interface CompareBannerProps {
  selectedCount: number;
  maxCount: number;
  onCompare: () => void;
  onCancel: () => void;
}

/**
 * Banner displayed when in compare mode
 * Shows selected count and action buttons
 */
export function CompareBanner({
  selectedCount,
  maxCount,
  onCompare,
  onCancel
}: CompareBannerProps) {
  const canCompare = selectedCount >= 2;

  return (
    <div 
      className="bg-gradient-to-r from-blue-50 to-purple-50 border border-[var(--accent-blue)] rounded-[var(--radius-lg)] p-4 mb-5 flex items-center justify-between"
      style={{
        background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(139, 92, 246, 0.08))'
      }}
    >
      {/* Left: Info */}
      <div className="flex items-center gap-3">
        <span className="text-xl">🔄</span>
        <span className="text-sm font-medium text-[var(--accent-blue)]">
          对比模式
        </span>
        <span className="px-3 py-1 bg-[var(--accent-blue)] text-white rounded-full text-[13px] font-semibold">
          {selectedCount} / {maxCount}
        </span>
        {selectedCount > 0 && selectedCount < 2 && (
          <span className="text-xs text-[var(--text-muted)]">
            至少选择 2 只股票
          </span>
        )}
        {selectedCount >= maxCount && (
          <span className="text-xs text-[var(--accent-amber)]">
            已达最大选择数量
          </span>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={onCompare}
          disabled={!canCompare}
          className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-all ${
            canCompare
              ? 'bg-[var(--accent-blue)] text-white hover:opacity-90 cursor-pointer'
              : 'bg-gray-200 text-gray-400 cursor-not-allowed'
          }`}
        >
          查看对比
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 bg-transparent text-[var(--accent-blue)] border border-[var(--accent-blue)] rounded-lg text-[13px] font-medium hover:bg-blue-50 transition-colors"
        >
          取消
        </button>
      </div>
    </div>
  );
}