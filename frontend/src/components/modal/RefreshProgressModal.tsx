import React, { useEffect } from 'react';

interface RefreshProgressModalProps {
  isOpen: boolean;
  title: string;
  currentItem?: string;
  message?: string;
  completed: number;
  total: number;
  isError?: boolean;
  isComplete?: boolean;
}

export function RefreshProgressModal({
  isOpen,
  title,
  currentItem,
  message,
  completed,
  total,
  isError = false,
  isComplete = false,
}: RefreshProgressModalProps) {
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center"
      style={{
        background: 'rgba(0, 0, 0, 0.3)',
        backdropFilter: 'blur(2px)',
      }}
    >
      <div
        className="bg-[var(--bg-primary)] rounded-[var(--radius-lg)] shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)] overflow-hidden"
        style={{ width: '360px' }}
      >
        {/* Header */}
        <div className="p-6 pb-4">
          <div className="flex items-center gap-3 mb-4">
            {isComplete ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-green)" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
            ) : isError ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-red)" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" strokeWidth="2" className="animate-spin">
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
            )}
            <h3 className="text-base font-semibold text-[var(--text-primary)]">{title}</h3>
          </div>

          {/* Progress Info */}
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-[var(--text-muted)]">
              已完成 {completed}/{total}
            </span>
            <span className="font-medium text-[var(--text-primary)]">{percentage}%</span>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-[var(--bg-secondary)] rounded-full h-2 overflow-hidden">
            <div
              className="h-full transition-all duration-300"
              style={{
                width: `${percentage}%`,
                background: isError
                  ? 'var(--accent-red)'
                  : isComplete
                  ? 'var(--accent-green)'
                  : 'var(--accent-blue)',
              }}
            />
          </div>
        </div>

        {/* Details */}
        <div className="px-6 py-4 border-t border-[var(--border-light)] bg-[var(--bg-secondary)]">
          {currentItem && (
            <div className="text-xs text-[var(--text-muted)] mb-2">
              <span className="text-[var(--text-primary)]">当前处理:</span> {currentItem}
            </div>
          )}
          {message && (
            <div className="text-xs text-[var(--text-muted)]">
              {message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
