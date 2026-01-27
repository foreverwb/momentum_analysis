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
  { id: 'tracking', label: '监控任务' },
];

export function Header({ activeSection, onNavigate }: HeaderProps) {
  const handleNavClick = (section: NavSection) => {
    console.log('Navigation clicked:', section);
    onNavigate(section);
  };

  return (
    <header 
      className="bg-[var(--bg-primary)] border-b border-[var(--border-light)] px-8 sticky top-0 z-[100]"
    >
      <div className="flex items-center justify-between h-16">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div 
            className="w-9 h-9 rounded-[var(--radius-md)] flex items-center justify-center text-base font-bold text-white"
            style={{ background: 'linear-gradient(135deg, var(--accent-purple), var(--accent-blue))' }}
          >
            &gt;_
          </div>
          <span className="text-lg font-semibold text-[var(--text-primary)]">
            Momentum
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex items-center gap-2">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => handleNavClick(item.id)}
              className={`
                px-[18px] py-2.5 text-sm font-medium rounded-[var(--radius-md)] cursor-pointer transition-all duration-150
                ${activeSection === item.id 
                  ? 'bg-[var(--accent-orange)] text-white' 
                  : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]'
                }
              `}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {/* Right Section - Market Status */}
        <div className="flex items-center gap-4">
          <div 
            className="flex items-center gap-2 px-3 py-1.5 rounded-full"
            style={{ background: 'rgba(34, 197, 94, 0.1)' }}
          >
            <span 
              className="w-2 h-2 rounded-full bg-[var(--accent-green)]"
            />
            <span className="text-[13px] text-[var(--accent-green)] font-medium">
              Risk-On
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
