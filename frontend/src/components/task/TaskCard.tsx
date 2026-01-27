import React from 'react';
import type { Task, TaskType } from '../../types';

interface TaskCardProps {
  task: Task;
  onClick?: () => void;
}

const taskTypeLabels: Record<TaskType, string> = {
  rotation: '板块轮动',
  drilldown: '板块内下钻',
  momentum: '动能股追踪'
};

export function TaskCard({ task, onClick }: TaskCardProps) {
  if (!task) return null;

  const handleClick = () => {
    if (!task?.id) return;
    console.log('Task card clicked:', task.title);
    onClick?.();
  };

  return (
    <div 
      className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-5 cursor-pointer transition-all duration-150 hover:shadow-md hover:border-[var(--accent-blue)]"
      onClick={handleClick}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3.5">
        <div>
          <div className="text-base font-semibold mb-1">{task.title ?? '--'}</div>
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
      </div>

      {/* Meta Info */}
      <div className="flex flex-col gap-1.5 text-[13px] text-[var(--text-secondary)] mb-3.5">
        <span>
          基准指数: {task.baseIndex ?? '--'}
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
