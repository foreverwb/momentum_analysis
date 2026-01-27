import React, { useEffect, useCallback } from 'react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  size?: 'default' | 'small';
  children: React.ReactNode;
  footer?: React.ReactNode;
  showCloseButton?: boolean;
}

export function Modal({
  isOpen,
  onClose,
  title,
  subtitle,
  size = 'default',
  children,
  footer,
  showCloseButton = true,
}: ModalProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    },
    [onClose]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'unset';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-start justify-center overflow-y-auto"
      style={{ 
        background: 'rgba(15, 23, 42, 0.5)',
        backdropFilter: 'blur(4px)',
        padding: '40px 20px',
      }}
      onClick={handleOverlayClick}
    >
      <div
        className={`
          bg-[var(--bg-primary)] rounded-[var(--radius-lg)] w-full
          shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]
          animate-[modalSlideIn_0.2s_ease-out]
          ${size === 'small' ? 'max-w-[560px]' : 'max-w-[900px]'}
        `}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-[var(--border-light)]">
          <div>
            <h2 className="text-xl font-semibold text-[var(--text-primary)]">{title}</h2>
            {subtitle && (
              <p className="text-sm text-[var(--text-muted)] mt-1">{subtitle}</p>
            )}
          </div>
          {showCloseButton && (
            <button
              onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 5L5 15M5 5l10 10" />
              </svg>
            </button>
          )}
        </div>

        {/* Body */}
        <div className="p-6">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-3 p-6 border-t border-[var(--border-light)] bg-[var(--bg-secondary)] rounded-b-[var(--radius-lg)]">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
