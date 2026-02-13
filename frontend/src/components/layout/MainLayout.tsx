import React, { useMemo, useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Header } from './Header';
import type { NavSection } from '../../types';

const STORAGE_KEY = 'momentum-radar-active-section';
const SECTION_PATH_MAP: Record<NavSection, string> = {
  core: '/core',
  sector: '/sector',
  industry: '/industry',
  momentum: '/momentum',
  tracking: '/tracking',
};

function normalizePath(pathname: string): string {
  const normalized = pathname.replace(/\/+$/, '');
  return normalized || '/';
}

function getSectionFromPath(pathname: string): NavSection {
  const path = normalizePath(pathname);
  if (path === '/core' || path.startsWith('/core/')) return 'core';
  if (path === '/industry' || path.startsWith('/industry/')) return 'industry';
  if (path === '/momentum' || path.startsWith('/momentum/')) return 'momentum';
  if (path === '/tracking' || path.startsWith('/tracking/')) return 'tracking';
  if (path === '/tasks' || path.startsWith('/tasks/')) return 'tracking';
  return 'sector';
}

export function MainLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeSection = useMemo(
    () => getSectionFromPath(location.pathname),
    [location.pathname]
  );

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, activeSection);
    } catch (e) {
      console.warn('Failed to save to localStorage:', e);
    }
  }, [activeSection]);

  const handleNavigate = (section: NavSection) => {
    const targetPath = SECTION_PATH_MAP[section];
    if (normalizePath(location.pathname) !== targetPath) {
      navigate(targetPath);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-slate-100 text-slate-900">
      <div className="p-4 max-w-[1600px] mx-auto">
        <Header activeSection={activeSection} onNavigate={handleNavigate} />
        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
