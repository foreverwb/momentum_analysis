import React, { useState } from 'react';
import type { ETF, Holding } from '../../types';

interface ETFCardProps {
  etf: ETF;
  onViewHoldings?: () => void;
  onRefresh?: () => void;
}

// 根据分数获取颜色
function getScoreColor(score: number): string {
  if (score >= 85) return 'text-emerald-600';
  if (score >= 70) return 'text-blue-600';
  if (score >= 60) return 'text-amber-600';
  return 'text-slate-500';
}

// 根据分数获取背景
function getScoreBg(score: number): string {
  if (score >= 85) return 'bg-emerald-50 border-emerald-200';
  if (score >= 70) return 'bg-blue-50 border-blue-200';
  return 'bg-amber-50 border-amber-200';
}

// 期权热度颜色
function getOptionsHeatColor(heat: string): string {
  if (heat === 'Very High') return 'text-red-600';
  if (heat === 'High') return 'text-orange-600';
  if (heat === 'Medium') return 'text-amber-600';
  return 'text-slate-500';
}

// 持仓表格组件
function HoldingsTable({ holdings, maxDisplay, etfSymbol }: { holdings: Holding[]; maxDisplay: number; etfSymbol: string }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const displayHoldings = isExpanded ? holdings : holdings.slice(0, maxDisplay);

  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-bold text-slate-900">持仓明细 (Holdings)</h4>
        <span className="text-xs text-slate-600">总持仓数: {holdings.length}</span>
      </div>
      <div className="bg-slate-50 rounded-xl border border-slate-200 overflow-hidden">
        <div className="grid grid-cols-5 gap-2 p-3 bg-slate-100 text-xs font-bold text-slate-700">
          <div className="col-span-2">股票代码</div>
          <div className="text-right col-span-2">持仓权重</div>
          <div></div>
        </div>
        <div className="divide-y divide-slate-200">
          {displayHoldings.map((h, idx) => (
            <div key={idx} className="grid grid-cols-5 gap-2 p-3 hover:bg-slate-100 text-sm">
              <div className="col-span-2 flex items-center gap-2">
                <span className="font-medium">{h.ticker}</span>
              </div>
              <div className="col-span-2 text-right font-medium">{h.weight.toFixed(2)}%</div>
              <div></div>
            </div>
          ))}
        </div>
        {holdings.length > maxDisplay && (
          <div className="p-3 bg-slate-100">
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="w-full py-2 px-4 bg-white border rounded-lg text-sm font-medium flex items-center justify-center gap-2 hover:bg-slate-50 transition-colors"
            >
              <span>{isExpanded ? '收起' : `展开全部 (${holdings.length - maxDisplay} 更多)`}</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`}
              >
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function ETFCard({ etf, onViewHoldings, onRefresh }: ETFCardProps) {
  if (!etf) return null;

  const hasDetailedData = etf.relMomentum && etf.trendQuality && etf.breadth && etf.optionsConfirm;
  const compositeScore = etf.compositeScore ?? etf.score;

  // 图标定义
  const ActivityIcon = (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
    </svg>
  );

  const TrendingUpIcon = (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline>
      <polyline points="17 6 23 6 23 12"></polyline>
    </svg>
  );

  const BarChartIcon = (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="20" x2="18" y2="10"></line>
      <line x1="12" y1="20" x2="12" y2="4"></line>
      <line x1="6" y1="20" x2="6" y2="14"></line>
    </svg>
  );

  const TargetIcon = (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10"></circle>
      <circle cx="12" cy="12" r="6"></circle>
      <circle cx="12" cy="12" r="2"></circle>
    </svg>
  );

  return (
    <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-lg hover:shadow-xl transition-all">
      {/* Card Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center text-white shadow-md">
            <span className="text-xl font-bold">{etf.rank > 0 ? `#${etf.rank}` : '#-'}</span>
          </div>
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-2xl font-bold text-slate-900">{etf.symbol}</h3>
              <span className="text-slate-600">{etf.name}</span>
            </div>
            <div className="text-sm text-slate-500 flex items-center gap-2">
              {etf.type === 'sector' ? 'Sector ETF' : 'Industry ETF'}
              {etf.type === 'industry' && etf.parentSector && (
                <span className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-xs font-medium">
                  {etf.parentSector}
                </span>
              )}
              {etf.holdingsCount > 0 && (
                <span className="px-2 py-0.5 bg-emerald-50 text-emerald-600 rounded text-xs font-medium">
                  {etf.holdingsCount} 持仓
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className={`px-6 py-3 rounded-xl border ${compositeScore > 0 ? getScoreBg(compositeScore) : 'bg-slate-50 border-slate-200'}`}>
            <div className="text-xs text-slate-600 mb-1">综合分</div>
            <div className={`text-3xl font-bold ${compositeScore > 0 ? getScoreColor(compositeScore) : 'text-slate-400'}`}>
              {compositeScore > 0 ? compositeScore : '--'}
            </div>
          </div>
        </div>
      </div>

      {/* 详细分析矩阵 */}
      {hasDetailedData ? (
        <div className="grid grid-cols-4 gap-4">
          {/* 相对动量 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-4 h-4 text-blue-600">{ActivityIcon}</span>
              <h4 className="text-sm font-bold text-slate-700">相对动量</h4>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">评分</span>
                <span className={`text-lg font-bold ${getScoreColor(etf.relMomentum!.score)}`}>
                  {etf.relMomentum!.score}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">动量值</span>
                <span className="text-sm font-medium text-emerald-600">{etf.relMomentum!.value}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">排名</span>
                <span className="text-sm font-bold text-purple-600">#{etf.relMomentum!.rank}</span>
              </div>
            </div>
          </div>

          {/* 趋势质量 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-4 h-4 text-emerald-600">{TrendingUpIcon}</span>
              <h4 className="text-sm font-bold text-slate-700">趋势质量</h4>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">评分</span>
                <span className={`text-lg font-bold ${getScoreColor(etf.trendQuality!.score)}`}>
                  {etf.trendQuality!.score}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">结构</span>
                <span className="text-sm font-medium text-emerald-600">{etf.trendQuality!.structure}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">斜率</span>
                <span className="text-sm font-bold text-blue-600">{etf.trendQuality!.slope}</span>
              </div>
            </div>
          </div>

          {/* 市场广度 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-4 h-4 text-purple-600">{BarChartIcon}</span>
              <h4 className="text-sm font-bold text-slate-700">市场广度</h4>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">评分</span>
                <span className={`text-lg font-bold ${getScoreColor(etf.breadth!.score)}`}>
                  {etf.breadth!.score}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">&gt;50MA</span>
                <span className="text-sm font-medium text-emerald-600">{etf.breadth!.above50ma}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">&gt;200MA</span>
                <span className="text-sm font-bold text-blue-600">{etf.breadth!.above200ma}</span>
              </div>
            </div>
          </div>

          {/* 期权确认 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-4 h-4 text-orange-600">{TargetIcon}</span>
              <h4 className="text-sm font-bold text-slate-700">期权确认</h4>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">评分</span>
                <span className={`text-lg font-bold ${getScoreColor(etf.optionsConfirm!.score)}`}>
                  {etf.optionsConfirm!.score}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">热度</span>
                <span className={`text-sm font-medium ${getOptionsHeatColor(etf.optionsConfirm!.heat)}`}>
                  {etf.optionsConfirm!.heat}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600">相对量</span>
                <span className="text-sm font-bold text-blue-600">{etf.optionsConfirm!.relVol}</span>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* 简化版展示（当没有详细分析数据时）- 显示基础信息和数据完整度 */
        <div className="mb-4 pb-4 border-b border-slate-200">
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-1">综合评分</div>
              <div className="text-2xl font-bold text-slate-400">
                {etf.score > 0 ? etf.score.toFixed(1) : '待计算'}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-1">排名</div>
              <div className="text-2xl font-bold text-slate-400">
                {etf.rank > 0 ? `#${etf.rank}` : '待排名'}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-1">3日变化</div>
              <div className={`text-2xl font-bold ${etf.delta?.delta3d && etf.delta.delta3d > 0 ? 'text-emerald-600' : etf.delta?.delta3d && etf.delta.delta3d < 0 ? 'text-red-600' : 'text-slate-400'}`}>
                {etf.delta?.delta3d !== null && etf.delta?.delta3d !== undefined 
                  ? (etf.delta.delta3d > 0 ? '+' : '') + etf.delta.delta3d.toFixed(1) 
                  : '--'}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-1">5日变化</div>
              <div className={`text-2xl font-bold ${etf.delta?.delta5d && etf.delta.delta5d > 0 ? 'text-emerald-600' : etf.delta?.delta5d && etf.delta.delta5d < 0 ? 'text-red-600' : 'text-slate-400'}`}>
                {etf.delta?.delta5d !== null && etf.delta?.delta5d !== undefined 
                  ? (etf.delta.delta5d > 0 ? '+' : '') + etf.delta.delta5d.toFixed(1) 
                  : '--'}
              </div>
            </div>
          </div>
          {/* 数据状态提示 */}
          <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
            <div className="flex items-center gap-2 text-amber-700 text-sm">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
              <span>持仓数据已上传，等待计算动能指标。请通过「任务管理」触发计算。</span>
            </div>
          </div>
        </div>
      )}

      {/* 持仓表格 */}
      {etf.holdings && etf.holdings.length > 0 && (
        <HoldingsTable holdings={etf.holdings} maxDisplay={10} etfSymbol={etf.symbol} />
      )}
    </div>
  );
}