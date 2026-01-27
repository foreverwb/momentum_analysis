import React, { useState } from 'react';
import { Header } from './Header';
import type { NavSection } from '../../types';

interface MainLayoutProps {
  children: (activeSection: NavSection) => React.ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  const [activeSection, setActiveSection] = useState<NavSection>('momentum');

  const handleNavigate = (section: NavSection) => {
    console.log('Navigating to:', section);
    setActiveSection(section);
  };

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)]">
      <Header activeSection={activeSection} onNavigate={handleNavigate} />
      <main className="py-7 px-8 max-w-[1600px] mx-auto">
        {children(activeSection)}
      </main>
    </div>
  );
}
