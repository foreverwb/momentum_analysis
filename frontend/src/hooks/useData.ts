import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as api from '../services/api';
import type { Task } from '../types';

// Stock hooks
export function useStocks(params?: { industry?: string; sector?: string; limit?: number }) {
  return useQuery({
    queryKey: ['stocks', params],
    queryFn: () => api.getStocks(params),
  });
}

export function useStock(id: number) {
  return useQuery({
    queryKey: ['stocks', id],
    queryFn: () => api.getStockById(id),
    enabled: !!id,
  });
}

export function useStockBySymbol(symbol: string) {
  return useQuery({
    queryKey: ['stocks', 'symbol', symbol],
    queryFn: () => api.getStockBySymbol(symbol),
    enabled: !!symbol,
  });
}

// ETF hooks
export function useETFs(type?: 'sector' | 'industry', includeHoldings = true) {
  return useQuery({
    queryKey: ['etfs', type, includeHoldings],
    queryFn: () => api.getETFs(type, includeHoldings),
  });
}

export function useETF(id: number, includeHoldings = false) {
  return useQuery({
    queryKey: ['etfs', id, includeHoldings],
    queryFn: () => api.getETFById(id, includeHoldings),
    enabled: !!id,
  });
}

export function useETFBySymbol(symbol: string, includeHoldings = false) {
  return useQuery({
    queryKey: ['etfs', 'symbol', symbol, includeHoldings],
    queryFn: () => api.getETFBySymbol(symbol, includeHoldings),
    enabled: !!symbol,
  });
}

export function useSectorETFs() {
  return useQuery({
    queryKey: ['etfs', 'sector', 'list'],
    queryFn: () => api.getSectorETFs(),
  });
}

export function useETFHoldings(etfId: number, dataDate?: string) {
  return useQuery({
    queryKey: ['etfs', etfId, 'holdings', dataDate],
    queryFn: () => api.getETFHoldings(etfId, dataDate),
    enabled: !!etfId,
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

export function useUpdateTask() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, task }: { id: number; task: Omit<Task, 'id' | 'createdAt'> }) => 
      api.updateTask(id, task),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

export function useDeleteTask() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (id: number) => api.deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

// Holdings upload hook
export function useUploadHoldings() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({
      file,
      dataDate,
      etfType,
      etfSymbol,
      parentSector,
    }: {
      file: File;
      dataDate: string;
      etfType: 'sector' | 'industry';
      etfSymbol: string;
      parentSector?: string;
    }) => api.uploadHoldingsXlsx(file, etfType, etfSymbol, dataDate, parentSector),
    onSuccess: (data) => {
      // 刷新 ETF 数据
      queryClient.invalidateQueries({ queryKey: ['etfs'] });
      queryClient.invalidateQueries({ queryKey: ['etfs', 'symbol', data.etfSymbol] });
    },
  });
}

// Market hooks
export function useMarketRegime() {
  return useQuery({
    queryKey: ['market', 'regime'],
    queryFn: api.getMarketRegime,
    staleTime: 60 * 1000, // 1 minute
  });
}

export function useMarketSnapshot() {
  return useQuery({
    queryKey: ['market', 'snapshot'],
    queryFn: api.getMarketSnapshot,
    staleTime: 60 * 1000,
  });
}

// Broker hooks
export function useBrokerStatus() {
  return useQuery({
    queryKey: ['broker', 'status'],
    queryFn: api.getBrokerStatus,
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useConnectIBKR() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (config?: { host?: string; port?: number; client_id?: number }) => 
      api.connectIBKR(config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['broker', 'status'] });
    },
  });
}

export function useDisconnectIBKR() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.disconnectIBKR,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['broker', 'status'] });
    },
  });
}

// Health check
export function useHealthCheck() {
  return useQuery({
    queryKey: ['health'],
    queryFn: api.healthCheck,
    staleTime: 60 * 1000,
  });
}