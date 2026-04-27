import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTasks, useTask, useCreateTask, useUpdateTask, useDeleteTask } from '../hooks/useData';
import { TaskCard, TaskDetail } from '../components/task';
import { LoadingState, ErrorMessage, Button } from '../components/common';
import { CreateTaskModal } from '../components/modal';
import type { CreateTaskData } from '../components/modal';
import type { Task, CreateTaskInput } from '../types';

function buildMomentumDetailRoute(symbol: string): string {
  const normalized = symbol.trim().toUpperCase();
  return `/momentum/${encodeURIComponent(normalized).replace(/\./g, '%2E')}`;
}

export function Tasks() {
  const navigate = useNavigate();
  const { taskId: routeTaskId } = useParams<{ taskId?: string }>();
  const normalizedTaskId = routeTaskId?.trim() || null;
  const isDetailRoute = Boolean(normalizedTaskId);

  const { data: tasks, isLoading, error, refetch } = useTasks();
  const {
    data: routeTask,
    isLoading: isTaskLoading,
    error: taskError,
    refetch: refetchTask,
  } = useTask(normalizedTaskId);
  const createTaskMutation = useCreateTask();
  const updateTaskMutation = useUpdateTask();
  const deleteTaskMutation = useDeleteTask();
  
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [renamingTaskId, setRenamingTaskId] = useState<number | null>(null);

  const selectedTask =
    isDetailRoute
      ? routeTask || tasks?.find((task) => String(task.id) === normalizedTaskId) || null
      : null;

  const handleCreateTask = () => {
    setIsCreateModalOpen(true);
  };

  const handleSubmitTask = (taskData: CreateTaskData) => {
    createTaskMutation.mutate({
      title: taskData.title,
      type: taskData.type,
      baseIndex: taskData.baseIndex,
      baseIndices: taskData.baseIndices,
      sector: taskData.sector ?? undefined,
      etfs: taskData.etfs,
      rootNode: taskData.rootNode,
      viewMode: taskData.viewMode,
      selectedNodes: taskData.selectedNodes,
      pinnedEvidenceNodes: taskData.pinnedEvidenceNodes,
    });
  };

  const handleViewTask = (task: Task) => {
    if (!task?.id) return;
    navigate(`/tracking/${task.id}`);
  };

  const handleBackToList = () => {
    navigate('/tracking');
  };

  const handleDeleteTask = async (task: Task) => {
    if (!task?.id) return;
    const confirmed = window.confirm(`确认删除监控任务「${task.title || task.id}」吗？`);
    if (!confirmed) return;
    try {
      await deleteTaskMutation.mutateAsync(task.id);
    } catch (err) {
      console.error('删除任务失败', err);
      alert('删除失败，请稍后重试');
    }
  };

  const handleRenameTask = async (task: Task, newTitle: string) => {
    if (!task?.id) return;
    const normalizedTitle = newTitle.trim();
    if (!normalizedTitle) {
      alert('任务名称不能为空');
      return;
    }

    const payload: CreateTaskInput = {
      title: normalizedTitle,
      type: task.type,
      baseIndex:
        task.baseIndices && task.baseIndices.length > 0
          ? task.baseIndices.join(',')
          : task.baseIndex,
      sector: task.sector,
      etfs: task.etfs || [],
    };

    setRenamingTaskId(task.id);
    try {
      const updatedTask = await updateTaskMutation.mutateAsync({
        id: task.id,
        input: payload,
      });
      if (normalizedTaskId && String(updatedTask.id) === normalizedTaskId) {
        void refetchTask();
      }
    } catch (err) {
      console.error('修改任务名称失败', err);
      alert('修改名称失败，请稍后重试');
      throw err;
    } finally {
      setRenamingTaskId(null);
    }
  };

  if (isDetailRoute) {
    if (isTaskLoading && !selectedTask) {
      return <LoadingState message="正在加载监控任务详情..." />;
    }

    if (taskError) {
      return <ErrorMessage error={taskError} onRetry={refetchTask} />;
    }

    if (!selectedTask) {
      return (
        <ErrorMessage
          error={new Error(`未找到任务 ID: ${normalizedTaskId}`)}
          onRetry={refetchTask}
        />
      );
    }

    return (
      <TaskDetail
        task={selectedTask}
        onBack={handleBackToList}
        onViewStockDetail={(symbol) => navigate(buildMomentumDetailRoute(symbol))}
      />
    );
  }

  if (isLoading) {
    return <LoadingState message="正在加载监控任务..." />;
  }

  if (error) {
    return <ErrorMessage error={error} onRetry={refetch} />;
  }

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
              onRename={(newTitle) => handleRenameTask(task, newTitle)}
              renaming={renamingTaskId === task.id}
              onDelete={() => handleDeleteTask(task)}
              deleting={deleteTaskMutation.isPending}
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
