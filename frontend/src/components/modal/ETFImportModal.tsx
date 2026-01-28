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
  jsonData: string;
}

export function ETFImportModal({
  isOpen,
  onClose,
  etfSymbol,
  onImport,
}: ETFImportModalProps) {
  const [source, setSource] = useState<'finviz' | 'marketchameleon'>('finviz');
  const [jsonData, setJsonData] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleImport = () => {
    try {
      if (jsonData.trim()) {
        JSON.parse(jsonData);
      } else {
        setError('请输入 JSON 数据');
        return;
      }
      setError(null);
      onImport({ source, jsonData });
      handleClose();
    } catch {
      setError('JSON 格式错误，请检查输入');
    }
  };

  const handleClose = () => {
    setJsonData('');
    setError(null);
    setSource('finviz');
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={
        <div className="flex items-center gap-2">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" strokeWidth="2">
            <path d="M12 5v14M5 12l7-7 7 7" />
          </svg>
          <span>导入 {etfSymbol} 数据</span>
        </div>
      }
      subtitle="导入 ETF 自身的市场数据"
      size="small"
      footer={
        <button
          onClick={handleImport}
          className="w-full py-3 text-sm font-medium rounded-[var(--radius-md)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors flex items-center justify-center gap-2"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 19V5M5 12l7 7 7-7" />
          </svg>
          导入数据
        </button>
      }
    >
      {/* Data Source Selection */}
      <div className="mb-6">
        <label className="block text-sm font-medium mb-3">数据源</label>
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => setSource('finviz')}
            className={`
              p-4 text-left rounded-[var(--radius-md)] cursor-pointer transition-all
              ${source === 'finviz'
                ? 'bg-[var(--accent-blue)] text-white'
                : 'bg-[var(--bg-secondary)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
              }
            `}
          >
            <div className="text-base font-semibold">Finviz</div>
          </button>
          <button
            onClick={() => setSource('marketchameleon')}
            className={`
              p-4 text-left rounded-[var(--radius-md)] cursor-pointer transition-all
              ${source === 'marketchameleon'
                ? 'bg-[var(--accent-blue)] text-white'
                : 'bg-[var(--bg-secondary)] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
              }
            `}
          >
            <div className="text-base font-semibold">MarketChameleon</div>
          </button>
        </div>
      </div>

      {/* JSON Input */}
      <div className="mb-4">
        <label className="block text-sm font-medium mb-3">JSON 数据</label>
        <textarea
          value={jsonData}
          onChange={(e) => {
            setJsonData(e.target.value);
            setError(null);
          }}
          placeholder="粘贴 JSON 数据"
          className={`
            w-full h-48 px-4 py-3 bg-[var(--bg-secondary)] border rounded-[var(--radius-md)] text-sm font-mono resize-none
            ${error ? 'border-[var(--accent-red)]' : 'border-[var(--border-light)]'}
            focus:outline-none focus:border-[var(--accent-blue)]
          `}
        />
        {error && (
          <p className="mt-2 text-xs text-[var(--accent-red)]">{error}</p>
        )}
      </div>
    </Modal>
  );
}