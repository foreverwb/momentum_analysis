import React, { useState, useEffect } from 'react';
import { Header } from './Header';
import type { NavSection } from '../../types';

interface MainLayoutProps {
  children: (activeSection: NavSection) => React.ReactNode;
}

const STORAGE_KEY = 'momentum-radar-active-section';

// 验证是否为有效的导航项
function isValidSection(section: string): section is NavSection {
  return ['core', 'sector', 'industry', 'momentum', 'tracking'].includes(section);
}

export function MainLayout({ children }: MainLayoutProps) {
  // 从 localStorage 读取初始状态
  const [activeSection, setActiveSection] = useState<NavSection>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && isValidSection(saved)) {
        return saved;
      }
    } catch (e) {
      console.warn('Failed to read from localStorage:', e);
    }
    return 'sector'; // 默认页面
  });

  // 当 activeSection 变化时保存到 localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, activeSection);
    } catch (e) {
      console.warn('Failed to save to localStorage:', e);
    }
  }, [activeSection]);

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