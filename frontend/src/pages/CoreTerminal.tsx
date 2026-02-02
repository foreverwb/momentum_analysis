import React, { useState } from 'react';
import * as api from '../services/api';

// ============ 类型定义 ============
interface MarketRegime {
  status: 'A' | 'B' | 'C';
  spy: {
    price: number;
    sma20: number;
    sma50: number;
    return20d?: number;
    sma20Slope?: number;
    distToSma20?: number | null;
    distToSma50?: number | null;
  };
  vix: number | null;
  breadth: number;
}

interface Sector {
  code: string;
  name: string;
  score: number;
  momentum: string;
  heat: 'high' | 'medium' | 'low';
  trend: 'strong' | 'stable' | 'weak';
}

interface Industry {
  name: string;
  fullName: string;
  score: number;
  relVol: number;
  ivr: number;
  change: string;
}

interface SectorDetail {
  code: string;
  name: string;
  trendLevel: string;
  relMomentum: string;
  breadth: string;
  capitalFlow: string;
  trendQuality: number;
  industries: Industry[];
}

// ============ SVG 图标组件 ============
const FlameIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"></path>
  </svg>
);

const BarChartIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <line x1="18" y1="20" x2="18" y2="10"></line>
    <line x1="12" y1="20" x2="12" y2="4"></line>
    <line x1="6" y1="20" x2="6" y2="14"></line>
  </svg>
);

const RefreshIcon = ({ className = '' }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <polyline points="23 4 23 10 17 10"></polyline>
    <polyline points="1 20 1 14 7 14"></polyline>
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
  </svg>
);

// ============ Mock 数据 ============
const marketRegime: MarketRegime = {
  status: 'A',
  spy: { price: 485.20, sma20: 472.5, sma50: 460.0, return20d: 0.028, sma20Slope: 0.35, distToSma20: 0.027, distToSma50: 0.055 },
  vix: 14.2,
  breadth: 68
};

const sectors: Sector[] = [
  { code: 'XLK', name: '科技', score: 92, momentum: '+12.3%', heat: 'high', trend: 'strong' },
  { code: 'XLF', name: '金融', score: 78, momentum: '+6.8%', heat: 'medium', trend: 'stable' },
  { code: 'XLE', name: '能源', score: 85, momentum: '+9.1%', heat: 'high', trend: 'strong' },
  { code: 'XLV', name: '医疗', score: 65, momentum: '+3.2%', heat: 'low', trend: 'weak' },
  { code: 'XLI', name: '工业', score: 72, momentum: '+5.6%', heat: 'medium', trend: 'stable' },
  { code: 'XLY', name: '消费', score: 88, momentum: '+10.5%', heat: 'high', trend: 'strong' }
];

const sectorDetails: Record<string, SectorDetail> = {
  'XLK': {
    code: 'XLK',
    name: '科技板块',
    trendLevel: 'Strong',
    relMomentum: '+12.3%',
    breadth: '75%',
    capitalFlow: '+$2.1B',
    trendQuality: 88,
    industries: [
      { name: 'SOXX', fullName: '半导体', score: 95, relVol: 1.8, ivr: 72, change: '+15.2%' },
      { name: 'IGV', fullName: '软件', score: 88, relVol: 1.4, ivr: 65, change: '+11.8%' },
      { name: 'SMH', fullName: '半导体设备', score: 91, relVol: 1.6, ivr: 68, change: '+13.5%' }
    ]
  },
  'XLF': {
    code: 'XLF',
    name: '金融板块',
    trendLevel: 'Stable',
    relMomentum: '+6.8%',
    breadth: '62%',
    capitalFlow: '+$0.8B',
    trendQuality: 72,
    industries: [
      { name: 'KBE', fullName: '银行', score: 75, relVol: 1.2, ivr: 55, change: '+7.2%' },
      { name: 'KIE', fullName: '保险', score: 71, relVol: 1.1, ivr: 48, change: '+5.8%' },
      { name: 'XLF', fullName: '多元金融', score: 78, relVol: 1.3, ivr: 52, change: '+6.5%' }
    ]
  },
  'XLE': {
    code: 'XLE',
    name: '能源板块',
    trendLevel: 'Strong',
    relMomentum: '+9.1%',
    breadth: '68%',
    capitalFlow: '+$1.5B',
    trendQuality: 82,
    industries: [
      { name: 'XOP', fullName: '油气勘探', score: 88, relVol: 1.7, ivr: 70, change: '+12.1%' },
      { name: 'OIH', fullName: '油服', score: 82, relVol: 1.5, ivr: 65, change: '+8.5%' },
      { name: 'AMLP', fullName: '能源基建', score: 76, relVol: 1.2, ivr: 58, change: '+6.2%' }
    ]
  },
  'XLV': {
    code: 'XLV',
    name: '医疗板块',
    trendLevel: 'Weak',
    relMomentum: '+3.2%',
    breadth: '48%',
    capitalFlow: '-$0.3B',
    trendQuality: 58,
    industries: [
      { name: 'XBI', fullName: '生物科技', score: 62, relVol: 1.1, ivr: 68, change: '+2.8%' },
      { name: 'IHI', fullName: '医疗器械', score: 68, relVol: 1.0, ivr: 45, change: '+4.2%' },
      { name: 'XLV', fullName: '制药', score: 65, relVol: 0.9, ivr: 42, change: '+3.0%' }
    ]
  },
  'XLI': {
    code: 'XLI',
    name: '工业板块',
    trendLevel: 'Stable',
    relMomentum: '+5.6%',
    breadth: '58%',
    capitalFlow: '+$0.5B',
    trendQuality: 68,
    industries: [
      { name: 'ITA', fullName: '航空航天', score: 78, relVol: 1.3, ivr: 55, change: '+7.8%' },
      { name: 'IYT', fullName: '运输', score: 70, relVol: 1.1, ivr: 50, change: '+5.2%' },
      { name: 'XLI', fullName: '工业设备', score: 72, relVol: 1.2, ivr: 48, change: '+5.8%' }
    ]
  },
  'XLY': {
    code: 'XLY',
    name: '消费板块',
    trendLevel: 'Strong',
    relMomentum: '+10.5%',
    breadth: '72%',
    capitalFlow: '+$1.8B',
    trendQuality: 85,
    industries: [
      { name: 'XRT', fullName: '零售', score: 86, relVol: 1.5, ivr: 62, change: '+11.2%' },
      { name: 'PBJ', fullName: '餐饮', score: 82, relVol: 1.3, ivr: 55, change: '+9.8%' },
      { name: 'XHB', fullName: '房建', score: 78, relVol: 1.4, ivr: 58, change: '+8.5%' }
    ]
  }
};

// ============ 辅助函数 ============
function getRegimeColor(status: 'A' | 'B' | 'C'): string {
  if (status === 'A') return 'from-emerald-400 to-green-500';
  if (status === 'B') return 'from-amber-400 to-orange-500';
  return 'from-red-400 to-rose-500';
}

function getRegimeText(status: 'A' | 'B' | 'C'): string {
  if (status === 'A') return 'Risk-On 满火力';
  if (status === 'B') return 'Neutral 半火力';
  return 'Risk-Off 低火力';
}

function getHeatColor(heat: 'high' | 'medium' | 'low'): string {
  if (heat === 'high') return 'text-red-500';
  if (heat === 'medium') return 'text-amber-500';
  return 'text-slate-400';
}

function getScoreColor(score: number): string {
  if (score >= 85) return 'text-emerald-600';
  if (score >= 70) return 'text-blue-600';
  if (score >= 60) return 'text-amber-600';
  return 'text-slate-500';
}

function getTrendLevelColor(level: string): string {
  if (level === 'Strong') return 'bg-emerald-50 border-emerald-200 text-emerald-600';
  if (level === 'Stable') return 'bg-blue-50 border-blue-200 text-blue-600';
  return 'bg-amber-50 border-amber-200 text-amber-600';
}

// ============ Regime 计算辅助 ============
const percentDiff = (price?: number, base?: number): number | null => {
  if (price === undefined || base === undefined || base === 0) return null;
  return (price - base) / base;
};

const formatPercent = (value: number | null | undefined, digits = 1): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  const pct = value * 100;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(digits)}%`;
};

const formatNumber = (value: number | null | undefined, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
};

function computeRegime(inputs: { price?: number; sma50?: number; return20d?: number; sma20Slope?: number; breadth?: number; dist50?: number | null }): 'A' | 'B' | 'C' {
  const { price, sma50, return20d, sma20Slope, breadth, dist50 } = inputs;
  if (price === undefined || sma50 === undefined) return 'B';

  const diff50 = dist50 !== null && dist50 !== undefined ? dist50 : percentDiff(price, sma50);
  const near50 = diff50 !== null && Math.abs(diff50) < 0.02; // ±2%

  const slopeUp = (sma20Slope ?? 0) > 0;
  const returnUp = (return20d ?? 0) > 0;
  const priceAbove50 = price > sma50;
  const priceBelow50 = price < sma50;

  const breadthGood = breadth === undefined ? true : breadth >= 50;
  const breadthCollapse = breadth !== undefined && breadth > 0 && breadth < 30;

  if ((priceBelow50 && (return20d ?? 0) < 0) || breadthCollapse) return 'C';
  if (near50) return 'B';
  if (priceAbove50 && (slopeUp || returnUp) && breadthGood) return 'A';
  return 'B';
}

// ============ 主组件 ============
export function CoreTerminal() {
  const [selectedSector, setSelectedSector] = useState<string>('XLK');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [marketStatus, setMarketStatus] = useState<{
    status?: string;
    spy?: { price?: number; sma20?: number; sma50?: number; return20d?: number; sma20Slope?: number; distToSma20?: number | null; distToSma50?: number | null };
    vix?: number | null;
    breadth?: number;
  } | null>(null);
  const [marketStatusError, setMarketStatusError] = useState<string | null>(null);
  const [manualInputs, setManualInputs] = useState<{
    price?: string;
    sma20?: string;
    sma50?: string;
    return20d?: string; // 百分比
    breadth?: string;
  }>({});

  const currentSectorDetail = sectorDetails[selectedSector] || sectorDetails['XLK'];

  const numberFromManual = (value?: string) => (value !== undefined && value !== '' ? Number(value) : undefined);

  const baseSpy = marketStatus?.spy || marketRegime.spy;
  const priceVal = numberFromManual(manualInputs.price) ?? baseSpy.price;
  const sma20Val = numberFromManual(manualInputs.sma20) ?? baseSpy.sma20;
  const sma50Val = numberFromManual(manualInputs.sma50) ?? baseSpy.sma50;
  const return20Val = numberFromManual(manualInputs.return20d) !== undefined
    ? Number(manualInputs.return20d) / 100
    : baseSpy.return20d;
  const dist50Val = percentDiff(priceVal, sma50Val);

  const effectiveSpy = {
    price: priceVal,
    sma20: sma20Val,
    sma50: sma50Val,
    return20d: return20Val,
    sma20Slope: baseSpy.sma20Slope,
    distToSma50: dist50Val,
  };

  const effectiveBreadth = numberFromManual(manualInputs.breadth) ?? marketStatus?.breadth ?? marketRegime.breadth;

  const computedStatus = computeRegime({
    price: effectiveSpy.price,
    sma50: effectiveSpy.sma50,
    return20d: effectiveSpy.return20d,
    sma20Slope: effectiveSpy.sma20Slope,
    breadth: effectiveBreadth,
    dist50: effectiveSpy.distToSma50 ?? percentDiff(effectiveSpy.price, effectiveSpy.sma50),
  });

  const displayRegime = {
    status: computedStatus,
    spy: effectiveSpy,
    vix: marketStatus?.vix !== undefined ? marketStatus.vix : marketRegime.vix,
    breadth: effectiveBreadth,
  };

  const dist20 = percentDiff(effectiveSpy.price, effectiveSpy.sma20);
  const dist50 = effectiveSpy.distToSma50 ?? percentDiff(effectiveSpy.price, effectiveSpy.sma50);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setMarketStatusError(null);
    try {
      const response = await api.getMarketRegime();
      const spy = (response.spy || {}) as any;
      const indicators = (response.indicators || {}) as any;
      setMarketStatus({
        status: response.status,
        spy: {
          price: spy.price,
          sma20: spy.sma20,
          sma50: spy.sma50,
          distToSma50: spy.dist_to_sma50 ?? indicators.dist_to_sma50 ?? percentDiff(spy.price, spy.sma50),
          return20d: spy.return_20d ?? indicators.return_20d,
          sma20Slope: spy.sma20_slope ?? indicators.sma20_slope,
        },
        vix: response.vix ?? null,
        breadth: (response as any).breadth,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '刷新失败';
      setMarketStatusError(message);
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <div>
      {/* 页面标题和刷新按钮 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="text-xl">🚀</span>
          <h1 className="text-xl font-semibold text-slate-900">核心终端</h1>
          <span className="text-sm text-slate-500">实时市场状态监控</span>
        </div>
        <button
          onClick={handleRefresh}
          className="px-4 py-2 text-sm font-medium rounded-sm bg-blue-600 text-white hover:bg-blue-700 transition-colors flex items-center gap-2"
        >
          <RefreshIcon className={isRefreshing ? 'animate-spin' : ''} />
          Refresh Index
        </button>
      </div>
      {/* 显示错误信息 */}
      {marketStatusError && (
        <div className="mb-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700">
          <p className="text-sm font-medium">❌ 数据刷新失败: {marketStatusError}</p>
        </div>
      )}

      {/* Regime Gate 状态卡 - 渐变背景大卡片 */}
      <div className={`mb-6 p-6 rounded-2xl bg-gradient-to-r ${getRegimeColor(displayRegime.status)} shadow-xl text-white`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 bg-white/30 rounded-xl flex items-center justify-center backdrop-blur-sm">
              <span className="text-3xl font-bold">{displayRegime.status}</span>
            </div>
            <div>
              <h2 className="text-2xl font-bold mb-1">{getRegimeText(displayRegime.status)}</h2>
              <p className="text-white/90 text-sm">市场环境评估 · {marketStatus ? '实时更新' : '今日更新'}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 lg:gap-6">
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">$SPY</div>
              <div className="text-2xl font-bold">${displayRegime.spy?.price !== undefined ? displayRegime.spy.price.toFixed(2) : 'N/A'}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">20DMA</div>
              <div className="text-2xl font-bold">{formatPercent(dist20)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">50DMA</div>
              <div className={`text-2xl font-bold ${Math.abs(dist50 ?? 0) < 0.02 ? 'text-amber-200' : ''}`}>{formatPercent(dist50)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">20日收益率</div>
              <div className="text-2xl font-bold">{formatPercent(displayRegime.spy?.return20d ?? null, 2)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">20DMA Slope</div>
              <div className="text-2xl font-bold">{formatNumber(displayRegime.spy?.sma20Slope ?? null, 3)}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-white/80 mb-1">市场广度</div>
              <div className="text-2xl font-bold">{displayRegime.breadth !== undefined ? `${displayRegime.breadth}%` : 'N/A'}</div>
            </div>
          </div>
        </div>
      </div>

      {/* 三栏布局：左侧板块热力榜 + 右侧板块详情 */}
      <div className="grid grid-cols-3 gap-6">
        {/* 左侧：板块热力榜 */}
        <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-lg">
          <div className="flex items-center gap-2 mb-6">
            <FlameIcon className="text-orange-500" />
            <h3 className="text-lg font-bold text-slate-900">板块热力榜</h3>
          </div>
          <div className="space-y-3">
            {sectors.map(sector => (
              <div 
                key={sector.code}
                onClick={() => setSelectedSector(sector.code)}
                className={`p-4 rounded-xl cursor-pointer transition-all ${
                  selectedSector === sector.code 
                    ? 'bg-gradient-to-r from-blue-100 to-purple-100 border border-blue-300 shadow-md' 
                    : 'bg-slate-50 hover:bg-slate-100 border border-slate-200'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="font-bold text-sm text-slate-900">{sector.code}</div>
                    <div className="text-xs text-slate-600">{sector.name}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-lg font-bold ${getScoreColor(sector.score)}`}>{sector.score}</div>
                    <div className="text-xs text-slate-600">综合分</div>
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-emerald-600 font-medium">{sector.momentum}</span>
                  <FlameIcon className={`w-4 h-4 ${getHeatColor(sector.heat)}`} />
                </div>
                <div className="mt-2 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-gradient-to-r from-emerald-500 to-blue-500 transition-all duration-500" 
                    style={{ width: `${sector.score}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 右侧：板块详情面板 (占2列) */}
        <div className="col-span-2 bg-white rounded-2xl p-6 border border-slate-200 shadow-lg">
          <div className="flex items-start justify-between mb-6">
            <div>
              <h2 className="text-3xl font-bold text-slate-900 mb-2">{selectedSector}</h2>
              <p className="text-slate-600">{currentSectorDetail.name} · {currentSectorDetail.name.replace('板块', '')} Sector</p>
            </div>
            <div className="flex items-center gap-3">
              <div className={`px-4 py-2 rounded-sm border ${getTrendLevelColor(currentSectorDetail.trendLevel)}`}>
                <div className="text-xs mb-1">趋势等级</div>
                <div className="text-xl font-bold">{currentSectorDetail.trendLevel}</div>
              </div>
            </div>
          </div>

          {/* 四个关键指标卡片 */}
          <div className="grid grid-cols-4 gap-4 mb-6">
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">相对动量</div>
              <div className="text-2xl font-bold text-blue-600">{currentSectorDetail.relMomentum}</div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">行业广度</div>
              <div className="text-2xl font-bold text-emerald-600">{currentSectorDetail.breadth}</div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">资金流入</div>
              <div className={`text-2xl font-bold ${currentSectorDetail.capitalFlow.startsWith('-') ? 'text-red-600' : 'text-purple-600'}`}>
                {currentSectorDetail.capitalFlow}
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="text-xs text-slate-600 mb-2">趋势质量</div>
              <div className="text-2xl font-bold text-amber-600">{currentSectorDetail.trendQuality}</div>
            </div>
          </div>

          {/* 子行业强度排名 */}
          <div>
            <h4 className="text-sm font-bold text-slate-700 mb-3 flex items-center gap-2">
              <BarChartIcon className="text-blue-600" />
              子行业强度排名
            </h4>
            <div className="space-y-2">
              {currentSectorDetail.industries.map((ind, idx) => (
                <div 
                  key={ind.name}
                  className="flex items-center gap-3 p-3 bg-slate-50 rounded-sm hover:bg-slate-100 border border-slate-200 transition-colors"
                >
                  <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-sm flex items-center justify-center font-bold text-sm text-white">
                    {idx + 1}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm text-slate-900">{ind.name}</span>
                      <span className="text-xs text-slate-600">{ind.fullName}</span>
                    </div>
                    <div className="flex items-center gap-4 mt-1 text-xs text-slate-600">
                      <span>相对成交: <span className="text-blue-600 font-medium">{ind.relVol}x</span></span>
                      <span>IVR: <span className="text-purple-600 font-medium">{ind.ivr}</span></span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-emerald-600">{ind.change}</div>
                    <div className="text-xs text-slate-600">20D涨幅</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
