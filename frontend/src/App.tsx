import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import { MainLayout } from './components/layout';
import { MomentumPool, ETFOverview, Tasks, CoreTerminal } from './pages';
import type { NavSection } from './types';

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 2,
    },
  },
});

const STORAGE_KEY = 'momentum-radar-active-section';
const SECTION_PATH_MAP: Record<NavSection, string> = {
  core: '/core',
  sector: '/sector',
  industry: '/industry',
  momentum: '/momentum',
  tracking: '/tracking',
};

function getDefaultPath(): string {
  try {
    const savedSection = localStorage.getItem(STORAGE_KEY) as NavSection | null;
    if (savedSection && savedSection in SECTION_PATH_MAP) {
      return SECTION_PATH_MAP[savedSection];
    }
  } catch (e) {
    console.warn('Failed to read default route from localStorage:', e);
  }
  return '/sector';
}

function LegacyTaskRouteRedirect() {
  const { taskId } = useParams();
  if (!taskId) {
    return <Navigate to="/tracking" replace />;
  }
  return <Navigate to={`/tracking/${taskId}`} replace />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to={getDefaultPath()} replace />} />
          <Route path="core" element={<CoreTerminal />} />
          <Route path="sector" element={<ETFOverview type="sector" />} />
          <Route path="industry" element={<ETFOverview type="industry" />} />
          <Route path="momentum" element={<MomentumPool />} />
          <Route path="momentum/:symbol" element={<MomentumPool />} />
          <Route path="tracking" element={<Tasks />} />
          <Route path="tracking/:taskId" element={<Tasks />} />
          <Route path="tasks" element={<Navigate to="/tracking" replace />} />
          <Route path="tasks/:taskId" element={<LegacyTaskRouteRedirect />} />
          <Route path="*" element={<Navigate to={getDefaultPath()} replace />} />
        </Route>
      </Routes>
    </QueryClientProvider>
  );
}

export default App;
