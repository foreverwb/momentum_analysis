import React from 'react';
import type { NavSection } from '../../types';

interface HeaderProps {
  activeSection: NavSection;
  onNavigate: (section: NavSection) => void;
}

interface NavItem {
  id: NavSection;
  label: string;
}

const navItems: NavItem[] = [
  { id: 'core', label: '核心终端' },
  { id: 'sector', label: '板块 ETF' },
  { id: 'industry', label: '行业 ETF' },
  { id: 'momentum', label: '动能股池' },
  { id: 'tracking', label: '任务管理' },
];

// Terminal 图标
const TerminalIcon = (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="4 17 10 11 4 5"></polyline>
    <line x1="12" y1="19" x2="20" y2="19"></line>
  </svg>
);

export function Header({ activeSection, onNavigate }: HeaderProps) {
  const handleNavClick = (section: NavSection) => {
    console.log('Navigation clicked:', section);
    onNavigate(section);
  };

  return (
    <header className="mb-6 flex items-center justify-between">
      {/* Logo Section - 参考原型设计 */}
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl flex items-center justify-center shadow-lg">
          <span className="w-6 h-6 text-white">{TerminalIcon}</span>
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Momentum Trading System</h1>
        </div>
      </div>

      {/* Navigation - 白色容器内的按钮组 */}
      <div className="flex gap-2 bg-white p-1 rounded-xl border border-slate-200 shadow-sm">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => handleNavClick(item.id)}
            className={`
              px-4 py-2 rounded-sm text-sm font-medium transition-all
              ${activeSection === item.id
                ? 'bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-md'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
              }
            `}
          >
            {item.label}
          </button>
        ))}
      </div>
    </header>
  );
}