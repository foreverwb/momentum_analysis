# momentum_analysis 项目说明

## 项目概述
美股动能分析系统，包含板块轮动、行业下钻、个股动能筛选三层评分体系。
后端 Python (FastAPI + SQLAlchemy)，前端 React + TypeScript (Vite)。

## 关键架构
- `backend/app/services/calculators/` — 核心计算引擎
  - `regime_gate.py` — 市场环境 A/B/C 判断
  - `etf_score.py` — 行业 ETF 综合评分（已有横截面标准化）
  - `stock_score.py` — 个股评分（已弃用，待迁移到 momentum_pool）
  - `momentum_pool.py` — 动能股池评分（升级目标）
  - `momentum.py` — RS/RelMom 纯计算
  - `technical.py` — 技术指标计算库
- `backend/app/api/` — FastAPI 路由
- `backend/app/models/database.py` — SQLAlchemy 模型
- `frontend/src/pages/CoreTerminal.tsx` — Regime Gate 前端页面

## 编码规范

### 类型与文档
- Python 所有新函数必须带 type hints
- docstring 三段式：`Args` / `Returns` / `Raises`，不省略
- 前端所有新组件和函数必须有 TypeScript 类型，禁止 `any`
- 模块顶部必须有模块级 `"""docstring"""`，说明职责与禁止做什么

### 注释规范
- 只写 WHY 注释：隐藏约束、公式出处、反直觉的决策
- 公式行必须注释来源（`# 需求文档 §X.Y` 或论文引用）
- 历史决策点必须注释原因（`# 向后兼容，Phase5 再清理`）
- TODO 统一格式：`# TODO(phaseN): 描述 — yyyy-mm-dd`
- 禁止描述代码做了什么的注释（命名本身应已说明）

### 可维护性
- 单函数 ≤ 60 行（不含 docstring）；超出必须拆分子函数
- 单文件 ≤ 600 行；超出按职责拆分为多个模块
- 嵌套层数 ≤ 3 层；用提早 return / 子函数降低圈复杂度
- 魔法数字全部常量化于文件顶部，`UPPER_SNAKE_CASE` + 注释来源
- 错误处理分层：计算层抛领域异常，API 层统一转 `HTTPException`，禁止在计算层直接抛 HTTP 异常

### 扩展性
- 新增同类配置（如新板块 YAML）时，不应改任何 `.py` 核心逻辑
- 多态分派用策略表（`Dict[EnumType, Callable]`），禁止写 if-else 枚举链
- 抽象类 / Protocol 定义扩展点，子类注册到 registry，主流程不感知具体实现

### 向后兼容 & 数据安全
- 不删除旧函数：标记 `# @deprecated — 原因 + 替代方案`，保留实现
- 数据库变更只走 `Base.metadata.create_all` + 列补齐函数，禁止使用 alembic
- 新增 DB 列必须 `nullable=True` 或带 `default`，不破坏老数据行
- 旧字段只读不删，除非 Phase 计划中明确列出"清理"步骤

### 测试
- 修改计算逻辑后必须运行 `pytest backend/tests/ -v`，全部通过才算完成
- 计算引擎必须有：正常路径 + ≥ 2 个边界用例（空数据、单元素、覆盖率不足）
- 数据迁移脚本必须有：dry_run / commit / 重复执行幂等 / 回滚 四类测试
- API 端点必须有：200 正常路径 + 4xx 错误路径

### 范围控制
- 只动任务中明确列出的文件，不顺手 refactor 无关代码
- bug fix 不附带周边清理；单次 PR 不引入未要求的抽象
- 三处相似代码才考虑抽象，不提前设计

## 当前升级任务
- Phase 1/2/3：参考 `Phase1_2_3.md`
- Phase 4（板块下钻 Node-Centric 升级）：参考 `Phase4_Drilldown_Upgrade.md`
