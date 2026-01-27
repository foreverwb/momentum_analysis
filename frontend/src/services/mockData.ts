import type { Stock, ETF, Task, Holding } from '../types';

// 生成持仓数据的辅助函数
function generateHoldings(count: number): Holding[] {
  const tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AVGO', 'AMD', 'ORCL',
    'CSCO', 'INTC', 'CRM', 'ADBE', 'QCOM', 'TXN', 'NOW', 'INTU', 'IBM', 'AMAT',
    'MU', 'ADI', 'LRCX', 'KLAC', 'SNPS', 'CDNS', 'MRVL', 'NXPI', 'MCHP', 'FTNT'];
  const holdings: Holding[] = [];
  let remainingWeight = 100;

  for (let i = 0; i < count; i++) {
    const weight = i === count - 1 ? remainingWeight : (Math.random() * 15 + 1);
    holdings.push({
      ticker: tickers[i % tickers.length] + (i >= tickers.length ? String(i) : ''),
      weight: parseFloat(weight.toFixed(2))
    });
    remainingWeight -= weight;
  }

  return holdings.sort((a, b) => b.weight - a.weight);
}

export const mockStocks: Stock[] = [
  {
    id: 1,
    symbol: 'MU',
    name: 'MU',
    sector: 'XLK',
    industry: '半导体',
    price: 405.78,
    scoreTotal: 56.2,
    scores: {
      momentum: 60,
      trend: 55,
      volume: 50,
      quality: 70,
      options: 70
    },
    changes: {
      delta3d: 0,
      delta5d: null
    },
    metrics: {
      return20d: 0,
      return63d: 0,
      sma20Slope: 0,
      ivr: 80,
      iv30: 67.5
    }
  },
  {
    id: 2,
    symbol: 'NVDA',
    name: 'NVIDIA Corporation',
    sector: 'XLK',
    industry: '半导体',
    price: 892.45,
    scoreTotal: 52.8,
    scores: {
      momentum: 58,
      trend: 52,
      volume: 48,
      quality: 65,
      options: 68
    },
    changes: {
      delta3d: 1.5,
      delta5d: 3.2
    },
    metrics: {
      return20d: 5.2,
      return63d: 12.8,
      sma20Slope: 0.5,
      ivr: 65,
      iv30: 55.2
    }
  },
  {
    id: 3,
    symbol: 'AMD',
    name: 'Advanced Micro Devices',
    sector: 'XLK',
    industry: '半导体',
    price: 178.32,
    scoreTotal: 48.5,
    scores: {
      momentum: 52,
      trend: 45,
      volume: 42,
      quality: 58,
      options: 55
    },
    changes: {
      delta3d: -0.8,
      delta5d: 1.2
    },
    metrics: {
      return20d: 3.1,
      return63d: 8.5,
      sma20Slope: 0.3,
      ivr: 55,
      iv30: 48.5
    }
  },
  {
    id: 4,
    symbol: 'INTC',
    name: 'Intel Corporation',
    sector: 'XLK',
    industry: '半导体',
    price: 42.15,
    scoreTotal: 35.2,
    scores: {
      momentum: 35,
      trend: 32,
      volume: 38,
      quality: 40,
      options: 45
    },
    changes: {
      delta3d: -2.1,
      delta5d: -4.5
    },
    metrics: {
      return20d: -2.5,
      return63d: -8.2,
      sma20Slope: -0.2,
      ivr: 72,
      iv30: 62.3
    }
  }
];

export const mockETFs: ETF[] = [
  // 板块 ETF - 参考 data_config_etf_panel.html 的 sectorETFs 结构
  {
    id: 1,
    symbol: 'XLK',
    name: '科技板块',
    type: 'sector',
    score: 92,
    rank: 1,
    delta: { delta3d: 2.3, delta5d: 4.1 },
    completeness: 95,
    holdingsCount: 68,
    compositeScore: 92,
    relMomentum: { score: 88, value: '+12.3%', rank: 1 },
    trendQuality: { score: 95, structure: 'Strong', slope: '+0.08' },
    breadth: { score: 85, above50ma: '75%', above200ma: '68%' },
    optionsConfirm: { score: 89, heat: 'High', relVol: '1.8x', ivr: 72 },
    holdings: generateHoldings(68)
  },
  {
    id: 2,
    symbol: 'XLE',
    name: '能源板块',
    type: 'sector',
    score: 85,
    rank: 2,
    delta: { delta3d: 1.8, delta5d: 3.5 },
    completeness: 92,
    holdingsCount: 45,
    compositeScore: 85,
    relMomentum: { score: 82, value: '+9.1%', rank: 3 },
    trendQuality: { score: 88, structure: 'Strong', slope: '+0.06' },
    breadth: { score: 78, above50ma: '68%', above200ma: '62%' },
    optionsConfirm: { score: 81, heat: 'High', relVol: '1.6x', ivr: 68 },
    holdings: generateHoldings(45)
  },
  {
    id: 3,
    symbol: 'XLF',
    name: '金融板块',
    type: 'sector',
    score: 78,
    rank: 3,
    delta: { delta3d: 1.5, delta5d: 2.8 },
    completeness: 88,
    holdingsCount: 68,
    compositeScore: 78,
    relMomentum: { score: 75, value: '+6.8%', rank: 4 },
    trendQuality: { score: 82, structure: 'Stable', slope: '+0.04' },
    breadth: { score: 72, above50ma: '62%', above200ma: '55%' },
    optionsConfirm: { score: 76, heat: 'Medium', relVol: '1.3x', ivr: 58 },
    holdings: generateHoldings(68)
  },
  {
    id: 4,
    symbol: 'XLY',
    name: '消费板块',
    type: 'sector',
    score: 88,
    rank: 4,
    delta: { delta3d: 2.1, delta5d: 3.8 },
    completeness: 90,
    holdingsCount: 52,
    compositeScore: 88,
    relMomentum: { score: 85, value: '+10.5%', rank: 2 },
    trendQuality: { score: 90, structure: 'Strong', slope: '+0.07' },
    breadth: { score: 80, above50ma: '70%', above200ma: '64%' },
    optionsConfirm: { score: 84, heat: 'High', relVol: '1.5x', ivr: 65 },
    holdings: generateHoldings(52)
  },
  {
    id: 5,
    symbol: 'XLV',
    name: '医疗板块',
    type: 'sector',
    score: 65,
    rank: 5,
    delta: { delta3d: 0.8, delta5d: 1.2 },
    completeness: 92,
    holdingsCount: 64,
    compositeScore: 65,
    relMomentum: { score: 60, value: '+3.2%', rank: 6 },
    trendQuality: { score: 68, structure: 'Weak', slope: '+0.02' },
    breadth: { score: 55, above50ma: '48%', above200ma: '42%' },
    optionsConfirm: { score: 62, heat: 'Low', relVol: '0.9x', ivr: 45 },
    holdings: generateHoldings(64)
  },
  {
    id: 6,
    symbol: 'XLI',
    name: '工业板块',
    type: 'sector',
    score: 72,
    rank: 6,
    delta: { delta3d: 1.2, delta5d: 2.1 },
    completeness: 88,
    holdingsCount: 78,
    compositeScore: 72,
    relMomentum: { score: 70, value: '+5.6%', rank: 5 },
    trendQuality: { score: 75, structure: 'Stable', slope: '+0.03' },
    breadth: { score: 68, above50ma: '58%', above200ma: '52%' },
    optionsConfirm: { score: 70, heat: 'Medium', relVol: '1.2x', ivr: 52 },
    holdings: generateHoldings(78)
  },
  // 行业 ETF - 参考 data_config_etf_panel.html 的 industryETFs 结构
  {
    id: 7,
    symbol: 'SOXX',
    name: '半导体',
    type: 'industry',
    score: 95,
    rank: 1,
    delta: { delta3d: 3.2, delta5d: 5.8 },
    completeness: 100,
    holdingsCount: 32,
    compositeScore: 95,
    sector: 'XLK',
    sectorName: '科技',
    relMomentum: { score: 92, value: '+15.2%', rank: 1 },
    trendQuality: { score: 96, structure: 'Strong', slope: '+0.10' },
    breadth: { score: 88, above50ma: '82%', above200ma: '75%' },
    optionsConfirm: { score: 93, heat: 'Very High', relVol: '2.1x', ivr: 78 },
    holdings: generateHoldings(32)
  },
  {
    id: 8,
    symbol: 'SMH',
    name: '半导体设备',
    type: 'industry',
    score: 91,
    rank: 2,
    delta: { delta3d: 2.8, delta5d: 4.9 },
    completeness: 98,
    holdingsCount: 25,
    compositeScore: 91,
    sector: 'XLK',
    sectorName: '科技',
    relMomentum: { score: 88, value: '+13.5%', rank: 2 },
    trendQuality: { score: 92, structure: 'Strong', slope: '+0.08' },
    breadth: { score: 84, above50ma: '78%', above200ma: '70%' },
    optionsConfirm: { score: 89, heat: 'High', relVol: '1.9x', ivr: 72 },
    holdings: generateHoldings(25)
  },
  {
    id: 9,
    symbol: 'IGV',
    name: '软件',
    type: 'industry',
    score: 88,
    rank: 3,
    delta: { delta3d: 2.1, delta5d: 3.6 },
    completeness: 95,
    holdingsCount: 42,
    compositeScore: 88,
    sector: 'XLK',
    sectorName: '科技',
    relMomentum: { score: 85, value: '+11.8%', rank: 3 },
    trendQuality: { score: 88, structure: 'Strong', slope: '+0.07' },
    breadth: { score: 80, above50ma: '72%', above200ma: '65%' },
    optionsConfirm: { score: 86, heat: 'High', relVol: '1.6x', ivr: 68 },
    holdings: generateHoldings(42)
  },
  {
    id: 10,
    symbol: 'XBI',
    name: '生物科技',
    type: 'industry',
    score: 72,
    rank: 4,
    delta: { delta3d: 1.5, delta5d: 2.2 },
    completeness: 90,
    holdingsCount: 135,
    compositeScore: 72,
    sector: 'XLV',
    sectorName: '医疗',
    relMomentum: { score: 68, value: '+5.8%', rank: 5 },
    trendQuality: { score: 75, structure: 'Stable', slope: '+0.04' },
    breadth: { score: 65, above50ma: '55%', above200ma: '48%' },
    optionsConfirm: { score: 70, heat: 'Medium', relVol: '1.3x', ivr: 55 },
    holdings: generateHoldings(135)
  },
  {
    id: 11,
    symbol: 'XOP',
    name: '油气勘探',
    type: 'industry',
    score: 82,
    rank: 5,
    delta: { delta3d: 1.8, delta5d: 3.2 },
    completeness: 92,
    holdingsCount: 48,
    compositeScore: 82,
    sector: 'XLE',
    sectorName: '能源',
    relMomentum: { score: 80, value: '+8.5%', rank: 4 },
    trendQuality: { score: 85, structure: 'Strong', slope: '+0.06' },
    breadth: { score: 75, above50ma: '65%', above200ma: '58%' },
    optionsConfirm: { score: 78, heat: 'High', relVol: '1.5x', ivr: 62 },
    holdings: generateHoldings(48)
  }
];

export const mockTasks: Task[] = [
  {
    id: 1,
    title: '科技板块轮动监控',
    type: 'rotation',
    baseIndex: 'SPY',
    etfs: ['XLK', 'XLF', 'XLV'],
    createdAt: '2026-01-25'
  },
  {
    id: 2,
    title: '科技内部行业下钻',
    type: 'drilldown',
    baseIndex: 'SPY',
    sector: 'XLK',
    etfs: ['SOXX', 'SMH', 'IGV', 'SKYY'],
    createdAt: '2026-01-24'
  },
  {
    id: 3,
    title: '半导体动能股追踪',
    type: 'momentum',
    baseIndex: 'SPY',
    sector: 'XLK',
    etfs: ['SOXX', 'SMH'],
    createdAt: '2026-01-23'
  }
];
