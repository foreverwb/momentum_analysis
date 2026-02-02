// ============================================================================
// 修复文件: frontend/src/components/stock/StockDetailView.tsx
// 修复内容:
// 1. 添加期权覆盖Tab（参考momentum-radar-complete.html）
// 2. 修复数据显示问题
// ============================================================================

import React, { useState } from 'react';
import { useStockDetail } from '../../hooks/useData';
import type { StockDetail } from '../../types';
import { ThresholdCard } from './ThresholdCard';
import { ScoreBreakdownPanel } from './ScoreBreakdownPanel';
import { OptionsOverlayTab } from './OptionsOverlayTab';

interface StockDetailViewProps {
  symbol: string;
  onBack: () => void;
}

export function StockDetailView({ symbol, onBack }: StockDetailViewProps) {
  const { data: stock, isLoading, error } = useStockDetail(symbol);
  // 修复：添加 'options' 作为第三个Tab选项
  const [activeTab, setActiveTab] = useState<'overview' | 'breakdown' | 'options'>('overview');

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[var(--accent-blue)] mx-auto mb-4" />
          <p className="text-[var(--text-muted)]">加载中...</p>
        </div>
      </div>
    );
  }

  if (error || !stock) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <p className="text-[var(--accent-red)] text-lg mb-2">加载失败</p>
          <p className="text-[var(--text-muted)] mb-4">
            {error instanceof Error ? error.message : '无法加载股票详情'}
          </p>
          <button
            onClick={onBack}
            className="px-4 py-2 bg-[var(--accent-blue)] text-white rounded-lg hover:opacity-90 transition-opacity"
          >
            返回列表
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto">

      {/* Stock Header */}
      <StockHeader stock={stock} />

      {/* Quick Stats Bar */}
      <QuickStatsBar stock={stock} />

      {/* Threshold Check */}
      {stock.thresholds && (
        <ThresholdCard
          thresholds={stock.thresholds}
          allPass={stock.thresholdsPass ?? false}
        />
      )}

      {/* Tabs - 修复：添加期权覆盖Tab */}
      <div className="mb-6">
        <div className="flex gap-2 border-b border-[var(--border-light)]">
          <button
            className={`px-6 py-3 text-sm font-medium transition-colors ${
              activeTab === 'overview'
                ? 'text-[var(--accent-blue)] border-b-2 border-[var(--accent-blue)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            onClick={() => setActiveTab('overview')}
          >
            综合概览
          </button>
          <button
            className={`px-6 py-3 text-sm font-medium transition-colors ${
              activeTab === 'breakdown'
                ? 'text-[var(--accent-blue)] border-b-2 border-[var(--accent-blue)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            onClick={() => setActiveTab('breakdown')}
          >
            四维评分详情
          </button>
          {/* 新增：期权覆盖Tab */}
          <button
            className={`px-6 py-3 text-sm font-medium transition-colors ${
              activeTab === 'options'
                ? 'text-[var(--accent-blue)] border-b-2 border-[var(--accent-blue)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            onClick={() => setActiveTab('options')}
          >
            期权覆盖
          </button>
        </div>
      </div>

      {/* Tab Content - 修复：添加期权覆盖Tab内容 */}
      {activeTab === 'overview' ? (
        <OverviewTab stock={stock} />
      ) : activeTab === 'breakdown' ? (
        <BreakdownTab stock={stock} />
      ) : (
        <OptionsOverlayTab stock={stock} />
      )}
    </div>
  );
}

// Stock Header Component
function StockHeader({ stock }: { stock: StockDetail }) {
  const formatPrice = (price?: number) => {
    if (price === null || price === undefined) return '--';
    return `$${price.toFixed(2)}`;
  };

  const formatChange = (change?: number, changePercent?: number) => {
    if (change === null || change === undefined) return '--';
    const sign = change >= 0 ? '+' : '';
    const percentText = changePercent !== null && changePercent !== undefined
      ? ` (${sign}${changePercent.toFixed(2)}%)`
      : '';
    return `${sign}${change.toFixed(2)}${percentText}`;
  };

  const getChangeColor = (change?: number) => {
    if (change === null || change === undefined) return 'var(--text-muted)';
    return change >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  };

  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6 mb-6">
      <div className="flex items-start justify-between">
        {/* Left: Stock Info */}
        <div className="flex items-center gap-4">
          {/* Rank Badge */}
          <div 
            className="w-16 h-16 rounded-full flex items-center justify-center text-white text-2xl font-bold"
            style={{ background: 'linear-gradient(135deg, var(--accent-purple), #a855f7)' }}
          >
            {stock.rank || '?'}
          </div>

          {/* Stock Title */}
          <div>
            <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">
              {stock.symbol}
            </h1>
            <p className="text-lg text-[var(--text-secondary)] mb-3">
              {stock.name || '--'}
            </p>
            <div className="flex items-center gap-3 text-sm">
              <span className="px-3 py-1 bg-blue-100 text-[var(--accent-blue)] rounded-full">
                板块: {stock.sector || '--'}
              </span>
              <span className="px-3 py-1 bg-purple-100 text-[var(--accent-purple)] rounded-full">
                行业: {stock.industry || '--'}
              </span>
              {stock.marketCap && (
                <span className="px-3 py-1 bg-gray-100 text-[var(--text-secondary)] rounded-full">
                  市值: ${(stock.marketCap / 1e9).toFixed(1)}B
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right: Price Info */}
        <div className="text-right">
          <div className="text-4xl font-bold text-[var(--text-primary)] mb-2">
            {formatPrice(stock.price)}
          </div>
          <div 
            className="text-lg font-semibold"
            style={{ color: getChangeColor(stock.change) }}
          >
            {formatChange(stock.change, stock.changePercent)}
          </div>
        </div>
      </div>

      {/* Score Row */}
      <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-[var(--border-light)]">
        <ScoreItem
          label="综合得分"
          value={stock.totalScore}
          isPrimary
        />
        <ScoreItem
          label="价格动能"
          value={stock.momentumScore}
          subtext="42.25% 权重"
        />
        <ScoreItem
          label="趋势结构"
          value={stock.technicalScore}
          subtext="22.75% 权重"
        />
        <ScoreItem
          label="期权覆盖"
          value={stock.optionsScore}
          subtext="20% 权重"
        />
      </div>
    </div>
  );
}

function ScoreItem({ 
  label, 
  value, 
  subtext, 
  isPrimary 
}: { 
  label: string; 
  value?: number; 
  subtext?: string; 
  isPrimary?: boolean;
}) {
  const getScoreColor = (score?: number) => {
    if (score === null || score === undefined) return 'var(--text-muted)';
    if (score >= 60) return 'var(--accent-green)';
    if (score >= 40) return 'var(--accent-amber)';
    return 'var(--accent-blue)';
  };

  return (
    <div className="text-center">
      <div className="text-xs text-[var(--text-muted)] mb-1">{label}</div>
      <div 
        className={`${isPrimary ? 'text-3xl' : 'text-2xl'} font-bold`}
        style={{ color: getScoreColor(value) }}
      >
        {value?.toFixed(1) ?? '--'}
      </div>
      {subtext && (
        <div className="text-xs text-[var(--text-muted)] mt-1">{subtext}</div>
      )}
    </div>
  );
}

// Quick Stats Bar Component - 修复：改进数据显示
function QuickStatsBar({ stock }: { stock: StockDetail }) {
  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined) return '--';
    return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
  };

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined) return '--';
    return value.toFixed(2);
  };

  // 修复：获取scoreBreakdown中的数据
  const momentumData = stock.scoreBreakdown?.momentum?.data;
  const optionsData = stock.scoreBreakdown?.options?.data;

  const stats = [
    { label: '20日收益', value: formatPercent(momentumData?.return_20d ?? stock.return20d) },
    { label: '63日收益', value: formatPercent(momentumData?.return_63d ?? stock.return63d) },
    { label: '相对强度', value: formatNumber(momentumData?.rs_20d ?? stock.rs20d) },
    { label: 'RSI', value: formatNumber(stock.rsi) },
    { label: 'IVR', value: formatNumber(optionsData?.ivr ?? stock.ivr) },
    { label: '量比', value: formatNumber(stock.volumeRatio) },
  ];

  return (
    <div className="grid grid-cols-6 gap-4 mb-6">
      {stats.map((stat, index) => (
        <div 
          key={index}
          className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-lg p-4 text-center"
        >
          <div className="text-xs text-[var(--text-muted)] mb-1">
            {stat.label}
          </div>
          <div className="text-lg font-bold text-[var(--text-primary)]">
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  );
}

// Overview Tab Component - 修复：改进数据显示逻辑
function OverviewTab({ stock }: { stock: StockDetail }) {
  // 修复：从scoreBreakdown获取数据
  const technicalData = stock.scoreBreakdown?.technical?.data;
  const volumeData = stock.scoreBreakdown?.volume?.data;
  const optionsData = stock.scoreBreakdown?.options?.data;

  const formatPrice = (value?: number | null) => {
    if (value === null || value === undefined || value === 0) return '$--';
    return `$${value.toFixed(2)}`;
  };

  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined || value === 0) return '--';
    return value.toLocaleString();
  };

  const metrics = [
    { label: '当前价格', value: formatPrice(technicalData?.price ?? stock.price) },
    { label: '20日均线', value: formatPrice(technicalData?.sma20 ?? stock.sma20) },
    { label: '50日均线', value: formatPrice(technicalData?.sma50 ?? stock.sma50) },
    { label: '200日均线', value: formatPrice(technicalData?.sma200 ?? stock.sma200) },
    { label: '成交量', value: formatNumber(volumeData?.volume ?? stock.volume) },
    { label: '平均成交量', value: formatNumber(volumeData?.avg_volume ?? stock.avgVolume) },
    { label: '隐含波动率', value: optionsData?.implied_volatility?.toFixed(2) ?? stock.impliedVolatility?.toFixed(2) ?? '--' },
    { label: '持仓量', value: formatNumber(optionsData?.open_interest ?? stock.openInterest) },
  ];

  return (
    <div>
      <h3 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
        关键指标数据
      </h3>
      <div className="bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-lg)] p-6">
        <div className="grid grid-cols-4 gap-4">
          {metrics.map((metric, index) => (
            <div 
              key={index}
              className="flex flex-col py-3 px-4 bg-[var(--bg-secondary)] rounded-lg"
            >
              <span className="text-xs text-[var(--text-muted)] mb-1">
                {metric.label}
              </span>
              <span className="text-base font-semibold text-[var(--text-primary)]">
                {metric.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Breakdown Tab Component
function BreakdownTab({ stock }: { stock: StockDetail }) {
  if (!stock.scoreBreakdown) {
    return (
      <div className="text-center py-12">
        <p className="text-[var(--text-muted)]">暂无评分细分数据</p>
      </div>
    );
  }

  const { momentum, technical, volume, options } = stock.scoreBreakdown;

  return (
    <div className="space-y-6">
      {/* Price Momentum */}
      {momentum && (
        <ScoreBreakdownPanel
          title="价格动能"
          icon="📈"
          score={momentum.score}
          weight="42.25%"
          breakdown={momentum.data.score_breakdown || {}}
          data={{
            return_20d: momentum.data.return_20d,
            return_63d: momentum.data.return_63d,
            rs_20d: momentum.data.rs_20d,
          }}
          description="基于短期和中期价格表现的动能评估"
        />
      )}

      {/* Trend Structure */}
      {technical && (
        <ScoreBreakdownPanel
          title="趋势结构"
          icon="〰️"
          score={technical.score}
          weight="22.75%"
          breakdown={technical.data.score_breakdown || {}}
          data={{
            price: technical.data.price,
            sma20: technical.data.sma20,
            sma50: technical.data.sma50,
            sma200: technical.data.sma200,
            rsi: technical.data.rsi,
            dist_from_52w_high: technical.data.dist_from_52w_high,
          }}
          description="基于技术指标和均线系统的趋势评估"
        />
      )}

      {/* Volume Confirmation */}
      {volume && (
        <ScoreBreakdownPanel
          title="量价确认"
          icon="📊"
          score={volume.score}
          weight="15%"
          breakdown={{}}
          data={{
            volume: volume.data.volume,
            avg_volume: volume.data.avg_volume,
            volume_ratio: volume.data.volume_ratio,
          }}
          description="基于成交量变化的确认信号"
        />
      )}

      {/* Options Coverage */}
      {options && (
        <ScoreBreakdownPanel
          title="期权覆盖"
          icon="🛡️"
          score={options.score}
          weight="20%"
          breakdown={{}}
          data={{
            heat_type: options.data.heat_type,
            heat_score: options.data.heat_score,
            risk_score: options.data.risk_score,
            ivr: options.data.ivr,
            implied_volatility: options.data.implied_volatility,
            open_interest: options.data.open_interest,
          }}
          description="基于期权市场活动和波动率的风险评估"
        />
      )}
    </div>
  );
}