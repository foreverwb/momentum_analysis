import type { Stock, ETF, Task } from '../types';
import { mockStocks, mockETFs, mockTasks } from './mockData';

const API_BASE = '/api';
const USE_MOCK = true; // Set to false when backend is ready

// Helper function for API calls
async function fetchApi<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`);
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }
  return response.json();
}

// Stock APIs
export async function getStocks(): Promise<Stock[]> {
  if (USE_MOCK) {
    // Simulate network delay
    await new Promise(resolve => setTimeout(resolve, 300));
    return mockStocks;
  }
  return fetchApi<Stock[]>('/stocks');
}

export async function getStockById(id: number): Promise<Stock | undefined> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 200));
    return mockStocks.find(s => s.id === id);
  }
  return fetchApi<Stock>(`/stocks/${id}`);
}

// ETF APIs
export async function getETFs(type?: 'sector' | 'industry'): Promise<ETF[]> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 300));
    if (type) {
      return mockETFs.filter(e => e.type === type);
    }
    return mockETFs;
  }
  const query = type ? `?type=${type}` : '';
  return fetchApi<ETF[]>(`/etfs${query}`);
}

export async function getETFById(id: number): Promise<ETF | undefined> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 200));
    return mockETFs.find(e => e.id === id);
  }
  return fetchApi<ETF>(`/etfs/${id}`);
}

// Task APIs
export async function getTasks(): Promise<Task[]> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 300));
    return mockTasks;
  }
  return fetchApi<Task[]>('/tasks');
}

export async function getTaskById(id: number): Promise<Task | undefined> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 200));
    return mockTasks.find(t => t.id === id);
  }
  return fetchApi<Task>(`/tasks/${id}`);
}

export async function createTask(task: Omit<Task, 'id' | 'createdAt'>): Promise<Task> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 500));
    const newTask: Task = {
      ...task,
      id: mockTasks.length + 1,
      createdAt: new Date().toISOString().split('T')[0]
    };
    mockTasks.push(newTask);
    return newTask;
  }
  const response = await fetch(`${API_BASE}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(task)
  });
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }
  return response.json();
}
