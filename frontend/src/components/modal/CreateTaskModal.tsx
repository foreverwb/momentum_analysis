import React, { useEffect, useState } from 'react';
import { Modal } from './Modal';
import type { TaskType, NodeCatalogItem, TaskViewMode } from '../../types';
import * as api from '../../services/api';

type BaseIndexSymbol = 'SPY' | 'QQQ' | 'IWM';

interface CreateTaskModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (taskData: CreateTaskData) => void;
}

export interface CreateTaskData {
  type: TaskType;
  name: string;
  title: string;
  etfs: string[];
  sector: string | null;
  baseIndex: string;
  baseIndices: BaseIndexSymbol[];
  // Phase 4.11 — node-centric drilldown fields
  rootNode?: string;
  viewMode?: TaskViewMode;
  selectedNodes?: string[];
  pinnedEvidenceNodes?: string[];
}

// ETF Data
const SECTOR_ETFS = [
  { symbol: 'XLK', name: '科技' },
  { symbol: 'XLF', name: '金融' },
  { symbol: 'XLV', name: '医疗' },
  { symbol: 'XLE', name: '能源' },
  { symbol: 'XLY', name: '消费' },
  { symbol: 'XLI', name: '工业' },
  { symbol: 'XLC', name: '通信' },
  { symbol: 'XLP', name: '必需消费品' },
  { symbol: 'XLU', name: '公用事业' },
  { symbol: 'XLRE', name: '房地产' },
  { symbol: 'XLB', name: '材料' },
];

// rotation / momentum tasks still need per-sector industry ETFs (hardcoded, unchanged)
const INDUSTRY_ETFS: Record<string, { symbol: string; name: string }[]> = {
  XLK: [
    { symbol: 'SOXX', name: '半导体' },
    { symbol: 'SMH', name: '半导体' },
    { symbol: 'IGV', name: '软件' },
    { symbol: 'SKYY', name: '云计算' },
    { symbol: 'HACK', name: '网络安全' },
    { symbol: 'CLOU', name: '云计算' },
  ],
  XLF: [
    { symbol: 'KBE', name: '银行' },
    { symbol: 'KRE', name: '区域银行' },
    { symbol: 'IAI', name: '券商资管' },
    { symbol: 'KIE', name: '保险' },
  ],
  XLV: [
    { symbol: 'XBI', name: '生物科技' },
    { symbol: 'IBB', name: '生物科技' },
    { symbol: 'IHI', name: '医疗器械' },
    { symbol: 'XHS', name: '医疗服务' },
  ],
  XLE: [
    { symbol: 'XOP', name: '油气开采' },
    { symbol: 'OIH', name: '油服设备' },
    { symbol: 'AMLP', name: 'MLP管道' },
  ],
  XLY: [
    { symbol: 'XRT', name: '零售' },
    { symbol: 'XHB', name: '住宅建筑' },
    { symbol: 'BETZ', name: '博彩' },
    { symbol: 'PEJ', name: '休闲娱乐' },
  ],
  XLI: [
    { symbol: 'ITA', name: '航空航天国防' },
    { symbol: 'XAR', name: '航空航天国防' },
    { symbol: 'JETS', name: '航空' },
  ],
};

const BASE_INDICES: { value: BaseIndexSymbol; name: string; description: string }[] = [
  { value: 'SPY', name: 'SPY', description: '标普500 - 大盘基准' },
  { value: 'QQQ', name: 'QQQ', description: '纳斯达克100 - 成长股基准' },
  { value: 'IWM', name: 'IWM', description: '罗素2000 - 小盘股基准' },
];

const TASK_TYPES: { type: TaskType; title: string; description: string; icon: string }[] = [
  {
    type: 'rotation',
    title: '板块轮动',
    description: '监控多个板块ETF相对强弱，捕捉轮动机会',
    icon: '🔄',
  },
  {
    type: 'drilldown',
    title: '板块内下钻',
    description: '选定板块后，对比其下属行业ETF的动能表现',
    icon: '🔍',
  },
  {
    type: 'momentum',
    title: '动能股追踪',
    description: '追踪特定行业内的高动能个股',
    icon: '📈',
  },
];

export function CreateTaskModal({ isOpen, onClose, onSubmit }: CreateTaskModalProps) {
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1);
  const [taskName, setTaskName] = useState<string>('');
  const [taskType, setTaskType] = useState<TaskType>('rotation');
  const [selectedETFs, setSelectedETFs] = useState<string[]>([]);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [baseIndices, setBaseIndices] = useState<BaseIndexSymbol[]>(['SPY']);

  // drilldown node-centric state (Phase 4.11)
  const [catalogItems, setCatalogItems] = useState<NodeCatalogItem[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>([]);

  const resetForm = () => {
    setCurrentStep(1);
    setTaskName('');
    setTaskType('rotation');
    setSelectedETFs([]);
    setSelectedSector(null);
    setBaseIndices(['SPY']);
    setCatalogItems([]);
    setSelectedNodes([]);
    setSelectedEvidenceIds([]);
  };

  // When drilldown sector changes, load catalog and auto-select GICS nodes
  useEffect(() => {
    if (taskType !== 'drilldown' || !selectedSector) {
      setCatalogItems([]);
      setSelectedNodes([]);
      setSelectedEvidenceIds([]);
      return;
    }
    let cancelled = false;
    setCatalogLoading(true);
    api.getNodeCatalog(selectedSector, true).then((items) => {
      if (cancelled) return;
      setCatalogItems(items);
      // Auto-select all GICS-type nodes
      const gicsIds = items
        .filter((n) => n.node_type === 'gics')
        .map((n) => n.id);
      setSelectedNodes(gicsIds);
      setSelectedEvidenceIds([]);
      setCatalogLoading(false);
    }).catch(() => {
      if (!cancelled) {
        setCatalogItems([]);
        setCatalogLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [taskType, selectedSector]);

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleNext = () => {
    if (currentStep < 4) {
      setCurrentStep((prev) => (prev + 1) as 1 | 2 | 3 | 4);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep((prev) => (prev - 1) as 1 | 2 | 3 | 4);
    }
  };

  // Build nodeIdToProxy map for etfs compatibility field
  const nodeIdToProxy = React.useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    for (const item of catalogItems) {
      if (item.proxy_etf) {
        map[item.id] = item.proxy_etf;
      }
    }
    return map;
  }, [catalogItems]);

  const handleSubmit = () => {
    const normalizedTaskName = taskName.trim();
    const normalizedBaseIndices: BaseIndexSymbol[] = baseIndices.length > 0 ? baseIndices : ['SPY'];
    const taskTitle = normalizedTaskName || generateTaskTitle();

    if (taskType === 'drilldown' && selectedSector) {
      const allSelectedNodes = [...selectedNodes, ...selectedEvidenceIds];
      const proxyEtfs = allSelectedNodes
        .flatMap((id) => (nodeIdToProxy[id] ? [nodeIdToProxy[id]] : []))
        .filter((v, i, a) => a.indexOf(v) === i);

      onSubmit({
        type: taskType,
        name: normalizedTaskName,
        title: taskTitle,
        etfs: proxyEtfs,
        sector: selectedSector,
        baseIndex: normalizedBaseIndices.join(','),
        baseIndices: normalizedBaseIndices,
        rootNode: selectedSector,
        viewMode: 'gics',
        selectedNodes: allSelectedNodes,
        pinnedEvidenceNodes: selectedEvidenceIds,
      });
    } else {
      onSubmit({
        type: taskType,
        name: normalizedTaskName,
        title: taskTitle,
        etfs: selectedETFs,
        sector: selectedSector,
        baseIndex: normalizedBaseIndices.join(','),
        baseIndices: normalizedBaseIndices,
      });
    }
    handleClose();
  };

  const generateTaskTitle = () => {
    switch (taskType) {
      case 'rotation':
        return `${selectedETFs.length}板块轮动监控`;
      case 'drilldown':
        return `${SECTOR_ETFS.find(e => e.symbol === selectedSector)?.name || selectedSector}内部行业下钻`;
      case 'momentum':
        return `${SECTOR_ETFS.find(e => e.symbol === selectedSector)?.name || selectedSector}动能股追踪`;
      default:
        return '新建监控任务';
    }
  };

  const toggleETF = (symbol: string) => {
    setSelectedETFs((prev) =>
      prev.includes(symbol) ? prev.filter((s) => s !== symbol) : [...prev, symbol]
    );
  };

  const toggleBaseIndex = (index: BaseIndexSymbol) => {
    setBaseIndices((prev) => {
      const next = prev.includes(index)
        ? prev.length > 1
          ? prev.filter((item) => item !== index)
          : prev
        : [...prev, index];
      return BASE_INDICES.map((item) => item.value).filter((item) => next.includes(item));
    });
  };

  const canProceed = () => {
    switch (currentStep) {
      case 1:
        return taskName.trim().length > 0;
      case 2:
        if (taskType === 'rotation') return selectedETFs.length >= 2;
        if (taskType === 'drilldown') return selectedSector !== null;
        if (taskType === 'momentum') return selectedSector && selectedETFs.length >= 1;
        return false;
      case 3:
        if (taskType === 'drilldown') {
          // need at least one node selected (GICS auto-selected on catalog load)
          return selectedNodes.length > 0 || selectedEvidenceIds.length > 0;
        }
        return baseIndices.length > 0;
      case 4:
        return true;
      default:
        return false;
    }
  };

  const renderStepContent = () => {
    switch (currentStep) {
      case 1:
        return <StepSelectType taskType={taskType} onSelect={setTaskType} taskName={taskName} onNameChange={setTaskName} />;
      case 2:
        return (
          <StepConfigureETFs
            taskType={taskType}
            selectedETFs={selectedETFs}
            selectedSector={selectedSector}
            onToggleETF={toggleETF}
            onSelectSector={(sector) => {
              setSelectedSector(sector);
              setSelectedETFs([]);
            }}
          />
        );
      case 3:
        if (taskType === 'drilldown' && selectedSector) {
          return (
            <StepSelectNodes
              sector={selectedSector}
              catalogItems={catalogItems}
              loading={catalogLoading}
              selectedNodes={selectedNodes}
              selectedEvidenceIds={selectedEvidenceIds}
              onToggleNode={(id) =>
                setSelectedNodes((prev) =>
                  prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]
                )
              }
              onToggleEvidence={(id) =>
                setSelectedEvidenceIds((prev) =>
                  prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]
                )
              }
            />
          );
        }
        return (
          <StepSelectAnchor
            baseIndices={baseIndices}
            onToggle={toggleBaseIndex}
            taskType={taskType}
            selectedETFs={selectedETFs}
            selectedSector={selectedSector}
          />
        );
      case 4:
        return (
          <StepConfirm
            taskType={taskType}
            selectedETFs={taskType === 'drilldown' && selectedSector
              ? [...selectedNodes, ...selectedEvidenceIds]
              : selectedETFs
            }
            selectedSector={selectedSector}
            baseIndices={baseIndices}
            taskName={taskName}
            onNameChange={setTaskName}
            defaultTitle={generateTaskTitle()}
            isNodeCentric={taskType === 'drilldown' && !!selectedSector}
          />
        );
      default:
        return null;
    }
  };

  // For drilldown, step 3 label changes
  const stepLabels =
    taskType === 'drilldown'
      ? ['选择类型', '选择板块', '选择节点', '确认创建']
      : ['选择类型', '配置ETF', '锚定层级', '确认创建'];

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="创建监控任务"
      subtitle="设置一个新的动能监控任务来追踪市场机会"
      footer={
        <>
          {currentStep > 1 && (
            <button
              onClick={handleBack}
              className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] transition-colors"
            >
              上一步
            </button>
          )}
          {currentStep < 4 ? (
            <button
              onClick={handleNext}
              disabled={!canProceed()}
              className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-blue)] text-white hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              下一步
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              className="px-5 py-2.5 text-sm font-medium rounded-[var(--radius-sm)] bg-[var(--accent-green)] text-white hover:bg-green-600 transition-colors"
            >
              创建任务
            </button>
          )}
        </>
      }
    >
      <StepNav currentStep={currentStep} labels={stepLabels} />
      <div className="mt-6">{renderStepContent()}</div>
    </Modal>
  );
}

// Step Navigation Component
function StepNav({ currentStep, labels }: { currentStep: number; labels: string[] }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {labels.map((label, index) => {
        const stepNum = index + 1;
        return (
          <React.Fragment key={stepNum}>
            <div
              className={`
                flex items-center gap-2 px-4 py-2 rounded-sm transition-colors
                ${currentStep === stepNum ? 'bg-blue-50' : ''}
                ${currentStep > stepNum ? 'opacity-70' : ''}
              `}
            >
              <span
                className={`
                  w-7 h-7 flex items-center justify-center rounded-full text-[13px] font-semibold transition-colors
                  ${currentStep === stepNum
                    ? 'bg-[var(--accent-blue)] text-white'
                    : currentStep > stepNum
                    ? 'bg-[var(--accent-green)] text-white'
                    : 'bg-[var(--border-light)] text-[var(--text-muted)]'
                  }
                `}
              >
                {currentStep > stepNum ? '✓' : stepNum}
              </span>
              <span
                className={`
                  text-sm font-medium
                  ${currentStep === stepNum
                    ? 'text-[var(--accent-blue)]'
                    : 'text-[var(--text-muted)]'
                  }
                `}
              >
                {label}
              </span>
            </div>
            {index < labels.length - 1 && (
              <div
                className={`
                  w-10 h-0.5 transition-colors
                  ${currentStep > stepNum ? 'bg-[var(--accent-green)]' : 'bg-[var(--border-light)]'}
                `}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// Step 1: Select Task Type
function StepSelectType({
  taskType,
  onSelect,
  taskName,
  onNameChange,
}: {
  taskType: TaskType;
  onSelect: (type: TaskType) => void;
  taskName: string;
  onNameChange: (name: string) => void;
}) {
  return (
    <div>
      {/* Task Name Input */}
      <div className="mb-6">
        <h3 className="text-base font-semibold mb-2">任务名称</h3>
        <input
          type="text"
          value={taskName}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="请输入任务名称"
          className="w-full px-4 py-3 text-sm border-2 border-[var(--border-light)] rounded-[var(--radius-md)] focus:outline-none focus:border-[var(--accent-blue)] transition-colors bg-[var(--bg-primary)]"
        />
      </div>

      <h3 className="text-base font-semibold mb-4">选择任务类型</h3>
      <div className="grid grid-cols-3 gap-4">
        {TASK_TYPES.map((type) => (
          <button
            key={type.type}
            onClick={() => onSelect(type.type)}
            className={`
              p-5 text-left bg-[var(--bg-primary)] border-2 rounded-[var(--radius-md)] cursor-pointer transition-all
              ${taskType === type.type
                ? 'border-[var(--accent-blue)] bg-blue-50/50'
                : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
              }
            `}
          >
            <div className="text-2xl mb-3">{type.icon}</div>
            <div className="text-base font-semibold mb-1">{type.title}</div>
            <div className="text-[13px] text-[var(--text-muted)] leading-relaxed">
              {type.description}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// Step 2: Configure ETFs (rotation/momentum unchanged; drilldown shows sector only)
function StepConfigureETFs({
  taskType,
  selectedETFs,
  selectedSector,
  onToggleETF,
  onSelectSector,
}: {
  taskType: TaskType;
  selectedETFs: string[];
  selectedSector: string | null;
  onToggleETF: (symbol: string) => void;
  onSelectSector: (sector: string) => void;
}) {
  if (taskType === 'rotation') {
    return (
      <div>
        <h3 className="text-base font-semibold mb-2">选择板块ETF</h3>
        <p className="text-sm text-[var(--text-muted)] mb-4">选择至少2个板块进行轮动监控</p>
        <div className="flex flex-wrap gap-2.5">
          {SECTOR_ETFS.map((etf) => (
            <button
              key={etf.symbol}
              onClick={() => onToggleETF(etf.symbol)}
              className={`
                px-4 py-2.5 rounded-[var(--radius-md)] text-sm font-medium border-2 transition-all cursor-pointer
                ${selectedETFs.includes(etf.symbol)
                  ? 'bg-blue-50 border-[var(--accent-blue)] text-[var(--accent-blue)]'
                  : 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]'
                }
              `}
            >
              {etf.symbol} · {etf.name}
            </button>
          ))}
        </div>
        <div className="mt-4 text-sm text-[var(--text-muted)]">
          已选择 {selectedETFs.length} 个板块
        </div>
      </div>
    );
  }

  if (taskType === 'drilldown') {
    return (
      <div>
        <h3 className="text-base font-semibold mb-2">选择板块</h3>
        <p className="text-sm text-[var(--text-muted)] mb-4">选择要下钻分析的板块，下一步将从后端加载该板块的节点树</p>
        <div className="flex flex-wrap gap-2.5">
          {SECTOR_ETFS.map((etf) => (
            <button
              key={etf.symbol}
              onClick={() => onSelectSector(etf.symbol)}
              className={`
                px-4 py-2.5 rounded-[var(--radius-md)] text-sm font-medium border-2 transition-all cursor-pointer
                ${selectedSector === etf.symbol
                  ? 'bg-blue-50 border-[var(--accent-blue)] text-[var(--accent-blue)]'
                  : 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]'
                }
              `}
            >
              {etf.symbol} · {etf.name}
            </button>
          ))}
        </div>
        {selectedSector && (
          <div className="mt-4 text-sm text-[var(--text-muted)]">
            已选择板块：<span className="font-medium text-[var(--accent-blue)]">{selectedSector}</span>，点击"下一步"加载节点树
          </div>
        )}
      </div>
    );
  }

  // momentum
  return (
    <div>
      <div className="mb-6">
        <h3 className="text-base font-semibold mb-2">选择板块</h3>
        <p className="text-sm text-[var(--text-muted)] mb-4">选择要追踪动能股的板块</p>
        <div className="flex flex-wrap gap-2.5">
          {SECTOR_ETFS.map((etf) => (
            <button
              key={etf.symbol}
              onClick={() => onSelectSector(etf.symbol)}
              className={`
                px-4 py-2.5 rounded-[var(--radius-md)] text-sm font-medium border-2 transition-all cursor-pointer
                ${selectedSector === etf.symbol
                  ? 'bg-blue-50 border-[var(--accent-blue)] text-[var(--accent-blue)]'
                  : 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]'
                }
              `}
            >
              {etf.symbol} · {etf.name}
            </button>
          ))}
        </div>
      </div>

      {selectedSector && INDUSTRY_ETFS[selectedSector] && (
        <div>
          <h3 className="text-base font-semibold mb-2">选择行业ETF</h3>
          <p className="text-sm text-[var(--text-muted)] mb-4">选择要监控的行业ETF</p>
          <div className="flex flex-wrap gap-2.5">
            {INDUSTRY_ETFS[selectedSector].map((etf) => (
              <button
                key={etf.symbol}
                onClick={() => onToggleETF(etf.symbol)}
                className={`
                  px-4 py-2.5 rounded-[var(--radius-md)] text-sm font-medium border-2 transition-all cursor-pointer
                  ${selectedETFs.includes(etf.symbol)
                    ? 'bg-purple-50 border-[var(--accent-purple)] text-[var(--accent-purple)]'
                    : 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]'
                  }
                `}
              >
                {etf.symbol} · {etf.name}
              </button>
            ))}
          </div>
          <div className="mt-4 text-sm text-[var(--text-muted)]">
            已选择 {selectedETFs.length} 个行业ETF
          </div>
        </div>
      )}
    </div>
  );
}

// Step 3 (drilldown): Node catalog picker
function StepSelectNodes({
  sector,
  catalogItems,
  loading,
  selectedNodes,
  selectedEvidenceIds,
  onToggleNode,
  onToggleEvidence,
}: {
  sector: string;
  catalogItems: NodeCatalogItem[];
  loading: boolean;
  selectedNodes: string[];
  selectedEvidenceIds: string[];
  onToggleNode: (id: string) => void;
  onToggleEvidence: (id: string) => void;
}) {
  const gicsNodes = catalogItems.filter((n) => n.node_type === 'gics');
  const chainNodes = catalogItems.filter((n) => n.node_type === 'chain' || n.node_type === 'leaf');
  const evidenceNodes = catalogItems.filter((n) => n.node_type === 'evidence');

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--text-muted)]">
        <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <span>正在加载 {sector} 节点树...</span>
      </div>
    );
  }

  if (catalogItems.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-[var(--text-muted)]">
        未找到 {sector} 的节点数据，请先导入节点图谱。
      </div>
    );
  }

  const totalSelected = selectedNodes.length + selectedEvidenceIds.length;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">选择监控节点</h3>
          <p className="text-sm text-[var(--text-muted)] mt-0.5">
            板块：<span className="font-medium">{sector}</span> · 已选 {totalSelected} 个节点
          </p>
        </div>
      </div>

      {/* GICS 子节点 (default all selected) */}
      {gicsNodes.length > 0 && (
        <NodeGroup
          title="GICS 行业节点"
          description="默认全选，可取消"
          color="blue"
          nodes={gicsNodes}
          selectedIds={selectedNodes}
          onToggle={onToggleNode}
        />
      )}

      {/* 产业链节点 (手选) */}
      {chainNodes.length > 0 && (
        <NodeGroup
          title="产业链节点"
          description="按需选择"
          color="purple"
          nodes={chainNodes}
          selectedIds={selectedNodes}
          onToggle={onToggleNode}
        />
      )}

      {/* 证据节点 (手选) */}
      {evidenceNodes.length > 0 && (
        <NodeGroup
          title="证据 / 主题节点"
          description="用于交叉确认，按需固定"
          color="amber"
          nodes={evidenceNodes}
          selectedIds={selectedEvidenceIds}
          onToggle={onToggleEvidence}
        />
      )}
    </div>
  );
}

type ChipColor = 'blue' | 'purple' | 'amber';

function NodeGroup({
  title,
  description,
  color,
  nodes,
  selectedIds,
  onToggle,
}: {
  title: string;
  description: string;
  color: ChipColor;
  nodes: NodeCatalogItem[];
  selectedIds: string[];
  onToggle: (id: string) => void;
}) {
  const colorMap: Record<ChipColor, { selected: string; unselected: string }> = {
    blue: {
      selected: 'bg-blue-50 border-[var(--accent-blue)] text-[var(--accent-blue)]',
      unselected: 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]',
    },
    purple: {
      selected: 'bg-purple-50 border-[var(--accent-purple)] text-[var(--accent-purple)]',
      unselected: 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]',
    },
    amber: {
      selected: 'bg-amber-50 border-amber-400 text-amber-700',
      unselected: 'bg-[var(--bg-tertiary)] border-transparent text-[var(--text-secondary)] hover:border-[var(--border-medium)]',
    },
  };

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <h4 className="text-sm font-semibold">{title}</h4>
        <span className="text-xs text-[var(--text-muted)]">{description}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {nodes.map((node) => {
          const isSelected = selectedIds.includes(node.id);
          return (
            <button
              key={node.id}
              onClick={() => onToggle(node.id)}
              className={`
                px-3 py-2 rounded-[var(--radius-md)] text-sm font-medium border-2 transition-all cursor-pointer
                ${isSelected ? colorMap[color].selected : colorMap[color].unselected}
              `}
            >
              <span>{node.label}</span>
              {node.proxy_etf && (
                <span className="ml-1.5 text-[11px] opacity-70">{node.proxy_etf}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Step 3 (rotation/momentum): Select Anchor/Baseline
function StepSelectAnchor({
  baseIndices,
  onToggle,
  taskType,
  selectedETFs,
  selectedSector,
}: {
  baseIndices: BaseIndexSymbol[];
  onToggle: (index: BaseIndexSymbol) => void;
  taskType: TaskType;
  selectedETFs: string[];
  selectedSector: string | null;
}) {
  const baseIndexLabel = baseIndices.join(' / ');

  return (
    <div>
      <h3 className="text-base font-semibold mb-2">选择基准指数</h3>
      <p className="text-sm text-[var(--text-muted)] mb-4">选择用于相对强弱比较的基准（支持多选）</p>
      <div className="grid grid-cols-3 gap-4 mb-6">
        {BASE_INDICES.map((index) => (
          <button
            key={index.value}
            onClick={() => onToggle(index.value)}
            className={`
              p-4 text-left border-2 rounded-[var(--radius-md)] cursor-pointer transition-all
              ${baseIndices.includes(index.value)
                ? 'border-[var(--accent-blue)] bg-blue-50/50'
                : 'border-[var(--border-light)] hover:border-[var(--accent-blue)]'
              }
            `}
          >
            <div className="text-lg font-bold mb-1">{index.name}</div>
            <div className="text-[13px] text-[var(--text-muted)]">{index.description}</div>
          </button>
        ))}
      </div>
      <div className="mb-6 text-sm text-[var(--text-muted)]">
        已选择 {baseIndices.length} 个基准：{baseIndexLabel || '--'}
      </div>

      <div className="p-4 bg-[var(--bg-secondary)] rounded-[var(--radius-md)] border border-[var(--border-light)]">
        <h4 className="text-sm font-semibold mb-3">配置预览</h4>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-[var(--text-muted)]">任务类型:</span>
            <span className="ml-2 font-medium">
              {taskType === 'rotation' ? '板块轮动' : taskType === 'drilldown' ? '板块下钻' : '动能追踪'}
            </span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">基准指数:</span>
            <span className="ml-2 font-medium">{baseIndexLabel || '--'}</span>
          </div>
          {selectedSector && (
            <div>
              <span className="text-[var(--text-muted)]">目标板块:</span>
              <span className="ml-2 font-medium">{selectedSector}</span>
            </div>
          )}
          <div>
            <span className="text-[var(--text-muted)]">监控ETF:</span>
            <span className="ml-2 font-medium">{selectedETFs.length} 个</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// Step 4: Confirm
function StepConfirm({
  taskType,
  selectedETFs,
  selectedSector,
  baseIndices,
  taskName,
  onNameChange,
  defaultTitle,
  isNodeCentric,
}: {
  taskType: TaskType;
  selectedETFs: string[];
  selectedSector: string | null;
  baseIndices: BaseIndexSymbol[];
  taskName: string;
  onNameChange: (name: string) => void;
  defaultTitle: string;
  isNodeCentric: boolean;
}) {
  const finalTitle = taskName.trim() || defaultTitle;

  return (
    <div>
      <div className="text-center mb-6">
        <div className="text-5xl mb-4">✅</div>
        <h3 className="text-xl font-semibold mb-2">确认创建任务</h3>
        <p className="text-[var(--text-muted)]">请确认以下配置信息</p>
      </div>

      <div className="p-5 bg-[var(--bg-secondary)] rounded-[var(--radius-lg)] border border-[var(--border-light)]">
        <div className="space-y-4">
          <div className="py-2 border-b border-[var(--border-light)]">
            <span className="text-[var(--text-muted)] block mb-2">任务名称（可修改）</span>
            <input
              type="text"
              value={taskName}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder={defaultTitle}
              className="w-full px-3 py-2 text-sm border border-[var(--border-light)] rounded-[var(--radius-sm)] focus:outline-none focus:border-[var(--accent-blue)] bg-[var(--bg-primary)]"
            />
            <div className="mt-2 text-sm">
              <span className="text-[var(--text-muted)]">最终名称：</span>
              <span className="font-semibold">{finalTitle}</span>
            </div>
          </div>
          <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
            <span className="text-[var(--text-muted)]">任务类型</span>
            <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-100 text-[var(--accent-purple)]">
              {taskType === 'rotation' ? '板块轮动' : taskType === 'drilldown' ? '板块下钻' : '动能追踪'}
            </span>
          </div>
          <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
            <span className="text-[var(--text-muted)]">基准指数</span>
            <span className="font-semibold">{baseIndices.join(' / ') || '--'}</span>
          </div>
          {selectedSector && (
            <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
              <span className="text-[var(--text-muted)]">目标板块</span>
              <span className="font-semibold">{selectedSector}</span>
            </div>
          )}
          <div className="py-2">
            <span className="text-[var(--text-muted)] block mb-2">
              {isNodeCentric ? '选中节点' : '监控ETF'}
            </span>
            {selectedETFs.length === 0 ? (
              <span className="text-sm text-[var(--text-muted)]">
                {isNodeCentric ? '（已自动选择 GICS 节点）' : '--'}
              </span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {selectedETFs.map((item) => (
                  <span
                    key={item}
                    className="px-3 py-1 bg-[var(--bg-tertiary)] rounded-[var(--radius-sm)] text-sm font-medium"
                  >
                    {item}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
