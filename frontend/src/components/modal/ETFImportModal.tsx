import React, { useState } from 'react';
import { Modal } from './Modal';

interface ETFImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  etfSymbol: string;
  onImport: (data: ETFImportData) => void;
}

export interface ETFImportData {
  source: 'finviz' | 'marketchameleon';
  dataType: 'market' | 'options' | 'both';
  jsonData: string;
}

export function ETFImportModal({
  isOpen,
  onClose,
  etfSymbol,
  onImport,
}: ETFImportModalProps) {
  const [source, setSource] = useState<'finviz' | 'marketchameleon'>('finviz');
  const [dataType, setDataType] = useState<'market' | 'options' | 'both'>('both');
  const [jsonData, setJsonData] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleImport = () => {
    try {
      if (jsonData.trim()) {
        JSON.parse(jsonData);
      }
      setError(null);
      onImport({ source, dataType, jsonData });
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

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`导入 ${etfSymbol} ETF数据`}
      subtitle="从外部数据源导入ETF市场和期权数据"
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
      {/* Data Type Selection */}
      <div className="mb-5">
        <label className="block text-sm font-medium mb-2">数据类型</label>
        <div className="grid grid-cols-3 gap-3">
          {[
            { value: 'market', label: '市场数据', icon: '📊' },
            { value: 'options', label: '期权数据', icon: '📈' },
            { value: 'both', label: '全部数据', icon: '🎯' },
          ].map((type) => (
            <button
              key={type.value}
              onClick={() => setDataType(type.value as 'market' | 'options' | 'both')}
              className={`
                p-3 text-center border-2 rounded-[var(--radius-md)] cursor-pointer transition-all
                ${dataType === type.value
                  ? 'border-[var(--accent-blue)] bg-blue-50/50'
                  : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
                }
              `}
            >
              <div className="text-xl mb-1">{type.icon}</div>
              <div className="text-sm font-medium">{type.label}</div>
            </button>
          ))}
        </div>
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
            <div className="text-xs text-[var(--text-muted)]">基础市场数据</div>
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

      {/* Data Preview */}
      <div className="mb-5 p-4 bg-[var(--bg-secondary)] rounded-[var(--radius-md)] border border-[var(--border-light)]">
        <div className="text-sm font-medium mb-3">将导入以下数据</div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          {(dataType === 'market' || dataType === 'both') && (
            <>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                <span>价格与成交量</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                <span>技术指标</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                <span>相对强度</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                <span>趋势数据</span>
              </div>
            </>
          )}
          {(dataType === 'options' || dataType === 'both') && (
            <>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-purple)]" />
                <span>隐含波动率</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-purple)]" />
                <span>IV 百分位</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-purple)]" />
                <span>期权成交</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-purple)]" />
                <span>Put/Call比率</span>
              </div>
            </>
          )}
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
            Finviz
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
          placeholder='粘贴JSON格式数据，例如：{"price": 245.50, "iv30": 28.5, "ivr": 65, ...}'
          className={`
            w-full h-28 px-4 py-3 bg-[var(--bg-primary)] border rounded-[var(--radius-md)] text-sm font-mono resize-none
            ${error ? 'border-[var(--accent-red)]' : 'border-[var(--border-light)]'}
            focus:outline-none focus:border-[var(--accent-blue)]
          `}
        />
        {error && (
          <p className="mt-1.5 text-xs text-[var(--accent-red)]">{error}</p>
        )}
      </div>
    </Modal>
  );
}
