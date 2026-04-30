# Phase 4：板块下钻 Node-Centric 升级实施任务

> 本文档是面向 Opus / Sonnet 模型的**自动化升级指令集**，目标：把当前"板块 ETF + 同板块行业 ETF 平铺"的二层 drilldown，升级为**节点(Node)为一等对象**的图谱化下钻引擎，并落地 [`design_handoff_drilldown/drilldown-upgrade.prototype.html`](file:///Users/bin/Downloads/design_handoff_drilldown/drilldown-upgrade.prototype.html) 设计的三栏前端布局。
>
> 需求来源：
> - `~/Downloads/板块内下钻功能升级.md` — 节点图谱框架与 XLK→半导体→连接→光/铜 落地示例
> - `~/Downloads/design_handoff_drilldown/README.md` 与 `drilldown-upgrade.prototype.html` — 高保真 UI 规格
>
> 每个 Task 都是**独立、自包含**的指令，可单独交付给 Opus/Sonnet 执行。后续 Task 依赖前序 Task 的产出（依赖关系在每节标头标注）。

---

## 0. 升级总览

### 0.1 现状（已读完代码确认）

| 维度 | 现状 | 局限 |
|------|------|------|
| 数据模型 | `ETF.type ∈ {sector, industry}` + `parent_sector` 单父关系 | 仅二层、无图、无节点抽象 |
| Task 模型 | `Task.sector + Task.etfs[]` 平铺 | 撑不起 ≥3 层下钻 |
| 校验逻辑 | `backend/app/api/tasks.py:95-158` 强制 drilldown 只能加同 sector 的 industry ETF | XLK 内 SOXX/SMH/IGV/SKYY 被混为同层 |
| API | `/etfs/sectors`、`/etfs/industries?sector=` | 没有 node/edge/proxy/basket 概念 |
| 前端创建任务 | `CreateTaskModal.tsx:38-46` 硬编码 `INDUSTRY_ETFS` | XLK 子项把 ETF proxy 与主题 ETF 混在一起 |
| 前端任务详情 | `TaskDetail.tsx:2114-2143` drilldown 也是 `etfDetails.map(<ETFDetailCard />)` 平铺 | 与 rotation 一样的平铺，没有树/图视图 |
| 持仓刷新 | `related_etf_symbols` 在同任务内做重叠跳过 | 只在 ETF 维度去重，未升到 node-scope |

### 0.2 目标体系（四层）

参考需求文档第 3 节，升级后体系为：

1. **节点层**：`AnalyticNode`（GICS / 产业链 / 介质叶子 / 证据主题 四类）
2. **关系层**：`NodeEdge`（classification_parent / chain_parent / proxy_of / corroborates / overlaps_with / drives_depends_on 六种边）
3. **市场表达层**：`NodeProxy`（primary ETF + secondary corroboration + synthetic basket + chain extension）
4. **分析输出层**：节点分数 = 旧 ETF 核心分（RelMom 0.45 / Trend 0.25 / Breadth 0.20 / Options 0.10）+ representation_confidence + chain_confirmation

### 0.3 落地路径（11 个 Task，按依赖顺序）

```
4.1 ─→ 4.2 ─→ 4.3 ─→ 4.4 ─→ 4.5 ─→ 4.6 ─→ 4.7
       (种子)                          (Task 模型) (Node API)  (前端骨架)
                                                              │
                                              ┌───────────────┼───────────────┐
                                              ▼               ▼               ▼
                                            4.8 NodeTree   4.9 Center      4.10 RightPanel
                                              │               │               │
                                              └───────────────┼───────────────┘
                                                              ▼
                                                            4.11 集成 + 表单升级
```

### 0.4 模型配置矩阵

> `model`: 推荐使用的模型 ID（Opus 4.7 = `claude-opus-4-7`，Sonnet 4.6 = `claude-sonnet-4-6`，Haiku 4.5 = `claude-haiku-4-5-20251001`）
> `effort`: 模型推理强度 `low / medium / high`
> `thinking`: 是否启用 extended thinking（`off / standard / extended`）— extended 适合需要多文件协同设计、跨层契约权衡的任务

| Task | 标题 | model | effort | thinking | 预估 token | 预估时长 |
|------|------|-------|--------|----------|----------|---------|
| 4.1  | Node 数据模型与边关系（DB Schema） | `claude-opus-4-7` | high | extended | 12k–18k | 25–35 min |
| 4.2  | XLK 节点种子数据（YAML + 灌库脚本） | `claude-sonnet-4-6` | medium | standard | 6k–10k | 12–18 min |
| 4.3  | Synthetic Basket 计算引擎 | `claude-opus-4-7` | medium | extended | 10k–15k | 20–28 min |
| 4.4  | Node Score 引擎（含 chain confirmation） | `claude-opus-4-7` | high | extended | 14k–20k | 30–40 min |
| 4.5  | Task 模型升级 + 旧任务自动迁移 | `claude-opus-4-7` | medium | extended | 10k–14k | 22–30 min |
| 4.6  | Node API 端点（树 / 持仓 / 走势对比） | `claude-opus-4-7` | medium | extended | 12k–16k | 25–32 min |
| 4.7  | 前端 Types + API Client + DrilldownView 骨架 | `claude-opus-4-7` | medium | extended | 10k–14k | 22–30 min |
| 4.8  | NodeTree 左栏组件（GICS / Chain lens） | `claude-sonnet-4-6` | medium | standard | 8k–12k | 18–25 min |
| 4.9  | Center 中栏（Trend / Matrix / Holdings / DataSource） | `claude-sonnet-4-6` | high | standard | 14k–20k | 30–40 min |
| 4.10 | NodeDetailPanel 右栏组件 | `claude-sonnet-4-6` | medium | standard | 8k–12k | 18–25 min |
| 4.11 | TaskDetail 集成 + CreateTaskModal node-first 改造 | `claude-sonnet-4-6` | medium | extended | 10k–14k | 22–30 min |

**为什么这样分配？**

- **Opus + extended thinking**：4.1/4.3/4.4/4.5/4.6/4.7 涉及跨层契约（DB → calculator → API → frontend types），需要全局一致性推理
- **Opus + medium effort**：4.4 是计算引擎核心，需要权衡数学公式与现有 ETFScoreCalculator 的兼容；4.5 涉及数据迁移
- **Sonnet + standard**：4.8/4.9/4.10 是依据 README 的高保真 spec 落实 React 组件，规格已穷举，重在执行精度而非创造性
- **Haiku 不推荐用于本 Phase**：所有任务都涉及多文件改动 + 现有约束推理，Haiku 在跨文件一致性上风险较高

### 0.5 执行指令模板（自动化 prompt）

把下面这段作为系统/用户消息发送给 Opus/Sonnet 时，模型会按本文档规范执行：

```
你是 momentum_analysis 项目的高级工程师。请严格按照
/Users/bin/Github/momentum_analysis/Phase4_Drilldown_Upgrade.md 中的
**Task <编号>** 执行升级，遵守以下硬性约束：

【范围隔离】
1. 只动 Task 中明确列出的"需要修改/新建的文件"，不要顺手 refactor 其他文件
2. 本 Phase 只升级 task_type='drilldown'（板块下钻）的任务路径；
   严禁影响 task_type='rotation' / 'momentum' 的任何代码路径、API 行为、
   UI 渲染与数据库读写。详见 0.6 节"Rotation 隔离清单"
3. 任何函数体内若存在 task.type 分支判断，rotation/momentum 分支必须
   字节级保持原状（diff 上不应出现非空格变更）

【向后兼容 & 数据安全】
4. 数据库变更只走 Base.metadata.create_all + 列补齐函数，禁止使用 alembic
5. 保持向后兼容：旧函数标 @deprecated 注释 + 保留实现，不删除、不改签名
6. 旧字段（Task.sector / Task.etfs / ETF.parent_sector）只读不删；
   新增字段必须 nullable=True 或带 default

【代码质量】
遵守项目 CLAUDE.md"编码规范"章节的全部规则
（type hints、docstring、函数长度、注释规范、扩展性设计等）。

【交付门槛】
7. 前端组件必须命中 design_handoff_drilldown/README.md 的像素级 spec
   （颜色、padding、border-radius、font-size 一一对照）
8. 修改完成后必须执行：
   a) `pytest backend/tests/ -v`（全部通过）
   b) 0.8 节的"Rotation 回归验证清单"（逐项打勾）
   c) `npm run typecheck && npm run lint`（前端 Task）

【文档与风格】
9. 不要新增 markdown 文档（CLAUDE.md / *.md），除非 Task 明确要求
10. 不要使用 emoji（除非 Task 明确要求）

执行完成后用以下格式总结：
- 修改文件清单（每个文件 1 行说明 + 行数变化 +N -M）
- 新增依赖（如有）
- 测试结果（pytest 输出关键行 + 0.8 回归验证逐项打勾）
- Rotation 影响面自检（说明为什么 rotation 路径未受影响）
- 已知风险与下一步建议
```

---

### 0.6 Rotation 隔离清单（约束 1 落地）

> 以下文件/路径/行为在 Phase 4 全程**只读不写**。如某 Task 必须修改其中文件，
> 必须用 `if task.type == "drilldown"` 短路保护，并在 PR 描述中举证 rotation 分支未受影响。

#### B.6.1 后端禁止触碰清单

| 文件 / 路径 | 保护范围 | 例外（必须短路保护）|
|---|---|---|
| `backend/app/api/tasks.py` | rotation 任务的创建/校验/刷新分支 | 仅可在 `_validate_task_etfs` 内部加 `if task.type == "drilldown" and root_node:` 旁路 |
| `backend/app/services/calculators/etf_score.py` | `ETFScoreCalculator.calculate_score` 主流程 | 仅复用其子函数（rank_percentile_normalize / trend / breadth / options），不改主流程 |
| `backend/app/services/refresh_*.py` rotation 路径 | rotation 的 ETF 持仓刷新逻辑 | 节点级刷新走**新文件** `node_refresh_service.py`，不挤占旧路径 |
| `backend/app/api/etfs.py:/sectors`, `/industries` | rotation 任务依赖的旧 ETF 列表接口 | 新接口 `/nodes/...` 独立暴露，旧接口签名零改动 |
| 数据库表：`tasks.sector`, `tasks.etfs`, `etfs.parent_sector` | 列定义不可改 | 仅追加新列（含 default），不修改/删除既有列 |

#### B.6.2 前端禁止触碰清单

| 文件 | 保护范围 | 例外 |
|---|---|---|
| `frontend/src/components/task/ETFDetailCard.tsx` | rotation/momentum 渲染卡片 | **完全不动** |
| `frontend/src/components/task/RelativeTrendChart.tsx` | rotation 走势图 | **完全不动** |
| `frontend/src/components/task/TaskDetail.tsx` | rotation/momentum 渲染分支 | 仅在 drilldown 分支前加 `if (task.type === 'drilldown') return <DrilldownView .../>;` 提前返回，**rotation/momentum 后续 JSX 字节级保持原状** |
| `frontend/src/components/modal/CreateTaskModal.tsx` | rotation 类型的 step 1/2/3 | 仅改 drilldown 分支的 step 3；rotation 分支的 INDUSTRY_ETFS 引用保留至 Task 4.11 末尾才删除（且只在确认 drilldown 改造完成后） |
| `frontend/src/api/tasks.ts` rotation/momentum 端点 | 现有 API client | 节点接口走**新文件** `frontend/src/api/nodes.ts` |

#### B.6.3 数据行为不变量（合约式）

完成 Phase 4 后必须满足以下 SQL/HTTP 不变量：

```sql
-- I1: rotation 任务行无新增字段写入
SELECT COUNT(*) FROM tasks WHERE type='rotation' AND root_node IS NOT NULL;
-- 必须 = 0

-- I2: 老 drilldown 任务的旧字段未被破坏
SELECT COUNT(*) FROM tasks WHERE type='drilldown' AND (sector IS NULL OR etfs IS NULL);
-- 必须 = 升级前的同查询结果（全 0 或同样的历史 NULL 数）
```

```bash
# I3: rotation 任务的 GET 返回体与升级前 byte-equal
diff <(curl -s pre/api/tasks/{rotation_id}) <(curl -s post/api/tasks/{rotation_id})
# 必须无 diff（除非 updated_at 字段）
```

---

### 0.7 软件工程规范

> 已并入项目 [`CLAUDE.md`](CLAUDE.md) 的"编码规范"章节，适用于本项目所有 Phase。
> 执行任何 Task 前请先阅读 `CLAUDE.md`。

---

### 0.8 Rotation 回归验证清单（每个 Task 完成时执行）

> 任何 Task 修改完成后，提交前必须逐项打勾。任一未通过禁止合并。

```
后端回归
[ ] R1. pytest backend/tests/ -v 全部通过
[ ] R2. 创建 rotation 任务（POST /api/tasks type=rotation）成功，
        返回结构与升级前完全一致（用 jq 对比 keys）
[ ] R3. GET /api/tasks?type=rotation 列表的 JSON 与升级前 byte-equal
[ ] R4. 触发 rotation 任务的 refresh，刷新行为与升级前一致
        （ETF 数量、related_etf_symbols 去重逻辑未变）
[ ] R5. ETFScoreCalculator.calculate_score(rotation_etf) 返回数值
        与 git stash 版本一致（用同一份测试 fixture 对比）

前端回归
[ ] R6. 创建 rotation 任务的 Modal 三步流程 UI 完全未变
[ ] R7. 进入 rotation 任务详情页，渲染的 ETFDetailCard 数量、
        顺序、内容与升级前一致（视觉对比截图）
[ ] R8. RelativeTrendChart 在 rotation 详情页正常渲染
[ ] R9. AddTaskETFsModal 在 rotation 任务上的"添加 ETF" tab 行为不变

数据完整性
[ ] R10. SELECT COUNT(*) FROM tasks WHERE type='rotation' AND root_node IS NOT NULL  → 0
[ ] R11. SELECT * FROM tasks WHERE type='rotation' 的所有列，升级前后 SHA256 一致
         （除 updated_at）
```

---

# Task 4.1 — Node 数据模型与边关系（DB Schema）

> **依赖**：无（Phase 4 起点）
> **模型配置**：`claude-opus-4-7` · effort=high · thinking=extended

## 背景

当前 `backend/app/models/database.py` 中：
- `ETF` 表只有 `type ∈ {sector, industry}` 与单父 `parent_sector` 字段
- `Task` 只有 `sector + etfs[]`
- 没有"节点"、"边"、"proxy"、"synthetic basket"等概念

需求文档第 7 节"最低风险路径"明确要求：**先加节点层，不要先删 ETF 层**。本 Task 即建立节点层底座，与 ETF 表并行存在。

## 目标

新增 5 张表，全部使用 `Base.metadata.create_all` 自动建表（保持项目模式），并提供列补齐函数（兼容老 SQLite 库）：

1. `analytic_nodes` — 节点本体（GICS / chain / leaf / evidence）
2. `node_edges` — 节点之间的关系边（多种边类型）
3. `node_proxies` — 节点的 ETF proxy 映射（primary / secondary）
4. `synthetic_basket_definitions` — 合成篮定义（成分股 + 权重策略）
5. `node_price_series` — 合成节点的价格序列缓存（避免每次请求重算）

## 需要修改/新建的文件

- `backend/app/models/database.py` — 新增 5 个 SQLAlchemy 模型 + 1 个枚举类 + 列补齐函数
- `backend/tests/test_node_models.py` — **新建** 单元测试（建表 / 关系 / unique 约束）

## 具体要求

### 1. 枚举与表结构

在 `database.py` 的 `class TaskType` 之后新增：

```python
class NodeType(enum.Enum):
    """节点的语义类型"""
    GICS = "gics"            # GICS 分类节点 (XLK / 半导体 / 软件)
    CHAIN = "chain"          # 产业链节点 (设备 / 计算 / 连接)
    LEAF = "leaf"            # 介质叶子节点 (光 / 铜)
    EVIDENCE = "evidence"    # 证据/主题节点 (云计算 / 网络安全)


class NodeEdgeType(enum.Enum):
    """节点之间关系的类型"""
    CLASSIFICATION_PARENT = "classification_parent"  # GICS 父子
    CHAIN_PARENT = "chain_parent"                    # 产业链父子
    PROXY_OF = "proxy_of"                            # ETF 是节点的 proxy
    CORROBORATES = "corroborates"                    # 主题节点用于确认主节点
    OVERLAPS_WITH = "overlaps_with"                  # 成分重叠
    DRIVES = "drives"                                # 上游驱动下游
    DEPENDS_ON = "depends_on"                        # 下游依赖上游


class NodeProxyRole(enum.Enum):
    """proxy 的角色"""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    EXTENSION = "extension"   # chain extension（跨出父 ETF 成分）


class AnalyticNode(Base):
    """研究节点 - 板块下钻的一等分析对象"""
    __tablename__ = "analytic_nodes"

    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String(64), unique=True, nullable=False, index=True)
    # node_id 是业务主键, e.g. 'XLK', 'semi', 'semi-compute', 'conn-optical'
    label = Column(String(64), nullable=False)        # '半导体'
    sublabel = Column(String(128), nullable=True)     # 'Semiconductors & Equip.'
    node_type = Column(String(20), nullable=False, index=True)  # NodeType value
    level = Column(Integer, default=0, index=True)    # 0=root, 1=sub-sector, 2=segment, 3=leaf
    representation_confidence = Column(Float, default=1.0)  # 0-1, synthetic 节点 < 1
    description = Column(Text, nullable=True)
    extra = Column(JSON, default=dict)  # 自由扩展: tags, oem_metadata, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NodeEdge(Base):
    """节点之间的关系边"""
    __tablename__ = "node_edges"

    id = Column(Integer, primary_key=True)
    src_node_id = Column(String(64), ForeignKey('analytic_nodes.node_id'), nullable=False, index=True)
    dst_node_id = Column(String(64), ForeignKey('analytic_nodes.node_id'), nullable=False, index=True)
    edge_type = Column(String(32), nullable=False, index=True)  # NodeEdgeType value
    weight = Column(Float, default=1.0)  # 边权重 (用于 chain confirmation 的加权)
    extra = Column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint('src_node_id', 'dst_node_id', 'edge_type', name='uix_node_edge_triple'),
    )


class NodeProxy(Base):
    """节点的 ETF proxy 映射"""
    __tablename__ = "node_proxies"

    id = Column(Integer, primary_key=True)
    node_id = Column(String(64), ForeignKey('analytic_nodes.node_id'), nullable=False, index=True)
    etf_symbol = Column(String(20), nullable=False, index=True)  # 'SOXX' / 'SMH' / 'IGV'
    role = Column(String(20), nullable=False, default='primary')  # NodeProxyRole value
    purity = Column(Float, default=1.0)   # ETF 表达此 node 的纯度 (0-1)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('node_id', 'etf_symbol', 'role', name='uix_node_proxy_node_etf_role'),
    )


class SyntheticBasketDefinition(Base):
    """合成篮成分定义 - 节点没有干净 ETF proxy 时使用"""
    __tablename__ = "synthetic_basket_definitions"

    id = Column(Integer, primary_key=True)
    node_id = Column(String(64), ForeignKey('analytic_nodes.node_id'), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    target_weight = Column(Float, nullable=True)
    # null = 等权或动态权重；非 null = 显式目标权重
    weighting_strategy = Column(String(20), default='equal')
    # 'equal' / 'mcap' / 'parent_etf_weight' / 'fixed'
    chain_extension = Column(Boolean, default=False)
    # True 表示这只票跨出了父 ETF 的成分范围（光/铜叶子常见）
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('node_id', 'ticker', name='uix_basket_node_ticker'),
    )


class NodePriceSeries(Base):
    """合成节点的价格序列缓存
    （ETF proxy 节点直接读 PriceHistory，无需缓存；只有 synthetic 才落这里）"""
    __tablename__ = "node_price_series"

    id = Column(Integer, primary_key=True)
    node_id = Column(String(64), ForeignKey('analytic_nodes.node_id'), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    close = Column(Float, nullable=False)        # 合成"价格"(归一化基准 100 起算)
    constituents_count = Column(Integer, default=0)
    coverage_ratio = Column(Float, default=1.0)  # 当日有数据的成分股比例
    weighting_strategy = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('node_id', 'date', name='uix_node_price_series_date'),
    )
```

### 2. 列补齐函数

在 `init_db()` 中追加调用 `_ensure_node_tables_indexes()`，并实现该函数（仅 sqlite，给 `analytic_nodes.node_type` / `node_edges.edge_type` / `node_proxies.etf_symbol` 建索引）。

### 3. 单元测试 `backend/tests/test_node_models.py`

至少覆盖：
- 建表后 5 张表都存在
- `AnalyticNode.node_id` 唯一
- `NodeEdge` 三元组 `(src, dst, type)` 唯一
- 一个节点可以有 primary + secondary 两个 proxy（test 用例：`semi` 节点配 SOXX=primary, SMH=secondary）
- `SyntheticBasketDefinition.chain_extension=True` 可正确插入
- `NodePriceSeries` `(node_id, date)` 唯一

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- **不修改** `ETF` / `Task` 现有表结构（4.5 才动）
- 所有新表的字段类型与现有表一致（`String(20)` for symbols / `Date` for date / `Float` for numeric）
- 在 `database.py` 的导入区不引入新依赖
- 所有现有 `backend/tests/` 测试必须通过

## 验证标准

- `python -c "from backend.app.models.database import init_db; init_db()"` 无报错
- `sqlite3 <db_path> ".schema analytic_nodes"` 输出含上述所有列
- `pytest backend/tests/test_node_models.py -v` 全部通过
- `pytest backend/tests/ -v` 不出现回归

---

# Task 4.2 — XLK 节点种子数据 + 灌库脚本

> **依赖**：Task 4.1
> **模型配置**：`claude-sonnet-4-6` · effort=medium · thinking=standard

## 背景

需求文档第 4 节给出了 XLK 完整节点结构。这个结构作为"代码外可维护的 taxonomy 配置"是合适的——按需求文档第 7 节第五步，"先做一份可维护的人工 taxonomy 配置，再逐步自动化"。

## 目标

1. 创建 `backend/data/node_taxonomy/xlk.yaml` — XLK 节点种子配置（GICS + chain + leaf + evidence + proxy + basket）
2. 创建 `backend/app/services/node_taxonomy_loader.py` — 解析 YAML 并写入 4.1 的 5 张表
3. 提供 CLI 入口 `python -m backend.app.cli load-node-taxonomy <yaml_path>`
4. 幂等：重复执行不产生重复行（按 node_id / 三元组 upsert）

## 需要修改/新建的文件

- `backend/data/node_taxonomy/xlk.yaml` — **新建**
- `backend/app/services/node_taxonomy_loader.py` — **新建**
- `backend/app/cli.py` — 增加 `load-node-taxonomy` 子命令
- `backend/tests/test_node_taxonomy_loader.py` — **新建**

## 具体要求

### 1. YAML 结构（必须严格按下面布局，loader 也按此约定解析）

```yaml
# backend/data/node_taxonomy/xlk.yaml
nodes:
  - node_id: XLK
    label: XLK
    sublabel: Technology Select Sector
    node_type: gics
    level: 0
    representation_confidence: 1.0

  - node_id: semi
    label: 半导体
    sublabel: Semiconductors & Equip.
    node_type: gics
    level: 1
    representation_confidence: 1.0

  - node_id: soft
    label: 软件
    sublabel: Application Software
    node_type: gics
    level: 1
    representation_confidence: 1.0

  - node_id: hw
    label: 硬件
    sublabel: Tech Hardware & Equipment
    node_type: gics
    level: 1
    representation_confidence: 0.7   # synthetic aggregate, 标记纯度

  - node_id: semi-equip
    label: 设备
    sublabel: Semiconductor Equipment
    node_type: chain
    level: 2
    representation_confidence: 0.85

  - node_id: semi-compute
    label: 计算
    sublabel: AI Compute / GPU
    node_type: chain
    level: 2
    representation_confidence: 0.8

  - node_id: semi-mem
    label: 存储
    sublabel: Memory / DRAM
    node_type: chain
    level: 2
    representation_confidence: 0.85

  - node_id: semi-conn
    label: 连接
    sublabel: High-Speed Interconnect
    node_type: chain
    level: 2
    representation_confidence: 0.7

  - node_id: conn-optical
    label: 光互联
    sublabel: Optical Transceivers
    node_type: leaf
    level: 3
    representation_confidence: 0.65

  - node_id: conn-copper
    label: 铜缆
    sublabel: Active Copper / Connectors
    node_type: leaf
    level: 3
    representation_confidence: 0.65

  - node_id: soft-cloud
    label: 云计算
    sublabel: Cloud Platforms
    node_type: evidence
    level: 2
    representation_confidence: 0.7

  - node_id: soft-cyber
    label: 网络安全
    sublabel: Cybersecurity
    node_type: evidence
    level: 2
    representation_confidence: 0.7

edges:
  # GICS 分类
  - {src: XLK, dst: semi, type: classification_parent}
  - {src: XLK, dst: soft, type: classification_parent}
  - {src: XLK, dst: hw,   type: classification_parent}

  # 产业链
  - {src: semi, dst: semi-equip,    type: chain_parent}
  - {src: semi, dst: semi-compute,  type: chain_parent}
  - {src: semi, dst: semi-mem,      type: chain_parent}
  - {src: semi, dst: semi-conn,     type: chain_parent}
  - {src: semi-conn, dst: conn-optical, type: chain_parent}
  - {src: semi-conn, dst: conn-copper,  type: chain_parent}

  # 证据节点 (corroborates 软件)
  - {src: soft-cloud, dst: soft, type: corroborates, weight: 0.6}
  - {src: soft-cyber, dst: soft, type: corroborates, weight: 0.4}

  # 上下游驱动 (设备/连接 驱动 计算)
  - {src: semi-equip,   dst: semi-compute, type: drives, weight: 0.5}
  - {src: semi-conn,    dst: semi-compute, type: drives, weight: 0.5}
  - {src: semi-compute, dst: semi-equip,   type: depends_on, weight: 0.5}
  - {src: semi-compute, dst: semi-conn,    type: depends_on, weight: 0.5}

proxies:
  - {node_id: XLK,         etf: XLK,  role: primary,    purity: 1.0}
  - {node_id: semi,        etf: SOXX, role: primary,    purity: 0.95}
  - {node_id: semi,        etf: SMH,  role: secondary,  purity: 0.85}
  - {node_id: soft,        etf: IGV,  role: primary,    purity: 0.9}
  - {node_id: soft-cloud,  etf: SKYY, role: primary,    purity: 0.75}
  - {node_id: soft-cyber,  etf: HACK, role: primary,    purity: 0.8}

baskets:
  # 硬件 — 父 ETF 内聚合
  - {node_id: hw, ticker: AAPL, weighting_strategy: parent_etf_weight, chain_extension: false}
  - {node_id: hw, ticker: HPQ,  weighting_strategy: parent_etf_weight, chain_extension: false}
  - {node_id: hw, ticker: DELL, weighting_strategy: parent_etf_weight, chain_extension: false}
  - {node_id: hw, ticker: NTAP, weighting_strategy: parent_etf_weight, chain_extension: false}
  - {node_id: hw, ticker: STX,  weighting_strategy: parent_etf_weight, chain_extension: false}

  # 设备
  - {node_id: semi-equip, ticker: AMAT, weighting_strategy: equal}
  - {node_id: semi-equip, ticker: LRCX, weighting_strategy: equal}
  - {node_id: semi-equip, ticker: KLAC, weighting_strategy: equal}
  - {node_id: semi-equip, ticker: ASML, weighting_strategy: equal}
  - {node_id: semi-equip, ticker: TER,  weighting_strategy: equal}

  # 计算
  - {node_id: semi-compute, ticker: NVDA, weighting_strategy: mcap}
  - {node_id: semi-compute, ticker: AMD,  weighting_strategy: mcap}
  - {node_id: semi-compute, ticker: AVGO, weighting_strategy: mcap}

  # 存储
  - {node_id: semi-mem, ticker: MU,   weighting_strategy: mcap}
  - {node_id: semi-mem, ticker: WDC,  weighting_strategy: mcap}
  - {node_id: semi-mem, ticker: STX,  weighting_strategy: mcap}

  # 连接
  - {node_id: semi-conn, ticker: ANET, weighting_strategy: mcap}
  - {node_id: semi-conn, ticker: CRDO, weighting_strategy: mcap}
  - {node_id: semi-conn, ticker: APH,  weighting_strategy: mcap}
  - {node_id: semi-conn, ticker: MTSI, weighting_strategy: mcap}
  - {node_id: semi-conn, ticker: LITE, weighting_strategy: mcap}

  # 光（chain extension：可能跨出 XLK 成分）
  - {node_id: conn-optical, ticker: CIEN, weighting_strategy: equal, chain_extension: true}
  - {node_id: conn-optical, ticker: LITE, weighting_strategy: equal, chain_extension: true}
  - {node_id: conn-optical, ticker: COHR, weighting_strategy: equal, chain_extension: true}
  - {node_id: conn-optical, ticker: AAOI, weighting_strategy: equal, chain_extension: true}

  # 铜
  - {node_id: conn-copper, ticker: CRDO, weighting_strategy: equal, chain_extension: true}
  - {node_id: conn-copper, ticker: APH,  weighting_strategy: equal}
  - {node_id: conn-copper, ticker: TEL,  weighting_strategy: equal}
  - {node_id: conn-copper, ticker: MTSI, weighting_strategy: equal}
```

### 2. Loader 实现

```python
# backend/app/services/node_taxonomy_loader.py
import yaml
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.database import (
    AnalyticNode, NodeEdge, NodeProxy, SyntheticBasketDefinition, SessionLocal
)

def load_taxonomy(yaml_path: Path, db: Session | None = None) -> dict[str, int]:
    """从 YAML 加载节点 taxonomy 到数据库 (幂等 upsert)。

    Args:
        yaml_path: YAML 文件路径
        db: SQLAlchemy session, None 时自动新建并提交

    Returns:
        统计 dict: {nodes, edges, proxies, baskets} 的实际写入/更新条数
    """
    # 实现要点：
    # 1. yaml.safe_load 读取
    # 2. 对每张表按业务主键 upsert（不重复）：
    #    - AnalyticNode 按 node_id
    #    - NodeEdge 按 (src, dst, type)
    #    - NodeProxy 按 (node_id, etf, role)
    #    - SyntheticBasketDefinition 按 (node_id, ticker)
    # 3. 校验 edges 中引用的 src/dst 都已在 nodes 中存在，否则抛 ValueError
    # 4. 校验 baskets 中引用的 node_id 已存在
    # 5. 校验 proxies.etf 在 ETF 表存在（可选警告，不强制阻断）
    # 6. 全部写入后 commit
    ...
```

### 3. CLI 集成

在 `backend/app/cli.py` 中追加 `load-node-taxonomy` 子命令：

```python
# 调用方式: python -m backend.app.cli load-node-taxonomy backend/data/node_taxonomy/xlk.yaml
```

### 4. 测试

`test_node_taxonomy_loader.py` 至少覆盖：
- 完整加载 xlk.yaml 后 13 个节点 / N 条边 / 6 个 proxy / N 条 basket 写入
- 重复加载相同 YAML，行数不变（幂等）
- 修改 YAML 中某节点 label，重新加载后 DB 中该节点 label 已更新
- YAML 中 edge 引用了不存在的 node → 抛 `ValueError`

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 不引入新的运行时依赖（项目已有 `pyyaml` 或允许添加 `pyyaml>=6.0` 到 `requirements.txt`，需在执行前确认）
- 所有写入路径使用 `db.flush()`，commit 在最外层做一次

## 验证标准

- `python -m backend.app.cli load-node-taxonomy backend/data/node_taxonomy/xlk.yaml` 输出 `{"nodes": 13, "edges": 13, "proxies": 6, "baskets": 26+}` 类似汇总
- 二次运行不产生新行
- `SELECT * FROM node_proxies WHERE node_id='semi'` 返回 2 行（SOXX primary + SMH secondary）

---

# Task 4.3 — Synthetic Basket 计算引擎

> **依赖**：Task 4.1, 4.2
> **模型配置**：`claude-opus-4-7` · effort=medium · thinking=extended

## 背景

需求文档第 4 节定义了多个 synthetic basket 节点（硬件 / 设备 / 计算 / 存储 / 连接 / 光 / 铜）。这些节点没有 ETF proxy，必须从成分股价格序列合成出节点级"价格 / 收益 / 广度"序列，才能复用 4.4 的 Node Score 引擎。

## 目标

1. 实现 `compute_basket_price_series(node_id, db)` — 从 `SyntheticBasketDefinition` + `PriceHistory` 合成节点日频价格序列，写入 `NodePriceSeries`
2. 支持 3 种权重策略：`equal` / `mcap` / `parent_etf_weight`
3. 计算 `representation_confidence`（覆盖率 × purity 加权）
4. 提供 `get_node_holdings(node_id, db)` — 返回节点的成分股清单（ETF proxy 节点走 ETFHolding，synthetic 节点走 SyntheticBasketDefinition）

## 需要修改/新建的文件

- `backend/app/services/calculators/node_basket.py` — **新建**
- `backend/app/services/calculators/__init__.py` — 导出
- `backend/tests/test_node_basket.py` — **新建**

## 具体要求

### 1. 主接口

```python
# backend/app/services/calculators/node_basket.py

from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
import pandas as pd
import numpy as np


@dataclass
class BasketComputeResult:
    node_id: str
    rows_written: int           # NodePriceSeries 中新写入的天数
    coverage_avg: float         # 全期平均成分覆盖率 (0-1)
    representation_confidence: float  # 节点 representation_confidence × coverage_avg
    last_date: Optional[date]
    error: Optional[str] = None


def compute_basket_price_series(
    node_id: str,
    db: Session,
    *,
    base_value: float = 100.0,
    min_constituents: int = 2,
) -> BasketComputeResult:
    """合成 synthetic 节点的日频"价格"序列并写入 NodePriceSeries。

    算法:
    1. 读取节点的 SyntheticBasketDefinition (含 weighting_strategy / target_weight)
    2. 对每个 ticker 读取 PriceHistory (close)
    3. 对齐日历: 取所有 ticker 的交易日交集（或 union + ffill 由策略决定）
    4. 按权重策略计算每日加权收益:
       - equal: 等权
       - mcap: 用 finviz 的 market_cap (ImportedData) 或 fallback 到等权
       - parent_etf_weight: 从 ETFHolding 拿父 ETF 权重 (父 ETF = 节点的 GICS 父节点的 primary proxy)
       - fixed: 用 SyntheticBasketDefinition.target_weight
    5. 累乘日频收益得到合成"价格"(从 base_value 起算)
    6. 同时记录每天的 constituents_count / coverage_ratio
    7. 写入 NodePriceSeries (按 (node_id, date) upsert)

    Args:
        node_id: 节点业务主键
        db: SQLAlchemy session
        base_value: 起始基准价格 (默认 100)
        min_constituents: 最少需要 N 个成分股有数据才计入当日 (否则跳过)

    Returns:
        BasketComputeResult
    """
    ...


def get_node_holdings(node_id: str, db: Session) -> List[Dict[str, Any]]:
    """获取节点的成分股清单 (统一接口)。

    - ETF proxy 节点: 从 ETFHolding 取最新 data_date 的 holdings
    - Synthetic 节点: 从 SyntheticBasketDefinition + 实时计算出当前权重

    Returns:
        [
          {
            'ticker': str,
            'weight': float,           # 0-100
            'name': Optional[str],
            'is_chain_extension': bool,
            'weighting_strategy': str,
          },
          ...
        ]
        按 weight 降序
    """
    ...


def get_node_proxy_etf(node_id: str, db: Session) -> Optional[str]:
    """返回节点的 primary proxy ETF symbol；synthetic 节点返回 None。"""
    ...


def is_synthetic_node(node_id: str, db: Session) -> bool:
    """判断节点是否为 synthetic（没有 primary ETF proxy 且有 basket 定义）。"""
    ...
```

### 2. 权重策略实现要点

**equal**：每日 `weight_i = 1/N`（N = 当日有数据的成分数）

**mcap**：
- 从 `ImportedData` 读 `source='finviz'` 最新 `data['market_cap']`
- 缺失时退化为 equal（在 result.coverage_ratio 中记录 N_mcap_available / N_total 作为信号）

**parent_etf_weight**：
- 从 `NodeEdge` 找到节点的 `classification_parent` (XLK)
- 取该父节点的 primary proxy (XLK 的 ETFHolding) 中匹配 ticker 的权重
- 对篮内成分按"父 ETF 中权重"归一化（让篮内权重和 = 1）
- 如果某 ticker 不在父 ETF 持仓里 → fallback equal（且在 chain_extension=True 时不强制要求）

### 3. 缓存策略

- `NodePriceSeries` 已存在 `(node_id, date)` 的行 → 跳过；
- 提供 `force_recompute=True` 选项（默认 False）；
- 调用方应该在 ETFHolding 刷新之后触发 basket 重算（4.6 的 API 层会管理）

### 4. 测试

`test_node_basket.py` 至少覆盖：
- mock `PriceHistory` 给 NVDA/AMD/AVGO 提供 60 天数据
- 计算 `semi-compute` 节点（mcap 策略）→ 60 行 NodePriceSeries 写入
- 把 AVGO 在第 30 天数据删除 → coverage_ratio[30] < 1.0，但仍输出（因为 ≥ min_constituents）
- 把 AMD 第 30 天也删 → 该天跳过（仅 NVDA < min_constituents=2）
- equal 策略下，3 只成分日收益 +1/-1/+0 → 节点日收益 0
- `get_node_holdings('XLK')` 返回 ETF holdings；`get_node_holdings('semi-compute')` 返回 basket
- `is_synthetic_node('semi')` = False（有 SOXX primary proxy）
- `is_synthetic_node('hw')` = True

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 不修改 `etf_score.py` / `momentum.py` / `technical.py`（4.4 才动）
- 价格序列对齐用 `pandas.DataFrame.reindex(business_days, method=None)`，不要 ffill 跨多日
- 所有数值运算前用 `np.nan_to_num` 清洗或显式 dropna，避免污染累乘

## 验证标准

- `pytest backend/tests/test_node_basket.py -v` 全部通过
- 给 `semi-compute` 灌 60 天数据后调用 `compute_basket_price_series` 返回 `rows_written=60, coverage_avg≥0.95`

---

# Task 4.4 — Node Score 引擎

> **依赖**：Task 4.1, 4.2, 4.3
> **模型配置**：`claude-opus-4-7` · effort=high · thinking=extended

## 背景

需求文档第 6 节明确：**保留 ETFScoreCalculator 主权重（rel_mom 0.45 / trend 0.25 / breadth 0.20 / options 0.10），新增两个 overlay**：
1. `representation_confidence` — 节点被 proxy/synthetic 表达得有多纯
2. `chain_confirmation` — 上下游是否共振（基于 NodeEdge 的 drives/depends_on/corroborates）

## 目标

1. 新建 `node_score.py`，复用 `etf_score.py` 的横截面标准化与子分数计算
2. 实现 `calculate_node_score(node_id, db, ...)` — 单节点评分
3. 实现 `batch_calculate_node_scores(node_ids, db, ...)` — 批量带横截面标准化
4. 实现 `compute_chain_confirmation(node_id, sibling_scores, db)` — 上下游共振修正
5. 输出"推荐下一个 drill 节点"建议

## 需要修改/新建的文件

- `backend/app/services/calculators/node_score.py` — **新建**
- `backend/app/services/calculators/__init__.py` — 导出
- `backend/tests/test_node_score.py` — **新建**

## 具体要求

### 1. 主接口

```python
@dataclass
class NodeScoreResult:
    node_id: str
    label: str
    level: int
    proxy_type: str               # 'etf' | 'synthetic'
    proxy_symbol: Optional[str]   # primary ETF symbol or None
    proxy_label: Optional[str]    # synthetic 时是 'NVDA + AMD + AVGO' 这种描述
    total_score: float            # 最终分 (0-100, 经 representation_confidence × chain_confirmation 修正后)
    base_score: float             # 修正前的"市场强度"分
    representation_confidence: float
    chain_confirmation: float     # 0-1，1=上下游全部共振
    score_vs_parent: Optional[float]  # 与父节点的分差（父节点 None 时为 None）
    contribution: Optional[float]     # 对父节点的贡献占比 (0-100)
    rel_strength: Optional[float]     # vs SPY 的 RS_20D_change
    breadth: Optional[float]          # %above_50ma
    delta3d: Optional[float]
    delta5d: Optional[float]
    raw_subscores: Dict[str, float]   # rel_mom / trend / breadth / options 标准化前
    norm_subscores: Dict[str, float]  # 标准化后 0-100
    notes: List[str]                  # 数据缺失/置信度告警等
    recommended_drill: Optional[str]  # 推荐下一个 drill 的子节点 node_id


def batch_calculate_node_scores(
    node_ids: List[str],
    db: Session,
    *,
    benchmark_symbol: str = 'SPY',
    label_tz: str = 'beijing',
) -> List[NodeScoreResult]:
    """批量计算节点评分（同一层节点同批次做横截面标准化）。

    Pipeline:
    1. 对每个 node_id, 拿到节点的"价格序列"
       - ETF proxy 节点: 直接从 PriceHistory 读 etf_symbol
       - Synthetic 节点: 调 compute_basket_price_series 确保已缓存, 然后从 NodePriceSeries 读
    2. 调 calculate_relative_strength + calculate_rel_mom (复用 momentum.py)
    3. 调 ETFScoreCalculator 的子函数计算 trend / breadth / options
       - synthetic 节点的 breadth 从 basket 成分实时计算 %above_50ma
       - synthetic 节点的 options 用 basket 成分加权 IV 数据 (ImportedData / IVData)
    4. 收集所有节点的 raw 值，调 rank_percentile_normalize 横截面标准化
    5. base_score = 0.45*rel_mom_norm + 0.25*trend_norm + 0.20*breadth_norm + 0.10*options_norm
    6. chain_confirmation = compute_chain_confirmation(...)
    7. total_score = base_score × representation_confidence × (0.7 + 0.3 * chain_confirmation)
       - 这样 chain_confirmation = 0 时仍保留 70% 基础分; chain_confirmation = 1 时满分
    8. recommended_drill = 子节点中分数最高且 ≥ 父节点 + 5 分的那个; 否则 None

    Returns:
        List[NodeScoreResult] 按 total_score 降序
    """
    ...


def compute_chain_confirmation(
    node_id: str,
    other_node_scores: Dict[str, float],
    db: Session,
) -> float:
    """基于 NodeEdge 的 drives/depends_on/corroborates 计算上下游共振度。

    算法:
    - 取所有 src=node_id, type ∈ {drives, depends_on} 的边
    - 对每条边, 看 dst 节点的分数是否 ≥ 60 (节点已合格), 是 +1 × edge.weight
    - 同时取 dst=node_id, type=corroborates 的入边, dst 节点 ≥ 60 时 +0.5 × edge.weight
    - 归一化到 [0, 1]: confirmation = sum(matched) / sum(all_edge_weights)

    返回 0.0 ~ 1.0
    """
    ...
```

### 2. 与现有代码的复用

**强约束**：必须 import 并复用以下函数，不要重写：
- `from .momentum import MomentumCalculator` — 用 `calculate_relative_strength`, `calculate_rel_mom`
- `from .etf_score import rank_percentile_normalize, ETFScoreCalculator` — 用 trend/breadth/options 子函数与横截面标准化
- `from .node_basket import compute_basket_price_series, get_node_holdings, get_node_proxy_etf, is_synthetic_node`
- `from .technical import calculate_sma, calculate_returns`

### 3. 关键数学公式

**total_score**（最终分）：
```
total = base × representation_confidence × (0.7 + 0.3 × chain_confirmation)
```

**contribution**（对父节点的贡献，仅子节点有）：
- 取父节点的所有兄弟节点
- 每个子节点的"贡献量" = `total_score × node_weight_in_parent`
- node_weight_in_parent：
  - GICS 子节点：父 ETF 中该子节点 proxy 的官方权重（XLK→半导体的 SOXX 占 XLK 的~45%）
  - chain 子节点：合成篮成分的合计权重在父节点中的占比
- contribution = 该贡献量 / 所有兄弟贡献量之和 × 100

**recommended_drill** 规则：
- 当前节点的子节点中，total_score 最高 且 比当前节点高 ≥ 5 分 → 推荐它
- 没有满足条件的 → None

### 4. 测试

`test_node_score.py` 至少覆盖：
- 灌入 XLK + 3 个 GICS 子节点（半导体/软件/硬件）的 60 天价格 → batch_calculate_node_scores 返回按分降序
- semi 节点 base_score < 100 时，乘以 representation_confidence=0.95 后 total_score 应略低
- compute_chain_confirmation: 给 semi-compute 节点的 drives 边对端 (semi-equip / semi-conn) 都 ≥ 60 → confirmation = 1.0
- recommended_drill: 父节点 70 分，子节点 [85, 60, 55] → 推荐第一个；子节点 [72, 60, 55] → None
- 缺数据节点（NodePriceSeries < 30 天）→ NodeScoreResult.notes 中记录"数据不足"，不抛异常

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 节点 score 的"维度名"使用 4 个：`rel_mom / trend / breadth / options`（与 etf_score 一致）
- 不删 / 不改 `etf_score.py`、`momentum_pool.py`、`stock_score.py` 任何函数
- 横截面标准化的输入要求 `len(node_ids) >= 3`，否则跳过标准化（直接用 raw 值映射 0-100）
- 所有节点的 `delta3d / delta5d` 通过查询 `ScoreSnapshot` 表（symbol_type='node'）获取——所以本任务也要在 batch_calculate 末尾把当日分数写入 ScoreSnapshot

## 验证标准

- `pytest backend/tests/test_node_score.py -v` 全部通过
- 调用 `batch_calculate_node_scores(['XLK', 'semi', 'soft', 'hw'])` 返回 4 条结果，按 total_score 降序

---

# Task 4.5 — Task 模型升级 + 旧任务自动迁移

> **依赖**：Task 4.1
> **模型配置**：`claude-opus-4-7` · effort=medium · thinking=extended

## 背景

当前 `Task` 表只有 `sector + etfs[]`，无法表达"研究节点树 + 选中节点 + lens（GICS / 产业链）+ 证据节点 + 最大深度"。需求文档第 7 节第二步给出了升级字段。

## 目标

1. 给 `Task` 表新增 5 个字段（不破坏旧字段）
2. 写一个一次性迁移脚本：把所有现有 drilldown 任务转成 `root_node = sector` + `selected_nodes = etfs 对应的 node_id`
3. `tasks.py` 的 schemas / 校验 / 序列化全部支持新字段，同时向后兼容旧 API 调用

## 需要修改/新建的文件

- `backend/app/models/database.py` — `Task` 表加列 + 列补齐函数
- `backend/app/schemas/__init__.py` — `TaskCreate` / `TaskEtfsAdd` schema 加可选字段
- `backend/app/api/tasks.py` — 校验、`format_task_response`、`create_task`、`update_task` 支持新字段
- `backend/app/services/migrations.py` — **新建**：一次性迁移函数
- `backend/app/cli.py` — 增加 `migrate-drilldown-tasks` 子命令
- `backend/tests/test_task_migration.py` — **新建**

## 具体要求

### 1. Task 表新增字段

```python
class Task(Base):
    __tablename__ = "tasks"

    # ... 现有字段保留 ...

    # ===== Phase 4 新增 =====
    root_node = Column(String(64), nullable=True, index=True)
    # node_id, e.g. 'XLK'; 旧任务迁移时 = sector

    view_mode = Column(String(20), default='gics')
    # 'gics' / 'chain' / 'hybrid'

    selected_nodes = Column(JSON, default=list)
    # ['XLK', 'semi', 'soft', 'hw'] - 用户在树中选中的节点

    pinned_evidence_nodes = Column(JSON, default=list)
    # ['soft-cloud', 'soft-cyber'] - 钉住作为证据展示的节点

    max_depth = Column(Integer, default=3)
    # 树最大展示深度
```

记得在 `init_db` 的列补齐函数 `_ensure_tasks_node_fields_columns` 里给老库 ALTER TABLE ADD COLUMN。

### 2. 迁移函数

```python
# backend/app/services/migrations.py
from sqlalchemy.orm import Session
from app.models.database import Task, NodeProxy, AnalyticNode

def migrate_drilldown_tasks_to_node_first(db: Session, dry_run: bool = True) -> dict:
    """把现有 drilldown 任务从 sector + etfs[] 迁移到 root_node + selected_nodes。

    映射规则:
    - root_node = sector  (XLK / XLF / ...)
    - selected_nodes = 对每个 etfs 中的 ETF symbol, 反查 NodeProxy 找对应的 node_id;
      找不到的 ETF 保留在 selected_etfs_legacy 里, 在 task.extra 中记录
    - view_mode = 'gics' (默认)
    - max_depth = 3

    Args:
        db: session
        dry_run: True 时只打印计划不写库

    Returns:
        {"migrated": N, "skipped": M, "warnings": [...]}
    """
    ...
```

`Task` 表临时再加一个 `extra: JSON` 字段（如已存在跳过），用于装 legacy 兼容信息。

### 3. API 兼容

`tasks.py` 中：
- `format_task_response` 增加 `rootNode / viewMode / selectedNodes / pinnedEvidenceNodes / maxDepth` 五个 camelCase 字段
- `_validate_task_etfs` 中：
  - 当 `task.type == 'drilldown'` 且 `root_node` 已设置时：跳过现有"必须 industry + parent_sector 匹配"的强校验
  - 退化条件：旧任务（root_node 为空）继续走旧校验，保证向后兼容

### 4. CLI

```bash
python -m backend.app.cli migrate-drilldown-tasks --dry-run    # 看计划
python -m backend.app.cli migrate-drilldown-tasks --commit     # 真迁
```

### 5. 测试

`test_task_migration.py`：
- 准备 3 个旧 drilldown 任务（XLK + [SOXX, IGV, SKYY]）
- dry_run 输出 `{migrated: 3, skipped: 0}`，DB 不变
- `--commit` 后任务的 `root_node='XLK'`, `selected_nodes=['XLK', 'semi', 'soft', 'soft-cloud']`（按 NodeProxy 反查）
- 旧 API `POST /tasks` 不带 root_node 字段仍能创建任务（兼容）
- 新 API 带 root_node 字段创建任务，且不再强制 etfs 必须是 industry

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 不删除 `Task.sector / Task.etfs` 字段（4.10 之后视情况再清理）
- 迁移脚本必须可重入（已迁过的任务跳过）

## 验证标准

- 现有所有 drilldown 任务执行 `migrate-drilldown-tasks --commit` 后 `root_node` 全部填充
- `pytest backend/tests/test_task_migration.py -v` 通过
- 现有前端 `Tasks.tsx` 列表接口仍正常返回（无字段不存在错误）

---

# Task 4.6 — Node API 端点

> **依赖**：Task 4.1, 4.2, 4.3, 4.4, 4.5
> **模型配置**：`claude-opus-4-7` · effort=medium · thinking=extended

## 背景

前端需要 3 个新接口（参考 README "New API Endpoints"）：节点树、节点持仓、节点走势对比。这些接口的契约必须严格匹配 README 的 TypeScript 类型，否则前端集成会报错。

## 目标

新增 3 个 FastAPI 端点，挂在 `/api/tasks/{task_id}/...` 下：

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/tasks/{task_id}/nodes` | 返回任务的研究节点树（含每个节点的实时分数） |
| GET | `/api/tasks/{task_id}/nodes/{node_id}/holdings` | 节点的成分股清单 + 节点级 RS / 收益 / 评分 |
| GET | `/api/tasks/{task_id}/nodes/{node_id}/trend-comparison` | 节点 vs 父节点 vs SPY 走势 |

## 需要修改/新建的文件

- `backend/app/api/nodes.py` — **新建**（路由）
- `backend/app/main.py` — 注册路由：`app.include_router(nodes.router, prefix="/api/tasks", tags=["nodes"])`
- `backend/tests/test_nodes_api.py` — **新建**

## 具体要求

### 1. GET /api/tasks/{task_id}/nodes

**Query params**:
- `lens` ∈ `{gics, chain, hybrid}`（默认 `gics`，从 task.view_mode 兜底）

**响应**（严格匹配 README 的 `ResearchNode[]` ）：

```json
[
  {
    "id": "XLK",
    "label": "XLK",
    "sublabel": "Technology Select Sector",
    "level": 0,
    "proxy": "XLK",
    "proxyType": "etf",
    "proxyLabel": null,
    "score": 74.2,
    "scoreVsParent": null,
    "contribution": null,
    "relStrength": "+6.4%",
    "breadth": 68,
    "delta3d": 1.2,
    "delta5d": 2.8,
    "children": [
      { "id": "semi", ... },
      ...
    ]
  }
]
```

**实现要点**：
1. 加载 task，取 `root_node`（旧任务先调 `migrate_drilldown_tasks_to_node_first(dry_run=True)` 风格的 in-memory 转换）
2. 用 `NodeEdge` 构图：
   - `lens='gics'` → 仅 `classification_parent` 边
   - `lens='chain'` → 仅 `chain_parent` 边
   - `lens='hybrid'` → 两者并集
3. 从 `root_node` 做深度遍历，深度限制 = `task.max_depth`
4. 对每个被遍历到的节点调用 `batch_calculate_node_scores`（一次性传整批节点 ID，最大化横截面标准化样本）
5. 把 NodeScoreResult 转换为 `ResearchNode` 嵌套结构（children 来自图遍历）
6. 缓存：`Cache-Control: max-age=300`（前端 React Query staleTime=5min）

### 2. GET /api/tasks/{task_id}/nodes/{node_id}/holdings

**响应**（匹配 README 的 `NodeHolding[]`）：

```json
[
  {
    "ticker": "NVDA",
    "weight": 22.1,
    "score": 91.2,
    "name": "NVIDIA Corp.",
    "return20d": 0.183,
    "rs20d": 11.9,
    "delta3d": 4.1,
    "delta5d": 7.8,
    "dataStatus": "complete"
  }
]
```

**实现要点**：
1. 调 `get_node_holdings(node_id)` 拿成分股 + 权重
2. 对每只成分股：
   - 从 `Stock` 表读 score / changes
   - 从 `PriceHistory` 算 return20d
   - rs20d = 该股 20D RS_change vs **节点价格序列**（不是 vs SPY），节点价格序列从 NodePriceSeries（synthetic）或 PriceHistory of proxy ETF（GICS 节点）取
3. 状态判定：finviz + iv 都齐 → 'complete'；缺一 → 'pending'；都缺 → 'missing'

### 3. GET /api/tasks/{task_id}/nodes/{node_id}/trend-comparison

**Query params**:
- `period` ∈ `{5, 20, 63}`（与现有 `GET /tasks/{id}/trend-comparison` 一致）
- `metric` ∈ `{relative, return20d, score}`
- `label_tz` ∈ `{beijing, market}`（默认 beijing）

**响应**（与现有 `/tasks/{id}/trend-comparison` 同结构，方便前端复用 `RelativeTrendChart`）：

```json
{
  "task_id": 7,
  "node_id": "semi",
  "period": 20,
  "metric": "relative",
  "label_tz": "beijing",
  "symbols": ["semi", "XLK", "SPY"],
  "dates": ["2026-04-01", ...],
  "series": [
    {"symbol": "semi", "color": "#3b82f6", "values": [0.0, 0.5, 1.2, ...]},
    {"symbol": "XLK", "color": "#8b5cf6", "values": [0.0, 0.3, 0.8, ...]},
    {"symbol": "SPY", "color": "#94a3b8", "values": [0.0, 0.1, 0.4, ...]}
  ]
}
```

**实现要点**：
1. 找父节点 = `NodeEdge` 中 `dst=node_id, type=classification_parent` 的 src（lens='gics'）
2. 给 [node, parent, SPY] 三个 symbol 各取 60-day 价格序列
   - node 的价格 = synthetic 走 NodePriceSeries / GICS 走 proxy ETF 的 PriceHistory
3. 调用现有 `build_metric_series`（已在 `series_utils.py`），把 node_id 也当成 symbol 传入
4. 颜色固定：node=#3b82f6 / parent=#8b5cf6 / SPY=#94a3b8

### 4. 测试

`test_nodes_api.py` 至少覆盖：
- GET /api/tasks/{id}/nodes 返回根节点 + 至少 1 层子节点
- GET /api/tasks/{id}/nodes/semi/holdings 返回 ≥ 3 只成分股
- 给 synthetic 节点（semi-compute）调 holdings 返回 NVDA/AMD/AVGO
- GET /api/tasks/{id}/nodes/semi/trend-comparison?period=20 返回 3 条 series
- 不存在的 node_id → 404

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 路由前缀 `/api/tasks` 与现有 tasks.py 不冲突（`include_router` 时用 `tags=["nodes"]` 区分）
- 所有 GET 接口 **不写库**（`compute_basket_price_series` 已在 4.3 内部 idempotent upsert）
- 错误处理使用现有 `HTTPException` 模式

## 验证标准

- `pytest backend/tests/test_nodes_api.py -v` 全部通过
- `curl http://localhost:8000/api/tasks/1/nodes` 返回正确 JSON
- 单次请求耗时 ≤ 2s（节点 ≤ 13 个时）

---

# Task 4.7 — 前端 Types + API Client + DrilldownView 骨架

> **依赖**：Task 4.6
> **模型配置**：`claude-opus-4-7` · effort=medium · thinking=extended

## 规格源（必读）

- **主源**：`/Users/bin/Downloads/design_handoff_drilldown/README.md`
  - 第 "TypeScript Types" 章节 — `ResearchNode` / `NodeHolding` / `NodeProxyType` / `NodeTrendData` 完整类型定义（含字段可空性）
  - 第 "New API Endpoints" 章节 — 3 个端点的请求/响应 schema
  - 第 "Layout & Container" 章节 — 三栏 280 / flex / 300 的 CSS spec
  - 第 "State Management" 章节 — localStorage key 命名规则
- **辅源**（按需查阅）：`/Users/bin/Downloads/design_handoff_drilldown/drilldown-upgrade.prototype.html`
  仅在 README 字段语义模糊或边界值不清时查阅。**本 Task 不实现具体组件 UI**，HTML 中的组件实现留给 4.8/4.9/4.10。

## 背景

前端实现分为 5 个 Task（4.7–4.11）。本 Task 是骨架：类型定义、API client、空壳 DrilldownView 三栏布局。

## 目标

1. 在 `frontend/src/types/index.ts` 增加 `ResearchNode / NodeHolding / NodeProxyType / NodeTrendData / TaskViewMode` 等类型
2. 在 `frontend/src/services/api.ts` 增加 3 个 API 函数 + 1 个 Query Key 工厂
3. 创建 `frontend/src/components/task/DrilldownView.tsx` 三栏壳（左 280 / 中 flex / 右 300），状态管理 + localStorage 持久化
4. 在 `TaskDetail.tsx` 中接入：`task.type === 'drilldown'` 时渲染 `<DrilldownView task={task} onViewStockDetail={onViewStockDetail} />`，**保持其他类型不变**

## 需要修改/新建的文件

- `frontend/src/types/index.ts` — 追加类型
- `frontend/src/services/api.ts` — 追加 3 个函数
- `frontend/src/components/task/DrilldownView.tsx` — **新建**（先做空壳）
- `frontend/src/components/task/index.ts` — 导出
- `frontend/src/components/task/TaskDetail.tsx` — 接入条件渲染（**只改 drilldown 分支**）

## 具体要求

### 1. types/index.ts 追加

```typescript
// ============ Phase 4: Drilldown Node Types ============

export type NodeProxyType = 'etf' | 'synthetic';
export type TaskViewMode = 'gics' | 'chain' | 'hybrid';
export type NodeTrendMetric = 'relative' | 'return20d' | 'score';
export type NodeTrendPeriod = '5d' | '20d' | '63d';

export interface ResearchNode {
  id: string;
  label: string;
  sublabel: string;
  level: number;
  proxy: string | null;
  proxyType: NodeProxyType;
  proxyLabel?: string;
  score: number;
  scoreVsParent: number | null;
  contribution: number | null;
  relStrength: string;
  breadth: number;
  delta3d: number | null;
  delta5d: number | null;
  children: ResearchNode[];
}

export interface NodeHolding extends Holding {
  name?: string;
  return20d: number;
  rs20d: number;
  delta3d: number;
  delta5d: number;
  status?: 'complete' | 'pending' | 'missing';
}

export interface NodeTrendSeries {
  symbol: string;
  color: string;
  values: (number | null)[];
}

export interface NodeTrendResponse {
  task_id: number;
  node_id: string;
  period: number;
  metric: NodeTrendMetric;
  label_tz: 'beijing' | 'market';
  symbols: string[];
  dates: string[];
  series: NodeTrendSeries[];
}
```

### 2. api.ts 追加

```typescript
// ===== Phase 4: Node API =====

export async function getTaskNodeTree(
  taskId: number,
  lens: TaskViewMode = 'gics'
): Promise<ResearchNode[]> {
  const params = new URLSearchParams({ lens });
  const response = await fetch(`${API_BASE_URL}/tasks/${taskId}/nodes?${params}`, {
    headers: defaultHeaders(),
  });
  if (!response.ok) throw new Error(`Failed to fetch node tree: ${response.status}`);
  return response.json();
}

export async function getNodeHoldings(
  taskId: number,
  nodeId: string
): Promise<NodeHolding[]> {
  const response = await fetch(
    `${API_BASE_URL}/tasks/${taskId}/nodes/${encodeURIComponent(nodeId)}/holdings`,
    { headers: defaultHeaders() }
  );
  if (!response.ok) throw new Error(`Failed to fetch node holdings: ${response.status}`);
  return response.json();
}

export async function getNodeTrendSeries(
  taskId: number,
  nodeId: string,
  period: NodeTrendPeriod,
  metric: NodeTrendMetric,
  labelTz: 'beijing' | 'market' = 'beijing'
): Promise<NodeTrendResponse> {
  const periodNum = { '5d': 5, '20d': 20, '63d': 63 }[period];
  const params = new URLSearchParams({
    period: String(periodNum),
    metric,
    label_tz: labelTz,
  });
  const response = await fetch(
    `${API_BASE_URL}/tasks/${taskId}/nodes/${encodeURIComponent(nodeId)}/trend-comparison?${params}`,
    { headers: defaultHeaders() }
  );
  if (!response.ok) throw new Error(`Failed to fetch trend series: ${response.status}`);
  return response.json();
}

// Query keys factory (用于 React Query / TanStack Query 缓存键)
export const drilldownQueryKeys = {
  nodeTree: (taskId: number, lens: TaskViewMode) => ['task-nodes', taskId, lens] as const,
  nodeHoldings: (taskId: number, nodeId: string) => ['node-holdings', taskId, nodeId] as const,
  nodeTrend: (taskId: number, nodeId: string, period: NodeTrendPeriod, metric: NodeTrendMetric) =>
    ['node-trend', taskId, nodeId, period, metric] as const,
};
```

### 3. DrilldownView.tsx 骨架

```tsx
// frontend/src/components/task/DrilldownView.tsx
import { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as api from '../../services/api';
import type {
  Task, ResearchNode, NodeHolding, NodeTrendPeriod, NodeTrendMetric, TaskViewMode
} from '../../types';

interface DrilldownViewProps {
  task: Task;
  onViewStockDetail?: (ticker: string) => void;
}

const LS_KEY = (taskId: number) => `drilldown-selected-node-${taskId}`;

function flattenTree(nodes: ResearchNode[]): ResearchNode[] {
  const out: ResearchNode[] = [];
  const walk = (ns: ResearchNode[]) => {
    for (const n of ns) {
      out.push(n);
      if (n.children?.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

export function DrilldownView({ task, onViewStockDetail }: DrilldownViewProps) {
  const [lens, setLens] = useState<TaskViewMode>('gics');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [trendPeriod, setTrendPeriod] = useState<NodeTrendPeriod>('20d');
  const [trendMetric, setTrendMetric] = useState<NodeTrendMetric>('relative');
  const [showAllHoldings, setShowAllHoldings] = useState(false);

  // Restore from localStorage
  useEffect(() => {
    const saved = localStorage.getItem(LS_KEY(task.id));
    if (saved) setSelectedNodeId(saved);
  }, [task.id]);

  // Persist to localStorage
  useEffect(() => {
    if (selectedNodeId) localStorage.setItem(LS_KEY(task.id), selectedNodeId);
  }, [task.id, selectedNodeId]);

  // Node tree
  const { data: nodeTree, isLoading: treeLoading } = useQuery({
    queryKey: api.drilldownQueryKeys.nodeTree(task.id, lens),
    queryFn: () => api.getTaskNodeTree(task.id, lens),
    staleTime: 5 * 60 * 1000,
  });

  const allNodes = useMemo(() => (nodeTree ? flattenTree(nodeTree) : []), [nodeTree]);
  const selectedNode = useMemo(
    () => allNodes.find((n) => n.id === selectedNodeId) ?? allNodes[0] ?? null,
    [allNodes, selectedNodeId]
  );

  // Holdings
  const { data: holdings = [] } = useQuery({
    queryKey: selectedNode ? api.drilldownQueryKeys.nodeHoldings(task.id, selectedNode.id) : ['noop'],
    queryFn: () => (selectedNode ? api.getNodeHoldings(task.id, selectedNode.id) : Promise.resolve([])),
    enabled: !!selectedNode,
    staleTime: 60 * 1000,
  });

  // Trend
  const { data: trendData } = useQuery({
    queryKey: selectedNode
      ? api.drilldownQueryKeys.nodeTrend(task.id, selectedNode.id, trendPeriod, trendMetric)
      : ['noop'],
    queryFn: () =>
      selectedNode
        ? api.getNodeTrendSeries(task.id, selectedNode.id, trendPeriod, trendMetric)
        : null,
    enabled: !!selectedNode,
    staleTime: 60 * 1000,
  });

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* LEFT 280 */}
      <aside style={{ width: 280, flexShrink: 0, borderRight: '1px solid #e2e8f0', background: '#fff' }}>
        {/* TODO Task 4.8: <NodeTree ... /> */}
        <div style={{ padding: 16, fontSize: 12, color: '#64748b' }}>NodeTree (Task 4.8)</div>
      </aside>

      {/* CENTER flex */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', background: '#f8fafc' }}>
        {/* TODO Task 4.9: regime / trend / matrix / holdings / data-source */}
        <div style={{ fontSize: 12, color: '#64748b' }}>Center (Task 4.9). Selected: {selectedNode?.label}</div>
      </main>

      {/* RIGHT 300 */}
      <aside style={{ width: 300, flexShrink: 0, borderLeft: '1px solid #e2e8f0', background: '#f8fafc' }}>
        {/* TODO Task 4.10: <NodeDetailPanel ... /> */}
        <div style={{ padding: 16, fontSize: 12, color: '#64748b' }}>NodeDetailPanel (Task 4.10)</div>
      </aside>
    </div>
  );
}
```

### 4. TaskDetail.tsx 接入

定位 `TaskDetail.tsx:2114-2143` 的 ETF 卡片渲染区，把 drilldown 分支改造为：

```tsx
{task.type === 'drilldown' ? (
  <DrilldownView task={task} onViewStockDetail={onViewStockDetail} />
) : (
  <div>
    {/* 现有 ETF Cards Section 保留, 仅 rotation/momentum 走这里 */}
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-base font-semibold">监控ETF ({etfSymbols.length})</h3>
    </div>
    <div className="grid grid-cols-3 gap-5">
      {etfDetails.map(...)}
    </div>
  </div>
)}
```

**注意**：保留 `RelativeTrendChart` 组件给 rotation/momentum 用，不要错删。

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 不动 rotation / momentum 渲染分支
- 不动现有 `ETFDetailCard.tsx` / `RelativeTrendChart.tsx`
- DrilldownView 内部使用现有 React Query (`@tanstack/react-query`)，不要新增状态管理库
- TypeScript strict 模式下零 error

## 验证标准

- `npm run typecheck` 零 error
- `npm run dev` 后访问任意 drilldown 任务，看到三栏空壳，selectedNode label 显示根节点
- localStorage 中能看到 `drilldown-selected-node-{id}`
- rotation / momentum 任务详情页与升级前完全一致

---

# Task 4.8 — NodeTree 左栏组件

> **依赖**：Task 4.7
> **模型配置**：`claude-sonnet-4-6` · effort=medium · thinking=standard

## 规格源（必读）

- **主源（像素 spec）**：`/Users/bin/Downloads/design_handoff_drilldown/README.md`
  → "Panel 2 — Left: Research Node Tree (280px)" 章节
- **辅源（参考实现，必读）**：`/Users/bin/Downloads/design_handoff_drilldown/drilldown-upgrade.prototype.html`
  → 函数 `NodeItem` / `Sparkline` / 节点树容器的完整 React 实现 + 内联 style
  → 复用其结构与交互（hover / selected / expand-collapse 状态机），但用项目实际 className 体系替换内联 style
- 当 README 与 HTML 出现差异时，**以 README 为准**（README 是契约，HTML 是参考实现）。

## 背景

落实 README 第 "Panel 2 — Left: Research Node Tree (280px)" 章节的高保真规格。

## 目标

实现 `frontend/src/components/task/NodeTree.tsx`，命中 README 的所有像素 spec。

## 需要修改/新建的文件

- `frontend/src/components/task/NodeTree.tsx` — **新建**
- `frontend/src/components/task/Sparkline.tsx` — **新建**（小型 SVG 折线，复用给 NodeDetailPanel）
- `frontend/src/components/task/DrilldownView.tsx` — 替换左栏 placeholder
- `frontend/src/components/task/index.ts` — 导出

## 具体要求

### 1. NodeTree props

```tsx
interface NodeTreeProps {
  nodes: ResearchNode[];
  selectedNodeId: string | null;
  expandedIds: Set<string>;
  lens: TaskViewMode;
  onSelect: (node: ResearchNode) => void;
  onToggleExpand: (nodeId: string) => void;
  onLensChange: (lens: TaskViewMode) => void;
  totalNodeCount: number;
  isLoading?: boolean;
}
```

### 2. 像素规格（必须命中）

参考 README + 原型 HTML：

| 元素 | 规格 |
|------|------|
| Container | `width: 280px`, `flex-shrink: 0`, `border-right: 1px solid #e2e8f0`, `background: #fff` |
| Header padding | `14px 16px 10px`, `border-bottom: 1px solid #f1f5f9` |
| Title row | "研究节点树" 13px bold + Layers icon (14px) + `{count} 节点` 11px muted right |
| Lens toggle container | `background: #f1f5f9`, `padding: 3px`, `border-radius: 8px`, segmented |
| Active lens | `background: #fff`, `color: #1e293b`, `box-shadow: 0 1px 3px rgba(0,0,0,0.08)` |
| Inactive lens | `color: #64748b`, transparent |
| Column header row | "节点 / 代理" / "20D走势" (44px) / "分数" (28px) — 10px muted |
| Node row | `padding: 8px 12px`, `padding-left: 12 + level*16`, `border-radius: 8px`, `margin: 1px 6px` |
| Selected | `border: 1px solid var(--accent-blue)` + gradient bg `linear-gradient(135deg, rgba(37,99,235,0.07), rgba(147,51,234,0.07))` |
| Hover (unselected) | `background: #f1f5f9` |
| Chevron | 14px width, `color: #94a3b8`，无 children 时占位空 |
| Label | `font-size: 13px`, `font-weight: 500/700` |
| Sublabel | `font-size: 10px`, `color: #94a3b8`, truncate |
| Proxy tag (ETF) | `background: rgba(59,130,246,0.1)`, `color: #2563eb`, `font-size: 10px`, `padding: 1px 6px` |
| Proxy tag (synthetic) | `background: rgba(245,158,11,0.1)`, `color: #d97706`，文字 `合成` |
| Sparkline | 44×18px |
| Score | 13px bold, score-tier color, `min-width: 28px`, right-align |
| Score colors | ≥85 #059669 / ≥70 #2563eb / ≥60 #d97706 / else #64748b |

### 3. 子组件 Sparkline

```tsx
interface SparklineProps {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}

export function Sparkline({ data, color = '#3b82f6', width = 44, height = 18 }: SparklineProps) {
  // SVG <polyline>，data.length < 2 时渲染空 span
  // 算法见原型 HTML `Sparkline` 函数实现
}
```

数据来源：直接用 `node.delta3d / delta5d / score` 凑 5 点序列即可；或在 4.6 的 API 里追加 `sparkValues: number[]` 字段（更准确但更费力，本 Task 先用前端凑）。

### 4. 点击行为

- 单击节点 → `onSelect(node)`；如果 hasChildren → 同时 `onToggleExpand(node.id)`
- 单击 Lens → `onLensChange`，触发节点树重新拉取（DrilldownView 已用 lens 作为 queryKey）

### 5. Footer Legend

`padding: 10px 16px`，两个 pill：`ETF 代理`（蓝）/ `合成篮`（橙），样式与 proxy tag 一致。

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 仅渲染 + 交互，不写 React Query
- score-tier color helper 抽到独立工具 `frontend/src/components/task/nodeStyles.ts`（4.9/4.10 复用）
- 树结构递归渲染，深度 ≤ 4 层（React 默认即可，无需虚拟化）

## 验证标准

- 视觉：与 prototype HTML 一致（在浏览器里目测每个像素值）
- 鼠标悬浮非选中节点 → 背景变 #f1f5f9
- 点击 child 节点 → 选中 + 展开 + 同步 localStorage
- 切 lens → 树重新拉取（network panel 看到新的 `lens=chain` 请求）

---

# Task 4.9 — Center 中栏（Trend / Matrix / Holdings / DataSource）

> **依赖**：Task 4.7, 4.8
> **模型配置**：`claude-sonnet-4-6` · effort=high · thinking=standard

## 规格源（必读）

- **主源（像素 spec）**：`/Users/bin/Downloads/design_handoff_drilldown/README.md`
  → "Panel 3 — Center: Main Content" 章节，包含 5 张卡片的 CSS 规格
- **辅源（参考实现，必读）**：`/Users/bin/Downloads/design_handoff_drilldown/drilldown-upgrade.prototype.html`
  → 函数 `TrendChart` / `RegimeBadge` / `ContribBar` / `StockHoldingsTable` 的完整 React 实现
  → mock 数据结构 `NODE_HOLDINGS` 字段（用作真实 API 响应的字段对齐参照）
  → SVG 走势图绘制逻辑（path 计算、tooltip、period toggle）
- README 与 HTML 冲突时**以 README 为准**。

## 背景

落实 README "Panel 3 — Center: Main Content" 章节。中栏由 5 张卡组成（自上而下）：Regime Badge → Trend Chart → Sub-Node Matrix → Holdings Table → Data Source Status Bar。

## 目标

实现 4 个子组件 + 1 个中栏容器，在 DrilldownView 中替换 Center placeholder。

## 需要修改/新建的文件

- `frontend/src/components/task/NodeTrendChart.tsx` — **新建**
- `frontend/src/components/task/NodeMatrix.tsx` — **新建**
- `frontend/src/components/task/NodeHoldingsTable.tsx` — **新建**
- `frontend/src/components/task/DataSourceBar.tsx` — **新建**（4 个数据源 pill）
- `frontend/src/components/task/RegimeBadge.tsx` — **新建**（复用 `getMarketRegime` API）
- `frontend/src/components/task/DrilldownView.tsx` — 装配中栏

## 具体要求

### 1. RegimeBadge（参考 README "Card 1 — Regime Badge"）

- 调用 `api.getMarketRegime()` 拿数据，5min refetch
- 三档背景色（A/B/C）：
  - A: `linear-gradient(105deg,#059669 0%,#10b981 50%,#34d399 100%)`
  - B: `linear-gradient(105deg,#d97706,#f59e0b,#fbbf24)`
  - C: `linear-gradient(105deg,#dc2626,#ef4444,#f87171)`
- 5 列指标：$SPY 价 / 距20MA% / 距50MA% / 广度% / VIX
- `border-radius: 12px`, `box-shadow: 0 2px 10px rgba(16,185,129,0.2)`

### 2. NodeTrendChart（README "Card 2 — Trend Chart"）

```tsx
interface NodeTrendChartProps {
  selectedNode: ResearchNode;
  data: NodeTrendResponse | null;
  period: NodeTrendPeriod;
  metric: NodeTrendMetric;
  onPeriodChange: (p: NodeTrendPeriod) => void;
  onMetricChange: (m: NodeTrendMetric) => void;
  isLoading: boolean;
}
```

- SVG `viewBox="0 0 600 200"`, padding `{t:12, r:16, b:28, l:44}`
- Y 网格 3 条（min/mid/max），stroke `#e2e8f0`
- 零线 `stroke: #cbd5e1`, `stroke-dasharray: 4,3`（仅当数据跨零时画）
- 系列线：node 2px 满透明 / parent 1.5px 0.6 / SPY 1.5px 0.6
- 颜色 node #3b82f6 / parent #8b5cf6 / SPY #94a3b8（与后端返回的 series.color 对齐）
- Period toggle：5d / 20d / 63d，segmented control
- Metric toggle：相对走势 / 20D收益 / 综合评分
- Legend：色条 20×2.5 + symbol 标签

### 3. NodeMatrix（README "Card 3 — Sub-Node Matrix"）

仅当 `selectedNode.children.length > 0` 时渲染。

- Grid `repeat(min(4, childCount), 1fr)`, gap 10
- 每张子节点卡：
  - Header：label 13px bold + proxy tag | score 20px bold（tier color）
  - Sparkline 220×28
  - Contribution 行：`对母板块贡献` 10px muted + `{value}%` 11px bold #2563eb + 进度条
  - Bottom 三列：`vs母 {scoreVsParent}` / `5D {delta5d}` / `广度 {breadth}%`
  - 点击 → `onSelect(child)` + 展开

### 4. NodeHoldingsTable（README "Card 4 — Holdings Table"）

```tsx
interface NodeHoldingsTableProps {
  holdings: NodeHolding[];
  showAll: boolean;
  onShowAll: () => void;
  onRowClick?: (ticker: string) => void;
  isLoading: boolean;
}
```

- 列：`# / 标的 / 权重↕ / 动能分↕ / 20D收益↕ / RS节点↕ / 3D Δ↕ / 5D Δ↕ / 状态`
- 默认按动能分降序，点击表头切换 sort key（同 key 切方向）
- 8 行截断 + `展开全部 (N 更多)` 按钮
- 偶数行 `background: #fafbfc`，hover `#eff6ff`
- 标的列：3px 高度的 score-tier 色条 + ticker 13px bold + name 10px muted truncate
- 状态 pill：complete `bg: rgba(34,197,94,0.1)` / pending `bg: rgba(245,158,11,0.1)` / missing `bg: rgba(239,68,68,0.1)`

行点击 → 调用 `onRowClick(ticker)` → DrilldownView 透传给 `props.onViewStockDetail`

### 5. DataSourceBar（README "Card 5 — Data Source Status Bar"）

- 4 个数据源：Finviz / MarketChameleon / IBKR 市场数据 / Futu 期权数据
- 状态来自 `task.sourceUpdatedAt`（如果 ETF detail 有），全 OK 显示 OK pill，缺一显示 pending
- 时间戳右对齐 10px muted

### 6. 在 DrilldownView 中装配

```tsx
<main style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', background: '#f8fafc' }}>
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <RegimeBadge />
    {selectedNode && (
      <>
        <NodeTrendChart
          selectedNode={selectedNode}
          data={trendData ?? null}
          period={trendPeriod}
          metric={trendMetric}
          onPeriodChange={setTrendPeriod}
          onMetricChange={setTrendMetric}
          isLoading={false}
        />
        {selectedNode.children?.length > 0 && (
          <NodeMatrix
            selectedNode={selectedNode}
            onSelectChild={(child) => {
              setSelectedNodeId(child.id);
              setExpandedIds((prev) => new Set([...prev, selectedNode.id, child.id]));
            }}
          />
        )}
        <NodeHoldingsTable
          holdings={holdings}
          showAll={showAllHoldings}
          onShowAll={() => setShowAllHoldings(true)}
          onRowClick={onViewStockDetail}
          isLoading={false}
        />
        <DataSourceBar />
      </>
    )}
  </div>
</main>
```

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 不引入新 charting 库（Recharts/Chart.js 等），使用纯 SVG
- 颜色 / padding / border-radius **必须** 与 README 值一致
- NodeTrendChart 的 series 数据全部来自 4.6 API，不要前端 mock

## 验证标准

- 视觉对照原型 HTML 像素级一致
- Period 切换 → Network 中能看到新请求 `period=5/20/63`
- Holdings 默认 8 行 + 展开按钮可见
- 点击子节点矩阵卡 → 中栏 + 左栏 + 右栏同步切换

---

# Task 4.10 — NodeDetailPanel 右栏组件

> **依赖**：Task 4.7
> **模型配置**：`claude-sonnet-4-6` · effort=medium · thinking=standard

## 规格源（必读）

- **主源（像素 spec）**：`/Users/bin/Downloads/design_handoff_drilldown/README.md`
  → "Panel 4 — Right: Node Detail Panel (300px)" 章节
- **辅源（参考实现，必读）**：`/Users/bin/Downloads/design_handoff_drilldown/drilldown-upgrade.prototype.html`
  → 函数 `NodeDetailPanel` 的完整 React 实现
  → 子卡的 score 颜色分级、proxy 标签样式、hover 交互
- README 与 HTML 冲突时**以 README 为准**。

## 背景

落实 README "Panel 4 — Right: Node Detail Panel (300px)"。右栏由 5 张子卡组成（自上而下）：Header → Node Header Card → 节点贡献与广度 → 同层节点排名 → 持仓 Top 5 → 子节点概览。

## 目标

实现 `NodeDetailPanel.tsx` 与 5 个子卡，装配进 DrilldownView。

## 需要修改/新建的文件

- `frontend/src/components/task/NodeDetailPanel.tsx` — **新建**
- `frontend/src/components/task/DrilldownView.tsx` — 替换右栏 placeholder

## 具体要求

### 1. Component props

```tsx
interface NodeDetailPanelProps {
  selectedNode: ResearchNode;
  allNodes: ResearchNode[];   // 用于查 sibling
  holdings: NodeHolding[];    // 用于 Top 5 持仓
  onSelectNode: (node: ResearchNode) => void;
}
```

### 2. Header（README "Header (padding: 12px 16px)"）

- "节点详情" 13px bold + BarChart icon
- Level badge `L{level + 1}` 10px muted, `background: #f1f5f9`, `padding: 2px 7px`, `border-radius: 5px`

### 3. Node Header Card（README "Card: Node Header"）

- `border-radius: 14px`, `padding: 14px`, `border: 1px solid #e2e8f0`
- Label 17px bold + proxy tag pill (ETF / 合成篮)
- Sublabel 12px #64748b
- Synthetic 时多一行 `proxyLabel` 11px #94a3b8（如 "NVDA + AMD + AVGO"）
- Score 30px bold tier-color，右对齐；下方 `综合分` 10px muted
- 2×2 metric grid：相对母节点 / 相对强度 / 3D Δ分 / 5D Δ分
  - 每个 cell `background: #f8fafc`, `border: 1px solid #f1f5f9`, `border-radius: 8px`, `padding: 7px 10px`
  - Label 10px muted / Value 14px bold tnum，颜色随 delta 变化（绿/红/灰）

### 4. 节点贡献与广度卡（仅当 contribution !== null）

- "对母板块贡献" + `{value}%` 12px bold #2563eb + 进度条 5px / `border-radius: 3px`
- "持仓广度 (>50MA)" + `{value}%` tier color + 进度条
- 进度条 fill 颜色随值分档：≥70 #22c55e / ≥50 #3b82f6 / else #f59e0b

### 5. 同层节点排名（仅当 siblings 存在）

- 通过 allNodes 找到 selectedNode 的兄弟（共享 parent）
- 按 score 降序排
- 每行 padding 7px 10px, border-radius 8px
- 选中兄弟 highlighted: `background: rgba(37,99,235,0.06)`, `border: 1px solid rgba(59,130,246,0.2)`
- 行内：#rank 11px muted | label 12px + proxy 10px | sparkline 36×16 | score 13px bold

### 6. 持仓 Top 5 紧凑卡

```tsx
const top5 = useMemo(
  () => [...holdings].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 5),
  [holdings]
);
```

- 每行 padding 6px 8px, border-radius 8px, background #f8fafc
- #rank | ticker 12px bold + name 10px muted | score 13px tier-color + return20d 10px (delta color) | weight + status

### 7. 子节点概览卡（仅当 children > 0）

- 按 child.score 降序
- 每行：label | proxy/basket 10px muted | 5D delta | score 13px bold
- 点击行 → `onSelectNode(child)`

### 8. DrilldownView 装配

替换右栏 placeholder：

```tsx
<aside style={{ width: 300, flexShrink: 0, borderLeft: '1px solid #e2e8f0', background: '#f8fafc' }}>
  {selectedNode && (
    <NodeDetailPanel
      selectedNode={selectedNode}
      allNodes={allNodes}
      holdings={holdings}
      onSelectNode={(n) => setSelectedNodeId(n.id)}
    />
  )}
</aside>
```

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- 不重复请求 holdings / trend（DrilldownView 已统一管理）
- 文案直接使用 README 中的中文标签

## 验证标准

- 视觉与原型 HTML 一致
- 切换不同 level 节点 → Header 中 L1/L2/L3 badge 跟随变化
- 点击同层兄弟节点 → DrilldownView 主选中切换
- root 节点（XLK）→ 不显示 contribution、scoreVsParent 卡

---

# Task 4.11 — TaskDetail 集成 + CreateTaskModal/AddTaskETFsModal node-first 改造

> **依赖**：Task 4.5, 4.6, 4.7-4.10
> **模型配置**：`claude-sonnet-4-6` · effort=medium · thinking=extended

## 规格源（必读）

- **主源**：`/Users/bin/Downloads/design_handoff_drilldown/README.md`
  → "Integration Points" / "Modal Flow" 章节（如有），描述 node-first 选择流程
- **辅源**（按需查阅）：`/Users/bin/Downloads/design_handoff_drilldown/drilldown-upgrade.prototype.html`
  本 Task 主要是集成与表单改造，原型 HTML 中如有 modal 流程片段可参照。
- 项目内集成位置以 [`frontend/src/components/task/TaskDetail.tsx`](frontend/src/components/task/TaskDetail.tsx) 与 [`frontend/src/components/modal/CreateTaskModal.tsx`](frontend/src/components/modal/CreateTaskModal.tsx) 现有结构为准。

## 背景

前面 10 个 Task 完成后，drilldown 任务详情已是节点化界面，但创建任务和追加 ETF 的入口还在硬编码 INDUSTRY_ETFS。本 Task 把入口也升级。

## 目标

1. `CreateTaskModal.tsx` 中 drilldown 类型的 step 3（选择子项）从硬编码 INDUSTRY_ETFS 改为从后端拉取 root_node 的子节点列表
2. `AddTaskETFsModal.tsx` 同理改为"添加节点 / 证据节点"
3. 增加 `GET /api/nodes/catalog?root_node=XLK&include_evidence=true` 端点供两个 modal 调用
4. 把 `task.etfs` 与 `task.selectedNodes` 字段同时填充（让 4.5 的兼容逻辑生效）

## 需要修改/新建的文件

- `backend/app/api/nodes.py` — 增加 `GET /catalog`
- `frontend/src/services/api.ts` — `getNodeCatalog`
- `frontend/src/components/modal/CreateTaskModal.tsx` — drilldown step 3 改造
- `frontend/src/components/modal/AddTaskETFsModal.tsx` — 改造
- `frontend/src/types/index.ts` — `NodeCatalogItem` 类型

## 具体要求

### 1. 后端 catalog 端点

```python
# backend/app/api/nodes.py
@router.get("/catalog")
async def get_node_catalog(
    root_node: str,
    include_evidence: bool = True,
    db: Session = Depends(get_db),
):
    """返回某个根节点（如 XLK）下可被选中的所有子节点 + 证据节点。

    用于创建任务和追加节点的 modal。
    """
    # 1. 取 root_node 的所有 classification_parent / chain_parent 后代
    # 2. 如果 include_evidence: 取 corroborates 边连到子树内任意节点的 evidence 节点
    # 3. 返回 [{id, label, sublabel, level, node_type, proxy_etf, proxy_label, parent_id}]
```

注意路由前缀：本端点挂在 `/api/nodes/catalog`（不含 task_id），所以 `app.include_router(nodes.router, prefix="/api/nodes", ...)` 与 4.6 的 task-scoped 路径并存（用两个 router 或 prefix 处理）。

### 2. CreateTaskModal 改造

定位 `frontend/src/components/modal/CreateTaskModal.tsx:38-46` 的 `INDUSTRY_ETFS`：

- 删除该常量
- drilldown 任务的 step 3 改为：
  - selectedSector 选定后，触发 `useQuery(['node-catalog', selectedSector])` → `getNodeCatalog(selectedSector, true)`
  - 渲染分组列表：GICS 子节点（默认全选）/ 产业链节点（手选）/ 证据节点（手选）
  - selectedNodes state 为 `string[]`（node_id 数组）
- 提交时，CreateTaskInput 里同时填：
  ```ts
  {
    rootNode: selectedSector,
    viewMode: 'gics',
    selectedNodes,
    pinnedEvidenceNodes: selectedEvidenceIds,
    // 兼容: etfs 仍然填一份, 由后端反向解析 NodeProxy 得到
    etfs: selectedNodes.flatMap(id => nodeIdToProxy[id] ?? []).filter(Boolean),
    sector: selectedSector,
  }
  ```

### 3. AddTaskETFsModal 改造

类似地，把 modal 标题改为"追加节点"，列表来源换为 `getNodeCatalog`，并在 onSubmit 时同时回写 `task.selectedNodes` 与 `task.etfs`。

### 4. CreateTaskInput 类型升级

```ts
export interface CreateTaskInput {
  // 现有字段保留
  title: string;
  type: TaskType;
  baseIndex: string;
  baseIndices?: string[];
  sector?: string;
  etfs: string[];

  // Phase 4 新增
  rootNode?: string;
  viewMode?: TaskViewMode;
  selectedNodes?: string[];
  pinnedEvidenceNodes?: string[];
  maxDepth?: number;
}
```

### 5. 后端 schemas 同步

`backend/app/schemas/__init__.py` 的 `TaskCreate` / `TaskEtfsAdd` 加可选字段：

```python
class TaskCreate(BaseModel):
    # 现有字段
    ...
    # Phase 4 新增
    rootNode: Optional[str] = None
    viewMode: Optional[str] = None
    selectedNodes: Optional[List[str]] = None
    pinnedEvidenceNodes: Optional[List[str]] = None
    maxDepth: Optional[int] = None
```

`tasks.py` 的 create_task / update_task 把这些字段写入 Task 表对应列。

## 约束

> **必读全局约束**：本 Task 在执行时同时遵守 0.5（硬性约束）、0.6（Rotation 隔离清单）、0.8（Rotation 回归验证清单）及项目 `CLAUDE.md` 编码规范。下列条目为本 Task 的**额外**约束。

- rotation / momentum 类型的创建流程**完全不变**
- 老前端 / 老用户行为：不带 rootNode 创建 drilldown 任务时，后端用旧逻辑 + 自动迁移（4.5 已实现）
- AddTaskETFsModal 的现有"添加 ETF"语义保留（不删按钮文案，仅在 drilldown 上额外加 "添加节点" tab）

## 验证标准

- 创建一个 XLK drilldown 任务 → 进入详情页直接看到节点树（不再看到 ETF 列表平铺）
- DB 中 `tasks` 表新任务的 `root_node='XLK'`, `selected_nodes=['semi','soft','hw',...]`
- 创建 rotation 任务流程完全没变
- `pytest backend/tests/ -v` 全部通过
- `npm run typecheck && npm run lint` 零错误

---

## 附录 A：执行顺序与风险

### A.1 推荐执行顺序

1. **第一周**：4.1 → 4.2 → 4.3 → 4.4（后端核心，可独立测试）
2. **第二周**：4.5 → 4.6（数据迁移 + API 暴露）
3. **第三周**：4.7 → 4.8 → 4.9 → 4.10（前端 UI 逐栏落地，每完成一个 Task 都能在浏览器里看到进度）
4. **第四周**：4.11（创建/追加入口最后改，避免提前破坏现有 UX）

### A.2 主要风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| Synthetic basket 在历史数据稀疏的成分股上覆盖率低 | Task 4.3 的 `min_constituents` 与 `coverage_ratio` 字段透传到 NodeScoreResult.notes，前端在分数旁显示 "数据置信度低" 提示 |
| Chain confirmation 公式过激进，导致弱节点反弹 | Task 4.4 公式中的 `(0.7 + 0.3 × chain_confirmation)` 把 confirmation 权重压在 30%，变化温和 |
| 旧 drilldown 任务迁移数据丢失 | Task 4.5 默认 `--dry-run`，需要 `--commit` 才落库；旧字段（sector / etfs）保留 |
| 前端 React Query keyseed 泄露 | Task 4.7 提供 `drilldownQueryKeys` 工厂统一管理 |
| Lens=chain 时根节点为空树 | Task 4.6 在 lens=chain 且无 chain_parent 边时返回空 children + 一个 warning 字段，前端显示 "暂无产业链视图" |

### A.3 上线后的下一步（不在本 Phase 范围）

- 把 XLE / XLF / XLV / XLI 各加一份 yaml 种子
- 给 `chain extension` 节点加专门的成分清单维护界面
- 给节点分数加 cron 定时计算（每日盘后）

---

## 附录 B：与现有代码的兼容关系

### B.1 复用清单

| 现有模块 | 复用方式 |
|---------|---------|
| `etf_score.py:rank_percentile_normalize` | Task 4.4 横截面标准化 |
| `etf_score.py:ETFScoreCalculator` | Task 4.4 复用 trend / breadth / options 子函数 |
| `momentum.py:MomentumCalculator` | Task 4.4 复用 RS / RelMom 计算 |
| `series_utils.py:build_metric_series` | Task 4.6 节点 trend-comparison 端点 |
| `RelativeTrendChart.tsx` | Task 4.9 NodeTrendChart 风格对齐参考 |
| `getMarketRegime` API | Task 4.9 RegimeBadge |

### B.2 不动清单（明确禁止）

- `regime_gate.py`（Phase 2 任务范围）
- `momentum_pool.py`（Phase 1 任务范围）
- `stock_score.py`（Phase 1 任务范围）
- `ETFDetailCard.tsx`（rotation/momentum 仍在用）
- `CoreTerminal.tsx`（与下钻无关）

### B.3 旧字段的最终归宿

- `Task.sector / Task.etfs` 在 Phase 4 保留向后兼容；Phase 5 视情况打 deprecated 标签
- `INDUSTRY_ETFS` 常量在 Task 4.11 删除

---

> 完成本 Phase 后，板块下钻从 **ETF 列表** 升级为 **节点图谱**，新框架可无缝复制到 XLE / XLF / XLV / 工业链 / AI 基建链等任意根节点。
