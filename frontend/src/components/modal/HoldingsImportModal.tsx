import React, { useState, useRef } from 'react';
import { Modal } from './Modal';
import { useUploadHoldings } from '../../hooks/useData';

interface HoldingsImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  etfSymbol: string;
  etfType: 'sector' | 'industry';
  onSuccess?: () => void;
}

// 11 个有效的板块 ETF
const VALID_SECTOR_ETFS = ['XLK', 'XLC', 'XLY', 'XLP', 'XLV', 'XLF', 'XLI', 'XLE', 'XLU', 'XLRE', 'XLB'];

export function HoldingsImportModal({
  isOpen,
  onClose,
  etfSymbol,
  etfType,
  onSuccess,
}: HoldingsImportModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dataDate, setDataDate] = useState(() => {
    const today = new Date();
    return today.toISOString().split('T')[0];
  });
  const [error, setError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<{
    valid_rows: number;
    skipped_rows: number;
    holdings: { ticker: string; weight: number }[];
    skipped_details: { row: number; ticker: string; reason: string }[];
  } | null>(null);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadMutation = useUploadHoldings();

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
        setError('请选择 .xlsx 或 .xls 格式的文件');
        setSelectedFile(null);
        return;
      }
      setSelectedFile(file);
      setError(null);
      setImportResult(null);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) {
      if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
        setError('请选择 .xlsx 或 .xls 格式的文件');
        return;
      }
      setSelectedFile(file);
      setError(null);
      setImportResult(null);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleImport = async () => {
    if (!selectedFile) {
      setError('请先选择文件');
      return;
    }

    try {
      const result = await uploadMutation.mutateAsync({
        file: selectedFile,
        dataDate,
        etfType,
        etfSymbol,
      });
      
      setImportResult({
        valid_rows: result.valid_rows,
        skipped_rows: result.skipped_rows,
        holdings: result.holdings,
        skipped_details: result.skipped_details,
      });
      
      setError(null);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入失败');
    }
  };

  const handleClose = () => {
    setSelectedFile(null);
    setError(null);
    setImportResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    onClose();
  };

  const isValidSectorETF = etfType === 'sector' && VALID_SECTOR_ETFS.includes(etfSymbol);
  const canImport = selectedFile && (etfType === 'industry' || isValidSectorETF);

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`导入 ${etfSymbol} 持仓数据`}
      subtitle={`上传 XLSX 文件导入${etfType === 'sector' ? '板块' : '行业'} ETF 持仓`}
      size="small"
      footer={
        importResult ? (
          <button
            onClick={handleClose}
            className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors"
          >
            完成
          </button>
        ) : (
          <>
            <button
              onClick={handleClose}
              className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleImport}
              disabled={!canImport || uploadMutation.isPending}
              className={`
                px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] transition-colors
                ${canImport && !uploadMutation.isPending
                  ? 'bg-[var(--accent-blue)] text-white hover:bg-blue-600'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
                }
              `}
            >
              {uploadMutation.isPending ? '导入中...' : '导入数据'}
            </button>
          </>
        )
      }
    >
      {/* Import Result */}
      {importResult && (
        <div className="mb-5">
          <div className="p-4 bg-green-50 rounded-[var(--radius-md)] border border-green-200 mb-4">
            <div className="flex items-center gap-2 mb-2">
              <svg className="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
              </svg>
              <span className="font-medium text-green-700">导入成功</span>
            </div>
            <div className="text-sm text-green-600">
              <p>有效记录: <strong>{importResult.valid_rows}</strong> 条</p>
              <p>跳过记录: <strong>{importResult.skipped_rows}</strong> 条</p>
            </div>
          </div>
          
          {/* Holdings Preview */}
          {importResult.holdings.length > 0 && (
            <div className="mb-4">
              <h4 className="text-sm font-medium mb-2">持仓预览 (Top 10)</h4>
              <div className="max-h-40 overflow-y-auto border border-[var(--border-light)] rounded-[var(--radius-md)]">
                <table className="w-full text-sm">
                  <thead className="bg-[var(--bg-secondary)] sticky top-0">
                    <tr>
                      <th className="text-left px-3 py-2">Ticker</th>
                      <th className="text-right px-3 py-2">Weight</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.holdings.slice(0, 10).map((h, i) => (
                      <tr key={i} className="border-t border-[var(--border-light)]">
                        <td className="px-3 py-2 font-mono">{h.ticker}</td>
                        <td className="px-3 py-2 text-right">{h.weight.toFixed(2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          
          {/* Skipped Details */}
          {importResult.skipped_details.length > 0 && (
            <div>
              <h4 className="text-sm font-medium mb-2 text-amber-600">跳过的记录</h4>
              <div className="max-h-32 overflow-y-auto text-xs bg-amber-50 p-2 rounded-[var(--radius-sm)]">
                {importResult.skipped_details.map((s, i) => (
                  <div key={i} className="text-amber-700">
                    行 {s.row}: {s.ticker} - {s.reason}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!importResult && (
        <>
          {/* ETF Info */}
          <div className="mb-5 p-3 bg-[var(--bg-secondary)] rounded-[var(--radius-md)] border border-[var(--border-light)]">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-sm font-medium">{etfSymbol}</span>
                <span className="ml-2 px-2 py-0.5 text-xs bg-[var(--bg-tertiary)] rounded">
                  {etfType === 'sector' ? '板块 ETF' : '行业 ETF'}
                </span>
              </div>
              {etfType === 'sector' && !isValidSectorETF && (
                <span className="text-xs text-red-500">
                  无效的板块 ETF
                </span>
              )}
            </div>
            {etfType === 'sector' && (
              <div className="mt-2 text-xs text-[var(--text-muted)]">
                有效板块: {VALID_SECTOR_ETFS.join(', ')}
              </div>
            )}
          </div>

          {/* Date Selection */}
          <div className="mb-5">
            <label className="block text-sm font-medium mb-2">数据日期</label>
            <input
              type="date"
              value={dataDate}
              onChange={(e) => setDataDate(e.target.value)}
              className="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-[var(--radius-md)] text-sm"
            />
          </div>

          {/* File Upload Area */}
          <div className="mb-5">
            <label className="block text-sm font-medium mb-2">XLSX 文件</label>
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onClick={() => fileInputRef.current?.click()}
              className={`
                border-2 border-dashed rounded-[var(--radius-md)] p-6 text-center cursor-pointer
                transition-colors
                ${selectedFile
                  ? 'border-[var(--accent-blue)] bg-blue-50/30'
                  : 'border-[var(--border-light)] hover:border-[var(--accent-blue)] hover:bg-[var(--bg-secondary)]'
                }
              `}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleFileSelect}
                className="hidden"
              />
              {selectedFile ? (
                <div className="flex items-center justify-center gap-2">
                  <svg className="w-5 h-5 text-[var(--accent-blue)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="text-sm font-medium">{selectedFile.name}</span>
                </div>
              ) : (
                <div>
                  <svg className="w-10 h-10 mx-auto text-[var(--text-muted)] mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  <p className="text-sm text-[var(--text-muted)]">
                    拖放文件到这里，或点击选择文件
                  </p>
                  <p className="text-xs text-[var(--text-muted)] mt-1">
                    支持 .xlsx, .xls 格式
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="mb-5 p-3 bg-red-50 rounded-[var(--radius-md)] border border-red-200">
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          {/* Format Hint */}
          <div className="p-3 bg-amber-50 rounded-[var(--radius-md)] border border-amber-200">
            <div className="flex items-start gap-2">
              <span className="text-amber-500 text-sm">💡</span>
              <div className="text-xs text-amber-700">
                <p className="font-medium mb-1">XLSX 文件格式要求</p>
                <p className="leading-relaxed mb-2">
                  文件需包含 "Ticker" 和 "Weight" 列。
                </p>
                <p className="leading-relaxed">
                  <strong>验证规则:</strong> Ticker 为空或包含非英文字符的行将被忽略。
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
