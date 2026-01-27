import React, { useState, useEffect, useMemo } from 'react';
import * as api from '../../services/api';

interface HoldingsImportDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  etfSymbol: string;
  onImport: (data: HoldingsImportData) => void;
}

export interface HoldingsImportData {
  source: 'finviz' | 'marketchameleon';
  coverage: string;
  jsonData: string;
}

interface HoldingInfo {
  ticker: string;
  weight: number;
}

type CoverageType = 'top10' | 'top15' | 'top20' | 'top30' | 'weight60' | 'weight65' | 'weight70' | 'weight75' | 'weight80' | 'weight85';

const COVERAGE_OPTIONS: { value: CoverageType; label: string }[] = [
  { value: 'top10', label: 'Top 10 - 前10大持仓' },
  { value: 'top15', label: 'Top 15 - 前15大持仓' },
  { value: 'top20', label: 'Top 20 - 前20大持仓' },
  { value: 'top30', label: 'Top 30 - 前30大持仓' },
  { value: 'weight60', label: 'Weight 60% - 累计权重60%' },
  { value: 'weight65', label: 'Weight 65% - 累计权重65%' },
  { value: 'weight70', label: 'Weight 70% - 累计权重70%' },
  { value: 'weight75', label: 'Weight 75% - 累计权重75%' },
  { value: 'weight80', label: 'Weight 80% - 累计权重80%' },
  { value: 'weight85', label: 'Weight 85% - 累计权重85%' },
];

// 示例数据
const SAMPLE_FINVIZ_DATA = `[
  {"Ticker": "NVDA", "Beta": 1.65, "ATR": 5.23, "SMA50": 142.5, "SMA200": 118.3, "52W_High": 152.89, "RSI": 62.5, "Price": 148.5},
  {"Ticker": "AAPL", "Beta": 1.28, "ATR": 3.12, "SMA50": 178.2, "SMA200": 172.1, "52W_High": 199.62, "RSI": 55.3, "Price": 182.3}
]`;

const SAMPLE_MC_DATA = `[
  {"Ticker": "NVDA", "IV30": 45.2, "IVR": 35, "PutCallRatio": 0.85, "OptionVolume": 125000},
  {"Ticker": "AAPL", "IV30": 22.5, "IVR": 28, "PutCallRatio": 0.72, "OptionVolume": 85000}
]`;

export function HoldingsImportDrawer({
  isOpen,
  onClose,
  etfSymbol,
  onImport,
}: HoldingsImportDrawerProps) {
  const [source, setSource] = useState<'finviz' | 'marketchameleon'>('finviz');
  const [coverage, setCoverage] = useState<CoverageType>('top10');
  const [jsonData, setJsonData] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [holdings, setHoldings] = useState<HoldingInfo[]>([]);
  const [showAllHoldings, setShowAllHoldings] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  // 加载 ETF 持仓数据
  useEffect(() => {
    if (isOpen && etfSymbol) {
      loadHoldings();
    }
  }, [isOpen, etfSymbol]);

  // 切换覆盖范围时收起展开状态
  useEffect(() => {
    setShowAllHoldings(false);
  }, [coverage]);

  const loadHoldings = async () => {
    try {
      const data = await api.getETFHoldingsBySymbol(etfSymbol);
      setHoldings(data.map(h => ({ ticker: h.ticker, weight: h.weight })));
    } catch (e) {
      console.error('Failed to load holdings:', e);
      setHoldings([]);
    }
  };

  // 根据 coverage 过滤持仓
  const filteredHoldings = useMemo(() => {
    if (holdings.length === 0) return [];

    // Top N 模式
    if (coverage.startsWith('top')) {
      const count = parseInt(coverage.replace('top', ''), 10);
      return holdings.slice(0, count);
    }

    // Weight 模式 - 累计权重达到指定百分比
    if (coverage.startsWith('weight')) {
      const targetWeight = parseInt(coverage.replace('weight', ''), 10);
      let accWeight = 0;
      const result: HoldingInfo[] = [];
      
      for (const h of holdings) {
        if (accWeight >= targetWeight) break;
        result.push(h);
        accWeight += h.weight;
      }
      
      return result;
    }

    return holdings;
  }, [holdings, coverage]);

  const totalWeight = useMemo(() => {
    return filteredHoldings.reduce((sum, h) => sum + h.weight, 0);
  }, [filteredHoldings]);

  // 默认显示的持仓数量
  const DEFAULT_DISPLAY_COUNT = 6;
  const displayHoldings = showAllHoldings ? filteredHoldings : filteredHoldings.slice(0, DEFAULT_DISPLAY_COUNT);
  const hasMoreHoldings = filteredHoldings.length > DEFAULT_DISPLAY_COUNT;

  const handleCopyTickers = async () => {
    const tickers = filteredHoldings.map(h => h.ticker).join(', ');
    try {
      await navigator.clipboard.writeText(tickers);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (e) {
      console.error('Failed to copy:', e);
    }
  };

  const handleLoadSampleData = () => {
    setJsonData(source === 'finviz' ? SAMPLE_FINVIZ_DATA : SAMPLE_MC_DATA);
    setError(null);
  };

  const handleClear = () => {
    setJsonData('');
    setError(null);
  };

  const handleImport = () => {
    try {
      if (jsonData.trim()) {
        JSON.parse(jsonData);
      } else {
        setError('请输入 JSON 数据');
        return;
      }
      setError(null);
      onImport({ source, coverage, jsonData });
      handleClose();
    } catch {
      setError('JSON 格式错误，请检查输入');
    }
  };

  const handleClose = () => {
    setJsonData('');
    setError(null);
    setSource('finviz');
    setCoverage('top10');
    setShowAllHoldings(false);
    onClose();
  };

  const getFormatHint = () => {
    if (source === 'finviz') {
      return 'Finviz JSON 需包含 Ticker, Beta, ATR, SMA50, SMA200, 52W_High, RSI, Price 字段';
    }
    return 'MarketChameleon JSON 需包含 Ticker, IV30, IVR, PutCallRatio, OptionVolume 字段';
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`
          fixed inset-0 bg-black/40 z-40 transition-opacity duration-300
          ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}
        `}
        onClick={handleClose}
      />

      {/* Drawer */}
      <div
        className={`
          fixed top-0 right-0 h-full w-[520px] bg-[var(--bg-primary)] shadow-2xl z-50
          transform transition-transform duration-300 ease-out
          ${isOpen ? 'translate-x-0' : 'translate-x-full'}
          flex flex-col
        `}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[var(--border-light)]">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold">导入 Holdings 数据</h2>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                导入 {etfSymbol} 的持仓数据
              </p>
            </div>
            <button
              onClick={handleClose}
              className="p-2 rounded-[var(--radius-sm)] text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content - Scrollable */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Coverage Section */}
          <div className="p-4 bg-[var(--bg-secondary)] rounded-[var(--radius-lg)] border border-[var(--border-light)] mb-6">
            <div className="text-sm font-medium mb-3">覆盖范围</div>
            <select
              value={coverage}
              onChange={(e) => setCoverage(e.target.value as CoverageType)}
              className="w-full px-4 py-3 bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-md)] text-sm focus:outline-none focus:border-[var(--accent-blue)]"
            >
              {COVERAGE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            
            <p className="text-sm text-[var(--text-muted)] mt-3">
              选择要导入数据的覆盖范围，不同范围可分别导入和监控
            </p>

            {/* Holdings Info Box */}
            {holdings.length > 0 && (
              <div className="mt-4 p-3 bg-[var(--bg-primary)] rounded-[var(--radius-md)] border border-[var(--border-light)]">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-sm">
                      需收集 <span className="font-semibold text-[var(--accent-blue)]">{filteredHoldings.length}</span> 只持仓标的数据
                    </span>
                    <span className="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-700">
                      累计权重 {totalWeight.toFixed(1)}%
                    </span>
                  </div>
                  <button
                    onClick={handleCopyTickers}
                    className={`
                      flex items-center gap-1.5 px-2 py-1 text-xs rounded transition-colors flex-shrink-0
                      ${copySuccess 
                        ? 'text-green-600 bg-green-50' 
                        : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
                      }
                    `}
                  >
                    {copySuccess ? (
                      <>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                        已复制
                      </>
                    ) : (
                      <>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                        </svg>
                        复制代码
                      </>
                    )}
                  </button>
                </div>

                {/* Holdings Pills - 可滚动容器 */}
                <div 
                  className={`
                    flex flex-wrap gap-2 
                    ${showAllHoldings && hasMoreHoldings ? 'max-h-40 overflow-y-auto pr-1' : ''}
                  `}
                >
                  {displayHoldings.map((h) => (
                    <span
                      key={h.ticker}
                      className="px-3 py-1.5 text-sm bg-[var(--bg-secondary)] border border-[var(--border-light)] rounded-[var(--radius-md)]"
                    >
                      {h.ticker}
                    </span>
                  ))}
                </div>

                {/* 查看全部/收起 链接 */}
                {hasMoreHoldings && (
                  <div className="flex items-center gap-3 mt-3 text-sm">
                    <span className="text-[var(--text-muted)]">
                      等 {filteredHoldings.length} 只
                    </span>
                    <button
                      onClick={() => setShowAllHoldings(!showAllHoldings)}
                      className="text-[var(--accent-blue)] hover:underline flex items-center gap-1"
                    >
                      {showAllHoldings ? '收起' : '查看全部'}
                      <svg 
                        width="12" 
                        height="12" 
                        viewBox="0 0 24 24" 
                        fill="none" 
                        stroke="currentColor" 
                        strokeWidth="2"
                        className={`transition-transform ${showAllHoldings ? 'rotate-180' : ''}`}
                      >
                        <path d="M7 17L17 7M17 7H7M17 7v10" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Data Source Section */}
          <div className="mb-6">
            <div className="text-sm font-bold mb-3">数据来源</div>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setSource('finviz')}
                className={`
                  p-4 text-left rounded-[var(--radius-lg)] cursor-pointer transition-all border-2
                  ${source === 'finviz'
                    ? 'border-[var(--accent-blue)] bg-blue-50/50'
                    : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
                  }
                `}
              >
                <div className={`text-base font-semibold ${source === 'finviz' ? 'text-[var(--accent-blue)]' : ''}`}>
                  Finviz
                </div>
                <div className="text-xs text-[var(--text-muted)] mt-1">技术指标数据</div>
              </button>
              <button
                onClick={() => setSource('marketchameleon')}
                className={`
                  p-4 text-left rounded-[var(--radius-lg)] cursor-pointer transition-all border-2
                  ${source === 'marketchameleon'
                    ? 'border-[var(--accent-blue)] bg-blue-50/50'
                    : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
                  }
                `}
              >
                <div className={`text-base font-semibold ${source === 'marketchameleon' ? 'text-[var(--accent-blue)]' : ''}`}>
                  MarketChameleon
                </div>
                <div className="text-xs text-[var(--text-muted)] mt-1">期权数据</div>
              </button>
            </div>
          </div>

          {/* JSON Input Section */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-bold">粘贴 JSON 数据</div>
              <button
                onClick={handleLoadSampleData}
                className="text-sm text-[var(--accent-blue)] hover:underline"
              >
                加载示例数据
              </button>
            </div>
            <textarea
              value={jsonData}
              onChange={(e) => {
                setJsonData(e.target.value);
                setError(null);
              }}
              placeholder={`粘贴包含 ${filteredHoldings.slice(0, 3).map(h => h.ticker).join(', ')} 等标的的 JSON 数据...`}
              className={`
                w-full h-48 px-4 py-3 bg-[var(--bg-secondary)] border rounded-[var(--radius-md)] text-sm font-mono resize-y
                ${error ? 'border-[var(--accent-red)]' : 'border-[var(--border-light)]'}
                focus:outline-none focus:border-[var(--accent-blue)]
              `}
            />
            {error && (
              <p className="mt-2 text-xs text-[var(--accent-red)]">{error}</p>
            )}
          </div>

          {/* Format Hint */}
          <div className="p-3 bg-amber-50 rounded-[var(--radius-md)] border border-amber-200">
            <div className="flex items-start gap-2">
              <span className="text-amber-500 text-sm font-medium">格式说明:</span>
              <span className="text-xs text-amber-700">
                {getFormatHint()}
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[var(--border-light)] flex items-center justify-between">
          <button
            onClick={handleClear}
            className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-md)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            清除
          </button>
          <button
            onClick={handleImport}
            className="px-6 py-2.5 text-sm font-medium rounded-[var(--radius-md)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors flex items-center gap-2"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12l7-7 7 7" />
            </svg>
            解析并导入
          </button>
        </div>
      </div>
    </>
  );
}

// 兼容旧的 HoldingsImportModal 导出名称
export const HoldingsImportModal = HoldingsImportDrawer;