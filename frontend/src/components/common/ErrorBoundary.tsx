import React, { Component, ReactNode } from 'react';

// ============================================================================
// Error Boundary Component
// ============================================================================

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

/**
 * ErrorBoundary Component
 * 
 * 捕获子组件树中的 JavaScript 错误，记录错误并显示备用 UI
 * 
 * 使用方式:
 * ```tsx
 * <ErrorBoundary fallback={<ErrorFallback />}>
 *   <YourComponent />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    // 更新 state 使下一次渲染能够显示降级后的 UI
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    // 记录错误信息
    this.setState({ errorInfo });
    
    // 调用错误回调
    this.props.onError?.(error, errorInfo);
    
    // 在开发环境打印错误
    if (process.env.NODE_ENV === 'development') {
      console.error('ErrorBoundary caught an error:', error, errorInfo);
    }
  }

  handleRetry = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      // 如果提供了自定义 fallback，使用它
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // 默认错误 UI
      return (
        <DefaultErrorFallback
          error={this.state.error}
          errorInfo={this.state.errorInfo}
          onRetry={this.handleRetry}
        />
      );
    }

    return this.props.children;
  }
}

// ============================================================================
// Default Error Fallback UI
// ============================================================================

interface DefaultErrorFallbackProps {
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  onRetry?: () => void;
}

function DefaultErrorFallback({ error, errorInfo, onRetry }: DefaultErrorFallbackProps) {
  const [showDetails, setShowDetails] = React.useState(false);

  return (
    <div className="min-h-[300px] flex items-center justify-center p-8">
      <div className="max-w-lg w-full bg-[var(--bg-primary)] border border-red-200 rounded-[var(--radius-lg)] p-8 text-center shadow-lg">
        {/* Error Icon */}
        <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-red-100 flex items-center justify-center">
          <svg
            className="w-8 h-8 text-red-500"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>

        {/* Error Message */}
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-2">
          出错了
        </h2>
        <p className="text-[var(--text-muted)] mb-6">
          抱歉，页面遇到了一些问题。请尝试刷新页面或稍后再试。
        </p>

        {/* Action Buttons */}
        <div className="flex gap-3 justify-center mb-6">
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-6 py-2.5 bg-[var(--accent-blue)] text-white rounded-lg font-medium hover:opacity-90 transition-opacity"
            >
              重试
            </button>
          )}
          <button
            onClick={() => window.location.reload()}
            className="px-6 py-2.5 bg-[var(--bg-secondary)] text-[var(--text-secondary)] rounded-lg font-medium hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            刷新页面
          </button>
        </div>

        {/* Error Details (Development) */}
        {process.env.NODE_ENV === 'development' && error && (
          <div className="text-left">
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="text-sm text-[var(--accent-blue)] hover:underline mb-2"
            >
              {showDetails ? '隐藏' : '显示'}错误详情
            </button>
            
            {showDetails && (
              <div className="mt-3 p-4 bg-[var(--bg-secondary)] rounded-lg text-left overflow-auto">
                <p className="text-sm font-medium text-red-600 mb-2">
                  {error.name}: {error.message}
                </p>
                {errorInfo?.componentStack && (
                  <pre className="text-xs text-[var(--text-muted)] whitespace-pre-wrap">
                    {errorInfo.componentStack}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Page-Level Error Fallback
// ============================================================================

interface PageErrorFallbackProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  onGoHome?: () => void;
}

export function PageErrorFallback({
  title = '页面加载失败',
  message = '抱歉，无法加载此页面。请检查网络连接后重试。',
  onRetry,
  onGoHome,
}: PageErrorFallbackProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg-secondary)] p-8">
      <div className="max-w-md w-full bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-10 text-center">
        {/* Illustration */}
        <div className="text-6xl mb-6">💥</div>

        {/* Title */}
        <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-3">
          {title}
        </h1>

        {/* Message */}
        <p className="text-[var(--text-muted)] mb-8">
          {message}
        </p>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-6 py-2.5 bg-[var(--accent-blue)] text-white rounded-lg font-medium hover:opacity-90 transition-opacity"
            >
              重新加载
            </button>
          )}
          {onGoHome && (
            <button
              onClick={onGoHome}
              className="px-6 py-2.5 bg-[var(--bg-secondary)] text-[var(--text-secondary)] rounded-lg font-medium hover:bg-[var(--bg-tertiary)] transition-colors"
            >
              返回首页
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Component-Level Error Fallback
// ============================================================================

interface ComponentErrorFallbackProps {
  componentName?: string;
  onRetry?: () => void;
}

export function ComponentErrorFallback({
  componentName,
  onRetry,
}: ComponentErrorFallbackProps) {
  return (
    <div className="p-6 bg-red-50 border border-red-200 rounded-lg text-center">
      <div className="text-2xl mb-2">⚠️</div>
      <p className="text-sm text-red-600 mb-3">
        {componentName ? `${componentName} 加载失败` : '组件加载失败'}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-1.5 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors"
        >
          重试
        </button>
      )}
    </div>
  );
}

// ============================================================================
// HOC: withErrorBoundary
// ============================================================================

/**
 * 高阶组件：为组件添加错误边界
 * 
 * 使用方式:
 * ```tsx
 * const SafeComponent = withErrorBoundary(YourComponent, {
 *   fallback: <CustomFallback />,
 *   onError: (error) => logError(error)
 * });
 * ```
 */
export function withErrorBoundary<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  errorBoundaryProps?: Omit<ErrorBoundaryProps, 'children'>
) {
  const displayName = WrappedComponent.displayName || WrappedComponent.name || 'Component';

  const ComponentWithErrorBoundary = (props: P) => (
    <ErrorBoundary {...errorBoundaryProps}>
      <WrappedComponent {...props} />
    </ErrorBoundary>
  );

  ComponentWithErrorBoundary.displayName = `withErrorBoundary(${displayName})`;

  return ComponentWithErrorBoundary;
}

// ============================================================================
// Export
// ============================================================================

export default ErrorBoundary;
