import React from 'react';

// Loading Spinner
export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center p-8">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--accent-blue)]" />
    </div>
  );
}

// Loading State
export function LoadingState({ message = '加载中...' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-[var(--text-muted)]">
      <LoadingSpinner />
      <p className="mt-4 text-sm">{message}</p>
    </div>
  );
}

// Error Message
interface ErrorMessageProps {
  error: Error | null;
  onRetry?: () => void;
}

export function ErrorMessage({ error, onRetry }: ErrorMessageProps) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center">
      <div className="text-4xl mb-4">⚠️</div>
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">加载失败</h3>
      <p className="text-sm text-[var(--text-muted)] mb-4">
        {error?.message ?? '未知错误'}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-[var(--accent-blue)] text-white rounded-[var(--radius-sm)] text-sm font-medium hover:bg-blue-600 transition-colors"
        >
          重试
        </button>
      )}
    </div>
  );
}

// Badge Component
interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'green' | 'amber' | 'red' | 'blue' | 'purple' | 'orange';
  size?: 'sm' | 'md';
}

export function Badge({ children, variant = 'default', size = 'sm' }: BadgeProps) {
  const baseClasses = "inline-flex items-center font-medium rounded-full";
  
  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm"
  };
  
  const variantClasses = {
    default: "bg-[var(--bg-tertiary)] text-[var(--text-secondary)]",
    green: "bg-green-100 text-[var(--accent-green)]",
    amber: "bg-amber-100 text-[var(--accent-amber)]",
    red: "bg-red-100 text-[var(--accent-red)]",
    blue: "bg-blue-100 text-[var(--accent-blue)]",
    purple: "bg-purple-100 text-[var(--accent-purple)]",
    orange: "bg-orange-100 text-[var(--accent-orange)]"
  };
  
  return (
    <span className={`${baseClasses} ${sizeClasses[size]} ${variantClasses[variant]}`}>
      {children}
    </span>
  );
}

// Button Component
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary';
  size?: 'sm' | 'md' | 'lg';
  children: React.ReactNode;
}

export function Button({ 
  variant = 'primary', 
  size = 'md', 
  children, 
  className = '',
  ...props 
}: ButtonProps) {
  const baseClasses = "inline-flex items-center justify-center gap-2 font-medium rounded-[var(--radius-sm)] transition-all duration-150 cursor-pointer border-none";
  
  const sizeClasses = {
    sm: "px-3 py-1.5 text-xs",
    md: "px-5 py-2.5 text-sm",
    lg: "px-6 py-3 text-base"
  };
  
  const variantClasses = {
    primary: "bg-[var(--accent-blue)] text-white hover:bg-blue-600",
    secondary: "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-light)]"
  };
  
  return (
    <button 
      className={`${baseClasses} ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

// Select Dropdown
interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  options: { value: string; label: string }[];
}

export function Select({ options, className = '', ...props }: SelectProps) {
  return (
    <select
      className={`px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-md)] text-sm text-[var(--text-secondary)] cursor-pointer min-w-[140px] ${className}`}
      {...props}
    >
      {options.map(option => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

// Empty State
interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon = '📭', title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center">
      <div className="text-5xl mb-4">{icon}</div>
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">{title}</h3>
      {description && (
        <p className="text-sm text-[var(--text-muted)] mb-4 max-w-md">{description}</p>
      )}
      {action}
    </div>
  );
}
