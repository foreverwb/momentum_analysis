import React from 'react';
import type { ThresholdResult } from '../../types';

interface ThresholdCardProps {
  thresholds: ThresholdResult;
  allPass: boolean;
}

export function ThresholdCard({ thresholds, allPass }: ThresholdCardProps) {
  const getStatusIcon = (status: 'PASS' | 'FAIL' | 'NO_DATA') => {
    if (status === 'PASS') return '✅';
    if (status === 'FAIL') return '❌';
    return '⚠️';
  };

  const getStatusClass = (status: 'PASS' | 'FAIL' | 'NO_DATA') => {
    if (status === 'PASS') return 'text-[var(--accent-green)]';
    if (status === 'FAIL') return 'text-[var(--accent-red)]';
    return 'text-[var(--accent-amber)]';
  };

  const getStatusText = (status: 'PASS' | 'FAIL' | 'NO_DATA') => {
    if (status === 'PASS') return 'PASS';
    if (status === 'FAIL') return 'FAIL';
    return 'NO DATA';
  };

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6 mb-6">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          门槛检查
        </h3>
        <div className={`px-4 py-2 rounded-full text-sm font-semibold ${
          allPass 
            ? 'bg-green-100 text-[var(--accent-green)]' 
            : 'bg-red-100 text-[var(--accent-red)]'
        }`}>
          {allPass ? '✓ 全部通过' : '✗ 未通过'}
        </div>
      </div>

      <div className="space-y-4">
        {/* Price above SMA50 */}
        <div className="flex items-center justify-between py-3 border-b border-[var(--border-light)] last:border-0">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{getStatusIcon(thresholds.price_above_sma50)}</span>
            <div>
              <div className="text-sm font-medium text-[var(--text-primary)]">
                价格 &gt; SMA50
              </div>
              <div className="text-xs text-[var(--text-muted)] mt-0.5">
                价格需要在50日均线之上
              </div>
            </div>
          </div>
          <div className={`text-sm font-bold ${getStatusClass(thresholds.price_above_sma50)}`}>
            {getStatusText(thresholds.price_above_sma50)}
          </div>
        </div>

        {/* RS Positive */}
        <div className="flex items-center justify-between py-3 border-b border-[var(--border-light)] last:border-0">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{getStatusIcon(thresholds.rs_positive)}</span>
            <div>
              <div className="text-sm font-medium text-[var(--text-primary)]">
                相对强度 &gt; 0
              </div>
              <div className="text-xs text-[var(--text-muted)] mt-0.5">
                相对行业表现需为正值
              </div>
            </div>
          </div>
          <div className={`text-sm font-bold ${getStatusClass(thresholds.rs_positive)}`}>
            {getStatusText(thresholds.rs_positive)}
          </div>
        </div>
      </div>

      {!allPass && (
        <div className="mt-5 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="flex items-start gap-2">
            <span className="text-amber-600 text-sm">⚠️</span>
            <p className="text-sm text-amber-800">
              该股票未通过全部门槛检查，可能存在一定风险。建议结合其他指标综合评估。
            </p>
          </div>
        </div>
      )}
    </div>
  );
}