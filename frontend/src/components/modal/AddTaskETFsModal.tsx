import React, { useEffect, useMemo, useState } from 'react';
import { Modal } from './Modal';
import type { ETF, TaskType, NodeCatalogItem } from '../../types';
import * as api from '../../services/api';

interface AddTaskETFsModalProps {
  isOpen: boolean;
  onClose: () => void;
  taskType: TaskType;
  taskSector?: string;
  existingEtfs: string[];
  existingNodes?: string[];
  onSubmit: (symbols: string[], selectedNodes?: string[]) => Promise<void> | void;
}

const TASK_TYPE_LABEL: Record<TaskType, string> = {
  rotation: '板块轮动',
  drilldown: '板块下钻',
  momentum: '动能追踪',
};

const normalizeSymbol = (value?: string | null): string =>
  (value || '').trim().toUpperCase();

const sortCandidates = (candidates: ETF[]): ETF[] =>
  [...candidates].sort((left, right) => {
    const leftRank = left.rank > 0 ? left.rank : Number.MAX_SAFE_INTEGER;
    const rightRank = right.rank > 0 ? right.rank : Number.MAX_SAFE_INTEGER;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    const leftScore = Number.isFinite(left.score) ? left.score : Number.NEGATIVE_INFINITY;
    const rightScore = Number.isFinite(right.score) ? right.score : Number.NEGATIVE_INFINITY;
    if (leftScore !== rightScore) {
      return rightScore - leftScore;
    }
    return left.symbol.localeCompare(right.symbol);
  });

// ============ ETF tab (unchanged for all task types) ============

interface ETFTabProps {
  taskType: TaskType;
  normalizedSector: string;
  existingSet: Set<string>;
  isSubmitting: boolean;
  onSubmit: (symbols: string[]) => Promise<void>;
  onClose: () => void;
}

function ETFTab({
  taskType,
  normalizedSector,
  existingSet,
  isSubmitting,
  onSubmit,
  onClose,
}: ETFTabProps) {
  const [candidates, setCandidates] = useState<ETF[]>([]);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const [searchValue, setSearchValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const subtitle = useMemo(() => {
    if (taskType === 'rotation') {
      return '板块轮动任务仅支持添加板块 ETF，可一次多选。';
    }
    if (!normalizedSector) {
      return '当前任务缺少板块上下文，暂时无法筛选可添加的行业 ETF。';
    }
    return `当前任务类型为 ${TASK_TYPE_LABEL[taskType]}，仅展示 ${normalizedSector} 下可添加的行业 ETF。`;
  }, [normalizedSector, taskType]);

  useEffect(() => {
    let cancelled = false;
    setSelectedSymbols([]);
    setSearchValue('');
    setError(null);

    if (taskType !== 'rotation' && !normalizedSector) {
      setCandidates([]);
      return;
    }

    const loadCandidates = async () => {
      setIsLoading(true);
      try {
        const etfType = taskType === 'rotation' ? 'sector' : 'industry';
        const response = await api.getETFs(etfType, false);
        if (cancelled) return;

        const nextCandidates = response.filter((etf) => {
          const symbol = normalizeSymbol(etf.symbol);
          if (!symbol || existingSet.has(symbol)) {
            return false;
          }
          if (taskType === 'rotation') {
            return etf.type === 'sector';
          }
          return etf.type === 'industry' && normalizeSymbol(etf.parentSector) === normalizedSector;
        });

        setCandidates(sortCandidates(nextCandidates));
      } catch (loadError) {
        if (cancelled) return;
        setCandidates([]);
        setError(loadError instanceof Error ? loadError.message : '加载可添加 ETF 失败');
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadCandidates();
    return () => { cancelled = true; };
  }, [existingSet, normalizedSector, taskType]);

  const filteredCandidates = useMemo(() => {
    const keyword = searchValue.trim().toUpperCase();
    if (!keyword) return candidates;
    return candidates.filter((etf) => {
      const symbol = normalizeSymbol(etf.symbol);
      const name = (etf.name || '').trim().toUpperCase();
      return symbol.includes(keyword) || name.includes(keyword);
    });
  }, [candidates, searchValue]);

  const selectedCandidateDetails = useMemo(() => {
    const selectedSet = new Set(selectedSymbols);
    return candidates.filter((etf) => selectedSet.has(normalizeSymbol(etf.symbol)));
  }, [candidates, selectedSymbols]);

  const handleToggle = (symbol: string) => {
    if (isSubmitting) return;
    setSelectedSymbols((prev) =>
      prev.includes(symbol) ? prev.filter((s) => s !== symbol) : [...prev, symbol]
    );
    setError(null);
  };

  const handleSubmit = async () => {
    if (selectedSymbols.length === 0) {
      setError('请至少选择一个 ETF');
      return;
    }
    await onSubmit(selectedSymbols);
  };

  return (
    <>
      <p className="text-sm text-[var(--text-muted)] -mt-1 mb-3">{subtitle}</p>

      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-[var(--radius-md)] border border-[var(--border-light)] bg-[var(--bg-secondary)] px-4 py-3">
            <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">任务类型</div>
            <div className="mt-1 text-sm font-medium text-[var(--text-primary)]">{TASK_TYPE_LABEL[taskType]}</div>
          </div>
          <div className="rounded-[var(--radius-md)] border border-[var(--border-light)] bg-[var(--bg-secondary)] px-4 py-3">
            <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">候选范围</div>
            <div className="mt-1 text-sm font-medium text-[var(--text-primary)]">
              {taskType === 'rotation' ? '全部板块 ETF' : normalizedSector ? `${normalizedSector} 行业 ETF` : '缺少板块配置'}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="text-sm text-[var(--text-muted)]">
            已监控 {existingSet.size} 个 ETF，可新增 {candidates.length} 个。
          </div>
          <input
            type="search"
            value={searchValue}
            onChange={(event) => {
              setSearchValue(event.target.value);
              setError(null);
            }}
            disabled={isLoading || isSubmitting}
            placeholder="按代码或名称筛选"
            className="w-full rounded-[var(--radius-sm)] border border-[var(--border-light)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-blue)] md:w-64"
          />
        </div>

        {selectedCandidateDetails.length > 0 && (
          <div className="rounded-[var(--radius-md)] border border-[var(--border-light)] bg-[var(--bg-secondary)] px-4 py-3">
            <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">已选择</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {selectedCandidateDetails.map((etf) => (
                <button
                  key={etf.symbol}
                  type="button"
                  onClick={() => handleToggle(normalizeSymbol(etf.symbol))}
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-2 rounded-full bg-[var(--accent-blue)]/10 px-3 py-1 text-xs font-medium text-[var(--accent-blue)] transition-colors hover:bg-[var(--accent-blue)]/20 disabled:opacity-50"
                >
                  <span>{etf.symbol}</span>
                  <span className="text-[10px]">移除</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-[var(--radius-md)] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="max-h-[340px] overflow-y-auto rounded-[var(--radius-md)] border border-[var(--border-light)]">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 px-4 py-10 text-sm text-[var(--text-muted)]">
              <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>正在加载可添加 ETF...</span>
            </div>
          ) : filteredCandidates.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-[var(--text-muted)]">
              {candidates.length === 0 ? '当前没有可添加的 ETF。' : '没有匹配的 ETF，请调整筛选条件。'}
            </div>
          ) : (
            <div className="divide-y divide-[var(--border-light)]">
              {filteredCandidates.map((etf) => {
                const symbol = normalizeSymbol(etf.symbol);
                const checked = selectedSymbols.includes(symbol);
                return (
                  <label
                    key={symbol}
                    className={`flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors ${
                      checked ? 'bg-[var(--accent-blue)]/5' : 'bg-[var(--bg-primary)] hover:bg-[var(--bg-secondary)]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={isSubmitting}
                      onChange={() => handleToggle(symbol)}
                      className="mt-1 h-4 w-4 rounded border-[var(--border-light)] text-[var(--accent-blue)] focus:ring-[var(--accent-blue)]"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-[var(--text-primary)]">{symbol}</span>
                        <span className="text-xs text-[var(--text-muted)]">
                          {etf.rank > 0 ? `#${etf.rank}` : '未排名'}
                        </span>
                      </div>
                      <div className="mt-1 text-sm text-[var(--text-secondary)]">{etf.name || symbol}</div>
                    </div>
                    <div className="shrink-0 text-right text-xs text-[var(--text-muted)]">
                      <div>Score</div>
                      <div className="mt-1 text-sm font-medium text-[var(--text-primary)]">
                        {Number.isFinite(etf.score) && etf.score > 0 ? etf.score.toFixed(1) : '--'}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Tab-local footer actions */}
      <div className="flex justify-end gap-3 pt-4 border-t border-[var(--border-light)] mt-4">
        <button
          type="button"
          onClick={onClose}
          disabled={isSubmitting}
          className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isSubmitting || isLoading || selectedSymbols.length === 0}
          className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? '添加中...' : `添加 ETF${selectedSymbols.length > 0 ? ` (${selectedSymbols.length})` : ''}`}
        </button>
      </div>
    </>
  );
}

// ============ Node tab (drilldown only) ============

type NodeGroup = 'gics' | 'chain' | 'evidence';

interface NodeTabProps {
  sector: string;
  existingNodeSet: Set<string>;
  isSubmitting: boolean;
  onSubmit: (etfs: string[], nodes: string[]) => Promise<void>;
  onClose: () => void;
}

function NodeTab({ sector, existingNodeSet, isSubmitting, onSubmit, onClose }: NodeTabProps) {
  const [catalogItems, setCatalogItems] = useState<NodeCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sector) return;
    let cancelled = false;
    setIsLoading(true);
    api.getNodeCatalog(sector, true).then((items) => {
      if (cancelled) return;
      setCatalogItems(items.filter((n) => !existingNodeSet.has(n.id)));
      setSelectedNodes([]);
      setIsLoading(false);
    }).catch(() => {
      if (!cancelled) {
        setCatalogItems([]);
        setIsLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [sector, existingNodeSet]);

  const grouped = useMemo<Record<NodeGroup, NodeCatalogItem[]>>(() => {
    const gics: NodeCatalogItem[] = [];
    const chain: NodeCatalogItem[] = [];
    const evidence: NodeCatalogItem[] = [];
    for (const item of catalogItems) {
      if (item.node_type === 'evidence') evidence.push(item);
      else if (item.node_type === 'chain' || item.node_type === 'leaf') chain.push(item);
      else gics.push(item);
    }
    return { gics, chain, evidence };
  }, [catalogItems]);

  const toggle = (id: string) => {
    if (isSubmitting) return;
    setSelectedNodes((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]
    );
    setError(null);
  };

  const handleSubmit = async () => {
    if (selectedNodes.length === 0) {
      setError('请至少选择一个节点');
      return;
    }
    // derive proxy ETFs from selected nodes
    const proxyEtfs = selectedNodes
      .flatMap((id) => {
        const item = catalogItems.find((n) => n.id === id);
        return item?.proxy_etf ? [item.proxy_etf] : [];
      })
      .filter((v, i, a) => a.indexOf(v) === i);
    await onSubmit(proxyEtfs, selectedNodes);
  };

  const renderGroup = (title: string, items: NodeCatalogItem[], color: 'blue' | 'purple' | 'amber') => {
    if (items.length === 0) return null;
    const colorMap = {
      blue: { sel: 'bg-blue-50 border-[var(--accent-blue)] text-[var(--accent-blue)]', unsel: 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]' },
      purple: { sel: 'bg-purple-50 border-[var(--accent-purple)] text-[var(--accent-purple)]', unsel: 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]' },
      amber: { sel: 'bg-amber-50 border-amber-400 text-amber-700', unsel: 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]' },
    };
    return (
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">{title}</div>
        <div className="flex flex-wrap gap-2">
          {items.map((node) => {
            const sel = selectedNodes.includes(node.id);
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => toggle(node.id)}
                disabled={isSubmitting}
                className={`px-3 py-1.5 rounded-[var(--radius-md)] text-sm font-medium border-2 transition-all cursor-pointer disabled:opacity-50 ${sel ? colorMap[color].sel : colorMap[color].unsel}`}
              >
                {node.label}
                {node.proxy_etf && <span className="ml-1.5 text-[11px] opacity-70">{node.proxy_etf}</span>}
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <>
      <p className="text-sm text-[var(--text-muted)] -mt-1 mb-3">
        追加节点到 <span className="font-medium">{sector}</span> 下钻任务。已在任务中的节点已过滤。
      </p>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--text-muted)]">
          <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span>正在加载节点...</span>
        </div>
      ) : catalogItems.length === 0 ? (
        <div className="py-10 text-center text-sm text-[var(--text-muted)]">
          没有可追加的节点（已全部添加，或节点图谱未导入）。
        </div>
      ) : (
        <div className="space-y-4 max-h-[340px] overflow-y-auto pr-1">
          {renderGroup('GICS 行业节点', grouped.gics, 'blue')}
          {renderGroup('产业链节点', grouped.chain, 'purple')}
          {renderGroup('证据 / 主题节点', grouped.evidence, 'amber')}
        </div>
      )}

      {selectedNodes.length > 0 && (
        <div className="mt-3 text-sm text-[var(--text-muted)]">
          已选 {selectedNodes.length} 个节点
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-[var(--radius-md)] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-3 pt-4 border-t border-[var(--border-light)] mt-4">
        <button
          type="button"
          onClick={onClose}
          disabled={isSubmitting}
          className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] border border-[var(--border-light)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isSubmitting || isLoading || selectedNodes.length === 0}
          className="px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? '添加中...' : `追加节点 (${selectedNodes.length})`}
        </button>
      </div>
    </>
  );
}

// ============ Main modal ============

type ActiveTab = 'etf' | 'node';

export function AddTaskETFsModal({
  isOpen,
  onClose,
  taskType,
  taskSector,
  existingEtfs,
  existingNodes = [],
  onSubmit,
}: AddTaskETFsModalProps) {
  const normalizedSector = useMemo(() => normalizeSymbol(taskSector), [taskSector]);
  const existingSet = useMemo(
    () => new Set(existingEtfs.map((s) => normalizeSymbol(s)).filter((s) => s !== '')),
    [existingEtfs]
  );
  const existingNodeSet = useMemo(
    () => new Set(existingNodes.filter((n) => n !== '')),
    [existingNodes]
  );

  const [activeTab, setActiveTab] = useState<ActiveTab>('etf');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isDrilldown = taskType === 'drilldown';

  // Reset tab when modal opens
  useEffect(() => {
    if (isOpen) {
      setActiveTab('etf');
    }
  }, [isOpen]);

  const handleClose = () => {
    if (isSubmitting) return;
    onClose();
  };

  const handleETFSubmit = async (symbols: string[]) => {
    setIsSubmitting(true);
    try {
      await onSubmit(symbols);
      handleClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleNodeSubmit = async (etfs: string[], nodes: string[]) => {
    setIsSubmitting(true);
    try {
      await onSubmit(etfs, nodes);
      handleClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={
        <div className="flex items-center gap-2">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span>{isDrilldown ? '追加节点 / ETF' : '添加 ETF'}</span>
        </div>
      }
      subtitle={undefined}
    >
      {/* Tab bar — only shown for drilldown */}
      {isDrilldown && (
        <div className="flex border-b border-[var(--border-light)] mb-4 -mt-2">
          {([['etf', '添加 ETF'], ['node', '追加节点']] as [ActiveTab, string][]).map(([tab, label]) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === tab
                  ? 'border-[var(--accent-blue)] text-[var(--accent-blue)]'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {activeTab === 'etf' || !isDrilldown ? (
        <ETFTab
          taskType={taskType}
          normalizedSector={normalizedSector}
          existingSet={existingSet}
          isSubmitting={isSubmitting}
          onSubmit={handleETFSubmit}
          onClose={handleClose}
        />
      ) : (
        <NodeTab
          sector={normalizedSector}
          existingNodeSet={existingNodeSet}
          isSubmitting={isSubmitting}
          onSubmit={handleNodeSubmit}
          onClose={handleClose}
        />
      )}
    </Modal>
  );
}
