import React, { useState } from 'react';
import { Modal } from './Modal';
import type { TaskType } from '../../types';

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
  baseIndex: 'SPY' | 'QQQ' | 'IWM';
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

const BASE_INDICES = [
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
  const [baseIndex, setBaseIndex] = useState<'SPY' | 'QQQ' | 'IWM'>('SPY');

  const resetForm = () => {
    setCurrentStep(1);
    setTaskName('');
    setTaskType('rotation');
    setSelectedETFs([]);
    setSelectedSector(null);
    setBaseIndex('SPY');
  };

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

  const handleSubmit = () => {
    const taskTitle = taskName.trim() || generateTaskTitle();
    onSubmit({
      type: taskType,
      name: taskName.trim(),
      title: taskTitle,
      etfs: selectedETFs,
      sector: selectedSector,
      baseIndex,
    });
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

  const canProceed = () => {
    switch (currentStep) {
      case 1:
        return taskName.trim().length > 0;
      case 2:
        if (taskType === 'rotation') return selectedETFs.length >= 2;
        if (taskType === 'drilldown') return selectedSector && selectedETFs.length >= 1;
        if (taskType === 'momentum') return selectedSector && selectedETFs.length >= 1;
        return false;
      case 3:
        return true;
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
        return (
          <StepSelectAnchor
            baseIndex={baseIndex}
            onSelect={setBaseIndex}
            taskType={taskType}
            selectedETFs={selectedETFs}
            selectedSector={selectedSector}
          />
        );
      case 4:
        return (
          <StepConfirm
            taskType={taskType}
            selectedETFs={selectedETFs}
            selectedSector={selectedSector}
            baseIndex={baseIndex}
            title={taskName.trim() || generateTaskTitle()}
          />
        );
      default:
        return null;
    }
  };

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
      <StepNav currentStep={currentStep} />
      <div className="mt-6">{renderStepContent()}</div>
    </Modal>
  );
}

// Step Navigation Component
function StepNav({ currentStep }: { currentStep: number }) {
  const steps = [
    { num: 1, label: '选择类型' },
    { num: 2, label: '配置ETF' },
    { num: 3, label: '锚定层级' },
    { num: 4, label: '确认创建' },
  ];

  return (
    <div className="flex items-center justify-center gap-2">
      {steps.map((step, index) => (
        <React.Fragment key={step.num}>
          <div
            className={`
              flex items-center gap-2 px-4 py-2 rounded-sm transition-colors
              ${currentStep === step.num ? 'bg-blue-50' : ''}
              ${currentStep > step.num ? 'opacity-70' : ''}
            `}
          >
            <span
              className={`
                w-7 h-7 flex items-center justify-center rounded-full text-[13px] font-semibold transition-colors
                ${currentStep === step.num
                  ? 'bg-[var(--accent-blue)] text-white'
                  : currentStep > step.num
                  ? 'bg-[var(--accent-green)] text-white'
                  : 'bg-[var(--border-light)] text-[var(--text-muted)]'
                }
              `}
            >
              {currentStep > step.num ? '✓' : step.num}
            </span>
            <span
              className={`
                text-sm font-medium
                ${currentStep === step.num
                  ? 'text-[var(--accent-blue)]'
                  : 'text-[var(--text-muted)]'
                }
              `}
            >
              {step.label}
            </span>
          </div>
          {index < steps.length - 1 && (
            <div
              className={`
                w-10 h-0.5 transition-colors
                ${currentStep > step.num ? 'bg-[var(--accent-green)]' : 'bg-[var(--border-light)]'}
              `}
            />
          )}
        </React.Fragment>
      ))}
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

// Step 2: Configure ETFs
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

  return (
    <div>
      <div className="mb-6">
        <h3 className="text-base font-semibold mb-2">选择板块</h3>
        <p className="text-sm text-[var(--text-muted)] mb-4">
          {taskType === 'drilldown' ? '选择要下钻分析的板块' : '选择要追踪动能股的板块'}
        </p>
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

// Step 3: Select Anchor/Baseline
function StepSelectAnchor({
  baseIndex,
  onSelect,
  taskType,
  selectedETFs,
  selectedSector,
}: {
  baseIndex: 'SPY' | 'QQQ' | 'IWM';
  onSelect: (index: 'SPY' | 'QQQ' | 'IWM') => void;
  taskType: TaskType;
  selectedETFs: string[];
  selectedSector: string | null;
}) {
  return (
    <div>
      <h3 className="text-base font-semibold mb-2">选择基准指数</h3>
      <p className="text-sm text-[var(--text-muted)] mb-4">选择用于相对强弱比较的基准</p>
      <div className="grid grid-cols-3 gap-4 mb-6">
        {BASE_INDICES.map((index) => (
          <button
            key={index.value}
            onClick={() => onSelect(index.value as 'SPY' | 'QQQ' | 'IWM')}
            className={`
              p-4 text-left border-2 rounded-[var(--radius-md)] cursor-pointer transition-all
              ${baseIndex === index.value
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
            <span className="ml-2 font-medium">{baseIndex}</span>
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
  baseIndex,
  title,
}: {
  taskType: TaskType;
  selectedETFs: string[];
  selectedSector: string | null;
  baseIndex: string;
  title: string;
}) {
  return (
    <div>
      <div className="text-center mb-6">
        <div className="text-5xl mb-4">✅</div>
        <h3 className="text-xl font-semibold mb-2">确认创建任务</h3>
        <p className="text-[var(--text-muted)]">请确认以下配置信息</p>
      </div>

      <div className="p-5 bg-[var(--bg-secondary)] rounded-[var(--radius-lg)] border border-[var(--border-light)]">
        <div className="space-y-4">
          <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
            <span className="text-[var(--text-muted)]">任务名称</span>
            <span className="font-semibold">{title}</span>
          </div>
          <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
            <span className="text-[var(--text-muted)]">任务类型</span>
            <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-100 text-[var(--accent-purple)]">
              {taskType === 'rotation' ? '板块轮动' : taskType === 'drilldown' ? '板块下钻' : '动能追踪'}
            </span>
          </div>
          <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
            <span className="text-[var(--text-muted)]">基准指数</span>
            <span className="font-semibold">{baseIndex}</span>
          </div>
          {selectedSector && (
            <div className="flex justify-between items-center py-2 border-b border-[var(--border-light)]">
              <span className="text-[var(--text-muted)]">目标板块</span>
              <span className="font-semibold">{selectedSector}</span>
            </div>
          )}
          <div className="py-2">
            <span className="text-[var(--text-muted)] block mb-2">监控ETF</span>
            <div className="flex flex-wrap gap-2">
              {selectedETFs.map((etf) => (
                <span
                  key={etf}
                  className="px-3 py-1 bg-[var(--bg-tertiary)] rounded-[var(--radius-sm)] text-sm font-medium"
                >
                  {etf}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}