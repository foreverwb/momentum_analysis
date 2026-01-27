import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as api from '../services/api';
import type { Task } from '../types';

// Stock hooks
export function useStocks() {
  return useQuery({
    queryKey: ['stocks'],
    queryFn: api.getStocks,
  });
}

export function useStock(id: number) {
  return useQuery({
    queryKey: ['stocks', id],
    queryFn: () => api.getStockById(id),
    enabled: !!id,
  });
}

// ETF hooks
export function useETFs(type?: 'sector' | 'industry') {
  return useQuery({
    queryKey: ['etfs', type],
    queryFn: () => api.getETFs(type),
  });
}

export function useETF(id: number) {
  return useQuery({
    queryKey: ['etfs', id],
    queryFn: () => api.getETFById(id),
    enabled: !!id,
  });
}

// Task hooks
export function useTasks() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: api.getTasks,
  });
}

export function useTask(id: number) {
  return useQuery({
    queryKey: ['tasks', id],
    queryFn: () => api.getTaskById(id),
    enabled: !!id,
  });
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (task: Omit<Task, 'id' | 'createdAt'>) => api.createTask(task),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}
