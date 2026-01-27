import React, { useState } from 'react';
import { Modal } from './Modal';

interface HoldingsImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  etfSymbol: string;
  onImport: (data: HoldingsImportData) => void;
}

export interface HoldingsImportData {
  coverage: 10 | 15 | 20 | 25 | 30;
  source: 'finviz' | 'marketchameleon';
  jsonData: string;
}

const COVERAGE_OPTIONS = [
  { value: 10, label: 'Top 10 - 前10大持仓', weight: '72.5%' },
  { value: 15, label: 'Top 15 - 前15大持仓', weight: '82.2%' },
  { value: 20, label: 'Top 20 - 前20大持仓', weight: '88.6%' },
  { value: 25, label: 'Top 25 - 前25大持仓', weight: '92.1%' },
  { value: 30, label: 'Top 30 - 前30大持仓', weight: '94.8%' },
];

const SAMPLE_HOLDINGS = ['NVDA', 'AAPL', 'MSFT', 'AVGO', 'AMD', 'QCOM', 'TXN', 'INTC', 'MU', 'AMAT'];

export function HoldingsImportModal({
  isOpen,
  onClose,
  etfSymbol,
  onImport,
}: HoldingsImportModalProps) {
  const [coverage, setCoverage] = useState<10 | 15 | 20 | 25 | 30>(20);
  const [source, setSource] = useState<'finviz' | 'marketchameleon'>('finviz');
  const [jsonData, setJsonData] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleImport = () => {
    try {
      // Validate JSON if provided
      if (jsonData.trim()) {
        JSON.parse(jsonData);
      }
      setError(null);
      onImport({ coverage, source, jsonData });
      handleClose();
    } catch {
      setError('JSON格式错误，请检查输入');
    }
  };

  const handleClose = () => {
    setJsonData('');
    setError(null);
    onClose();
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const currentWeight = COVERAGE_OPTIONS.find((o) => o.value === coverage)?.weight || '--';

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`导入 ${etfSymbol} 持仓数据`}
      subtitle="从外部数据源导入ETF持仓信息"
      size="small"
      footer={
        <>
          <button
            onClick={handleClose}
            className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleImport}
            className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors"
          >
            导入数据
          </button>
        </>
      }
    >
      {/* Coverage Selection */}
      <div className="mb-5">
        <label className="block text-sm font-medium mb-2">覆盖范围</label>
        <select
          value={coverage}
          onChange={(e) => setCoverage(Number(e.target.value) as 10 | 15 | 20 | 25 | 30)}
          className="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-md)] text-sm cursor-pointer"
        >
          {COVERAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {/* Holdings Preview */}
      <div className="mb-5 p-4 bg-[var(--bg-secondary)] rounded-[var(--radius-md)] border border-[var(--border-light)]">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium">当前持仓标的</span>
          <span className="text-sm text-[var(--text-muted)]">
            累计权重: <span className="text-[var(--accent-green)] font-semibold">{currentWeight}</span>
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {SAMPLE_HOLDINGS.slice(0, Math.min(coverage, SAMPLE_HOLDINGS.length)).map((symbol) => (
            <span
              key={symbol}
              className="px-2.5 py-1 bg-[var(--bg-tertiary)] rounded-[var(--radius-sm)] text-xs font-medium text-[var(--text-secondary)]"
            >
              {symbol}
            </span>
          ))}
          {coverage > SAMPLE_HOLDINGS.length && (
            <span className="px-2.5 py-1 text-xs text-[var(--text-muted)]">
              +{coverage - SAMPLE_HOLDINGS.length} 更多...
            </span>
          )}
        </div>
        <button
          onClick={() => copyToClipboard(SAMPLE_HOLDINGS.slice(0, coverage).join(', '))}
          className="mt-3 text-xs text-[var(--accent-blue)] hover:underline cursor-pointer flex items-center gap-1"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          复制代码列表
        </button>
      </div>

      {/* Source Selection */}
      <div className="mb-5">
        <label className="block text-sm font-medium mb-2">数据来源</label>
        <div className="flex gap-3">
          <button
            onClick={() => setSource('finviz')}
            className={`
              flex-1 p-3 text-left border-2 rounded-[var(--radius-md)] cursor-pointer transition-all
              ${source === 'finviz'
                ? 'border-[var(--accent-blue)] bg-blue-50/50'
                : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
              }
            `}
          >
            <div className="text-sm font-semibold mb-0.5">Finviz</div>
            <div className="text-xs text-[var(--text-muted)]">免费数据源</div>
          </button>
          <button
            onClick={() => setSource('marketchameleon')}
            className={`
              flex-1 p-3 text-left border-2 rounded-[var(--radius-md)] cursor-pointer transition-all
              ${source === 'marketchameleon'
                ? 'border-[var(--accent-blue)] bg-blue-50/50'
                : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
              }
            `}
          >
            <div className="text-sm font-semibold mb-0.5">MarketChameleon</div>
            <div className="text-xs text-[var(--text-muted)]">期权数据</div>
          </button>
        </div>
      </div>

      {/* Quick Links */}
      <div className="mb-5 p-3 bg-[var(--bg-secondary)] rounded-[var(--radius-md)] border border-[var(--border-light)]">
        <div className="text-xs text-[var(--text-muted)] mb-2">快速访问</div>
        <div className="flex gap-2">
          <a
            href={`https://finviz.com/quote.ashx?t=${etfSymbol}`}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 text-xs bg-[var(--bg-tertiary)] rounded-[var(--radius-sm)] text-[var(--accent-blue)] hover:bg-blue-50 transition-colors flex items-center gap-1"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            Finviz {etfSymbol}
          </a>
          <a
            href={`https://marketchameleon.com/Overview/${etfSymbol}`}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 text-xs bg-[var(--bg-tertiary)] rounded-[var(--radius-sm)] text-[var(--accent-blue)] hover:bg-blue-50 transition-colors flex items-center gap-1"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            MarketChameleon
          </a>
        </div>
      </div>

      {/* JSON Input */}
      <div className="mb-3">
        <label className="block text-sm font-medium mb-2">JSON 数据 (可选)</label>
        <textarea
          value={jsonData}
          onChange={(e) => {
            setJsonData(e.target.value);
            setError(null);
          }}
          placeholder='粘贴JSON格式数据，例如：{"holdings": [{"symbol": "NVDA", "weight": 8.5}, ...]}'
          className={`
            w-full h-32 px-4 py-3 bg-[var(--bg-primary)] border rounded-[var(--radius-md)] text-sm font-mono resize-none
            ${error ? 'border-[var(--accent-red)]' : 'border-[var(--border-light)]'}
            focus:outline-none focus:border-[var(--accent-blue)]
          `}
        />
        {error && (
          <p className="mt-1.5 text-xs text-[var(--accent-red)]">{error}</p>
        )}
      </div>

      {/* Format Hint */}
      <div className="p-3 bg-amber-50 rounded-[var(--radius-md)] border border-amber-200">
        <div className="flex items-start gap-2">
          <span className="text-amber-500 text-sm">💡</span>
          <div className="text-xs text-amber-700">
            <p className="font-medium mb-1">数据格式说明</p>
            <p className="leading-relaxed">
              支持标准JSON格式，包含holdings数组，每个持仓需包含symbol和weight字段。
              如不提供JSON数据，将使用默认配置。
            </p>
          </div>
        </div>
      </div>
    </Modal>
  );
}
