import React, { useState } from 'react';
import { Header } from './Header';
import type { NavSection } from '../../types';

interface MainLayoutProps {
  children: (activeSection: NavSection) => React.ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  const [activeSection, setActiveSection] = useState<NavSection>('sector');

  const handleNavigate = (section: NavSection) => {
    console.log('Navigating to:', section);
    setActiveSection(section);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-slate-100 text-slate-900">
      <div className="p-4 max-w-[1600px] mx-auto">
        <Header activeSection={activeSection} onNavigate={handleNavigate} />
        <main>
          {children(activeSection)}
        </main>
      </div>
    </div>
  );
}