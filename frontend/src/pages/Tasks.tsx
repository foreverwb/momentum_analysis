import React, { useState } from 'react';
import { useTasks, useCreateTask } from '../hooks/useData';
import { TaskCard, TaskDetail } from '../components/task';
import { LoadingState, ErrorMessage, Button } from '../components/common';
import { CreateTaskModal } from '../components/modal';
import type { CreateTaskData } from '../components/modal';
import type { Task } from '../types';

export function Tasks() {
  const { data: tasks, isLoading, error, refetch } = useTasks();
  const createTaskMutation = useCreateTask();
  
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);

  const handleCreateTask = () => {
    setIsCreateModalOpen(true);
  };

  const handleSubmitTask = (taskData: CreateTaskData) => {
    createTaskMutation.mutate({
      title: taskData.title,
      type: taskData.type,
      baseIndex: taskData.baseIndex,
      sector: taskData.sector ?? undefined,
      etfs: taskData.etfs,
    });
    console.log('Task created:', taskData);
  };

  const handleViewTask = (task: Task) => {
    setSelectedTask(task);
  };

  const handleBackToList = () => {
    setSelectedTask(null);
  };

  if (isLoading) {
    return <LoadingState message="正在加载监控任务..." />;
  }

  if (error) {
    return <ErrorMessage error={error} onRetry={refetch} />;
  }

  // Show task detail view
  if (selectedTask) {
    return <TaskDetail task={selectedTask} onBack={handleBackToList} />;
  }

  // Show task list view
  return (
    <div>
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="text-xl">📋</span>
          <h1 className="text-xl font-semibold">监控任务列表</h1>
          <span className="text-sm text-[var(--text-muted)]">
            共 {tasks?.length ?? 0} 个任务
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={handleCreateTask}>
            + 创建监控任务
          </Button>
        </div>
      </div>

      {/* Task Cards Grid */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-5">
        {tasks && tasks.length > 0 ? (
          tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onClick={() => handleViewTask(task)}
            />
          ))
        ) : (
          <div className="col-span-full text-center py-12 text-[var(--text-muted)]">
            暂无监控任务，点击"创建监控任务"开始
          </div>
        )}
      </div>

      {/* Create Task Modal */}
      <CreateTaskModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSubmit={handleSubmitTask}
      />
    </div>
  );
}
