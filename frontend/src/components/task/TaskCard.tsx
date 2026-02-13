import React, { useEffect, useState } from 'react';
import type { Task, TaskType } from '../../types';

interface TaskCardProps {
  task: Task;
  onClick?: () => void;
  onDelete?: () => void;
  onRename?: (newTitle: string) => Promise<void> | void;
  deleting?: boolean;
  renaming?: boolean;
}

const taskTypeLabels: Record<TaskType, string> = {
  rotation: '板块轮动',
  drilldown: '板块内下钻',
  momentum: '动能股追踪'
};

export function TaskCard({ task, onClick, onDelete, onRename, deleting, renaming }: TaskCardProps) {
  if (!task) return null;
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState(task.title ?? '');

  useEffect(() => {
    if (!isEditingTitle) {
      setDraftTitle(task.title ?? '');
    }
  }, [isEditingTitle, task.title]);

  const baseIndices = (task.baseIndices && task.baseIndices.length > 0
    ? task.baseIndices
    : String(task.baseIndex || '')
        .split(',')
        .map((item) => item.trim().toUpperCase())
        .filter((item) => item.length > 0)
  );
  const baseIndicesLabel = baseIndices.length > 0 ? baseIndices.join(' / ') : '--';

  const handleClick = () => {
    if (isEditingTitle) return;
    if (!task?.id) return;
    console.log('Task card clicked:', task.title);
    onClick?.();
  };

  const handleStartEditTitle = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    setDraftTitle(task.title ?? '');
    setIsEditingTitle(true);
  };

  const handleCancelEditTitle = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    setDraftTitle(task.title ?? '');
    setIsEditingTitle(false);
  };

  const handleSaveTitle = async (e?: React.MouseEvent<HTMLButtonElement>) => {
    e?.stopPropagation();
    const normalized = draftTitle.trim();
    if (normalized.length === 0) {
      alert('任务名称不能为空');
      return;
    }
    if (normalized === (task.title ?? '').trim()) {
      setIsEditingTitle(false);
      return;
    }
    try {
      await onRename?.(normalized);
      setIsEditingTitle(false);
    } catch (err) {
      console.error('重命名任务失败', err);
    }
  };

  return (
    <div 
      className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5 cursor-pointer transition-all duration-150 hover:shadow-md hover:border-[var(--accent-blue)]"
      onClick={handleClick}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3.5">
        <div className="min-w-0 flex-1 pr-3">
          {isEditingTitle ? (
            <div className="flex items-center gap-2 mb-1" onClick={(e) => e.stopPropagation()}>
              <input
                type="text"
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    void handleSaveTitle();
                  }
                  if (e.key === 'Escape') {
                    setDraftTitle(task.title ?? '');
                    setIsEditingTitle(false);
                  }
                }}
                className="min-w-0 flex-1 px-2 py-1.5 text-sm border border-[var(--border-medium)] rounded-[var(--radius-sm)] focus:outline-none focus:border-[var(--accent-blue)]"
                autoFocus
              />
              <button
                type="button"
                onClick={(e) => void handleSaveTitle(e)}
                disabled={Boolean(renaming)}
                className="px-2 py-1 text-xs rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 disabled:opacity-50"
              >
                保存
              </button>
              <button
                type="button"
                onClick={handleCancelEditTitle}
                disabled={Boolean(renaming)}
                className="px-2 py-1 text-xs rounded-[var(--radius-sm)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] disabled:opacity-50"
              >
                取消
              </button>
            </div>
          ) : (
            <div className="text-base font-semibold mb-1 truncate">{task.title ?? '--'}</div>
          )}
          <span 
            className="inline-flex px-2.5 py-1 rounded-full text-xs font-medium"
            style={{ 
              background: 'rgba(139, 92, 246, 0.1)', 
              color: 'var(--accent-purple)' 
            }}
          >
            {taskTypeLabels[task.type] ?? task.type}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {onRename && !isEditingTitle && (
            <button
              className="p-1.5 rounded-full text-[var(--text-muted)] hover:text-[var(--accent-blue)] hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50"
              onClick={handleStartEditTitle}
              disabled={Boolean(renaming)}
              aria-label="编辑任务名称"
              title="编辑任务名称"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
          )}
          {onDelete && (
            <button
              className="p-1.5 rounded-full text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              disabled={deleting}
              aria-label="删除任务"
              title="删除任务"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 6h18" />
                <path d="M8 6v12a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V6" />
                <path d="M10 11v6M14 11v6" />
                <path d="M9 6l1-3h4l1 3" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Meta Info */}
      <div className="flex flex-col gap-1.5 text-[13px] text-[var(--text-secondary)] mb-3.5">
        <span>
          基准指数: {baseIndicesLabel}
          {task.sector ? ` · 板块: ${task.sector}` : ''}
        </span>
        <span>创建时间: {task.createdAt ?? '--'}</span>
      </div>

      {/* ETF Chips */}
      <div className="flex flex-wrap gap-2">
        {task.etfs?.map((etf, index) => (
          <span
            key={index}
            className="px-2.5 py-1 bg-[var(--bg-tertiary)] rounded-[var(--radius-sm)] text-xs font-medium"
          >
            {etf}
          </span>
        )) ?? null}
      </div>
    </div>
  );
}
