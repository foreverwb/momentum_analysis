import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
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

// Page Router Component
function PageRouter({ section }: { section: NavSection }) {
  switch (section) {
    case 'momentum':
      return <MomentumPool />;
    case 'sector':
      return <ETFOverview type="sector" />;
    case 'industry':
      return <ETFOverview type="industry" />;
    case 'tracking':
      return <Tasks />;
    case 'core':
    default:
      return <CoreTerminal />;
  }
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <MainLayout>
        {(activeSection) => <PageRouter section={activeSection} />}
      </MainLayout>
    </QueryClientProvider>
  );
}

export default App;
