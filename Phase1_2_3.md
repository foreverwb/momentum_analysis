# momentum_analysis 升级实施任务

> 每个 Task 是一个独立的、可交付给 Claude Opus/Sonnet 的完整任务指令。
> 按顺序执行，后续 Task 依赖前序 Task 的产出。

---

# Phase 1：核心评分引擎统一

## Task 1.1 — 将 momentum_pool.py 升级为唯一个股评分引擎

### 背景

当前项目有两个个股评分模块：
- `backend/app/services/calculators/stock_score.py`：权重 40/30/20/10（技术/动量/成交量/期权），使用二值评分（收益 > 0 给 25 分，否则 0 分）
- `backend/app/services/calculators/momentum_pool.py`：权重 0.65*(mom+trend)/2 + 0.15*vol + 0.20*options，有质量惩罚机制

两个模块做同一件事但逻辑不同，需要统一。`momentum_pool.py` 更接近目标设计，以它为基础升级。

### 目标

1. 将 `momentum_pool.py` 的权重调整为：

```
PriceMom  = 0.40  （价格动量）
TrendStr  = 0.25  （趋势结构）
VolScore  = 0.15  （量价确认）
OptionsOv = 0.20  （期权叠加）
```

2. 将动量评分从二值改为连续值。当前代码（L237-244）：
```python
# ❌ 当前：二值，0.1% 和 15% 得分相同
momentum_score += 25 if return_5d > 0 else 0
momentum_score += 25 if return_20d > 0 else 0
```

改为返回连续原始值：
```python
# ✅ 改为：连续值，后续横截面标准化时区分
momentum_raw = {
    'abs_mom': 0.60 * (return_20d_ex3d or 0) + 0.40 * (return_63d or 0),
    'rel_strength': rs_diff_20d or 0,
    'prox_high': distance_ratio or 0,  # 已有：L229
}
```

3. 将质量惩罚从阶梯式改为乘法叠加：

当前代码（L273-279）：
```python
# ❌ 当前：阶梯式
if quality_score < 40: penalty_factor = 0.85
elif quality_score < 60: penalty_factor = 0.90
```

改为：
```python
# ✅ 改为：多条件乘法叠加
quality_adj = 1.0
# 波动率过高：过去 20 日年化波动率 > 行业中位数 * 1.5
if atr_pct is not None and atr_pct > 0.03:  # ATR% > 3% ≈ 年化波动 > 47%
    quality_adj *= 0.70
# 回撤过大：20 日 MDD > 15%
if analysis.max_drawdown_20d < -0.15:
    quality_adj *= 0.60
# 过热：偏离 20DMA > 10%
if deviation_pct is not None and deviation_pct > 0.10:
    quality_adj *= 0.80
quality_adj = max(quality_adj, 0.40)  # 底线
```

### 需要修改的文件

- `backend/app/services/calculators/momentum_pool.py`（主要修改）

### 约束

- 保持 `calculate_momentum_pool_result` 函数签名不变（输入：price_df, sector_df, finviz_data, mc_data, iv_data）
- 保持 `MomentumPoolResult` dataclass 结构不变（total_score, scores, metrics）
- `scores` dict 的 key 改为 `{'price_mom', 'trend', 'volume', 'options', 'quality_adj'}`（旧 key `momentum` 改名为 `price_mom`）
- `metrics` dict 保持向后兼容，新增字段而非删除
- 运行已有测试 `backend/tests/test_momentum_calculator.py` 确保不破坏现有功能

### 验证标准

- 两只收益率差异大的股票（如 return_20d = +0.1% vs +15%）在 `price_mom` 维度得到显著不同的原始分
- 质量惩罚可叠加：同时满足"高波动 + 过热"时 quality_adj = 0.70 * 0.80 = 0.56
- 所有现有测试通过

---

## Task 1.2 — 为 momentum_pool.py 增加批量横截面标准化

### 背景

当前 `momentum_pool.py` 的 `calculate_momentum_pool_result` 只处理单只股票。评分是"绝对值映射"（如 return > 0 给 25 分），没有横截面比较。

`etf_score.py` 已有成熟的横截面标准化函数 `rank_percentile_normalize`（L71-101），对所有行业的 raw 值做 winsorize 后的 rank percentile 归一化到 0-100。

### 目标

新建一个批量入口函数 `batch_calculate_momentum_pool`，流程如下：

```
1. 对每只股票调用内部函数获取 raw_features（连续值）
2. 收集所有股票的 raw_features 做横截面 rank_percentile_normalize
3. 用标准化后的分数加权合成 total_score
4. 乘以 quality_adj
5. 按 total_score 降序排列返回
```

### 需要修改的文件

- `backend/app/services/calculators/momentum_pool.py`（新增 `batch_calculate_momentum_pool` 函数）
- 从 `etf_score.py` 导入 `rank_percentile_normalize`

### 具体要求

```python
from .etf_score import rank_percentile_normalize

def batch_calculate_momentum_pool(
    stock_data_map: Dict[str, Dict[str, Any]],
    # stock_data_map = {
    #     'NVDA': {'price_df': df, 'sector_df': df, 'finviz_data': {}, 'mc_data': {}, 'iv_data': {}},
    #     'AMD': {...},
    # }
) -> List[Dict[str, Any]]:
    """
    批量计算动能股池评分，带横截面标准化。

    Returns:
        按 total_score 降序排列的结果列表，每项包含：
        {
            'symbol': str,
            'total_score': float,          # 标准化后加权合成 × quality_adj
            'raw_scores': Dict[str, float], # 标准化前的原始分
            'norm_scores': Dict[str, float],# 标准化后的 0-100 分
            'quality_adj': float,           # 质量调整系数
            'scores': Dict[str, float],     # 兼容旧结构
            'metrics': Dict[str, Any],      # 兼容旧结构
        }
    """
```

### 内部流程

1. 遍历 `stock_data_map`，对每只股票调用 Task 1.1 中改造的内部逻辑，拿到 `raw_features`：
   - `price_mom_raw`: float（连续值）
   - `trend_raw`: float
   - `volume_raw`: float
   - `options_raw`: float
   - `quality_adj`: float

2. 收集所有股票的 raw 值做横截面标准化：
```python
price_mom_map = {sym: data['price_mom_raw'] for sym, data in raw_results.items()}
price_mom_norm = rank_percentile_normalize(price_mom_map, winsorize_limits=(0.05, 0.95))
# 同理 trend, volume, options
```

3. 合成 total_score：
```python
total = (
    0.40 * price_mom_norm[sym] +
    0.25 * trend_norm[sym] +
    0.15 * volume_norm[sym] +
    0.20 * options_norm[sym]
) * quality_adj[sym]
```

### 约束

- 保留原有的 `calculate_momentum_pool_result` 函数不删除（单股评分仍然可用）
- 批量函数内部复用单股计算的子函数，不重复实现
- 如果样本数 < 3，退化为单股评分模式（横截面标准化在小样本时不可靠）

### 验证标准

- 5 只股票批量评分后，每个维度的 norm_scores 分布在 0-100 且总和无显著偏差
- 单股调用 `calculate_momentum_pool_result` 和批量调用中同一股票结果的 `metrics` 字段一致

---

## Task 1.3 — 统一 API 层调用，废弃 stock_score.py 的评分逻辑

### 背景

当前 API 层 `backend/app/api/stocks.py` 同时调用 `stock_score.py` 和 `momentum_pool.py`。需要统一到 `momentum_pool.py` 的批量评分。

### 目标

1. 修改 `backend/app/api/stocks.py`，将所有个股评分调用替换为 `batch_calculate_momentum_pool`
2. `stock_score.py` 中**保留** `_calculate_technical_from_finviz` 方法（Finviz 数据适配器），其余评分方法标记为 `@deprecated`
3. 确保前端不受影响：API 返回字段保持向后兼容

### 需要修改的文件

- `backend/app/api/stocks.py`（主要修改）
- `backend/app/services/calculators/stock_score.py`（添加 deprecation 注释，不删除代码）
- `backend/app/services/orchestrator.py`（如果评分调用经过编排器）

### 具体要求

1. 在 `stocks.py` 中找到所有调用 `StockScoreCalculator.batch_calculate_scores` 或 `calculate_composite_score` 的地方
2. 替换为调用 `batch_calculate_momentum_pool`
3. 返回结构要确保包含前端需要的字段。检查前端 `StockCard.tsx`、`StockDetailView.tsx`、`ScoreBreakdownPanel.tsx` 使用了哪些字段，确保兼容
4. 在 `stock_score.py` 头部添加注释：

```python
"""
⚠️ DEPRECATED: 评分逻辑已迁移到 momentum_pool.py
本模块仅保留 _calculate_technical_from_finviz 作为 Finviz 数据适配器。
请使用 momentum_pool.batch_calculate_momentum_pool 进行个股评分。
"""
```

### 约束

- 不删除 `stock_score.py` 中任何代码（只添加 deprecation 注释），因为可能有测试依赖
- 所有现有测试必须通过：`pytest backend/tests/ -v`

### 验证标准

- `GET /api/stocks/{task_id}/scores` 返回的 JSON 结构不变，前端正常渲染
- 同一组股票的评分结果来自 `momentum_pool.py` 而非 `stock_score.py`

---

# Phase 2：Regime Gate 与排名缓冲

## Task 2.1 — Regime Gate 增加滞后保护（Hysteresis）

### 背景

当前 `regime_gate.py` 的 `calculate_regime` 是无状态的，每次调用根据当天快照直接判断 A/B/C。当 SPY 在 50DMA 附近震荡时，状态会在 A/B 之间日内反复切换。

需要增加：
1. **确认天数**：状态变化需连续 3 个交易日满足条件才执行切换
2. **冷却期**：切换后 5 个交易日内不再切换

注意：前端 `CoreTerminal.tsx` 的 `computeRegime()` 是客户端实时计算（用于 UI 即时反馈），不受后端滞后保护影响。滞后保护只作用于后端持久化的 regime 状态（用于驱动行业选择和仓位决策）。

### 需要修改的文件

- `backend/app/models/database.py`（新增 `RegimeStateHistory` 表）
- `backend/app/services/calculators/regime_gate.py`（新增带滞后的方法）
- `backend/app/api/market.py`（regime 端点写入历史记录）

### 具体要求

#### 1. 数据库新增表

在 `database.py` 中新增：

```python
class RegimeStateHistory(Base):
    """Regime 状态变更历史"""
    __tablename__ = 'regime_state_history'

    id = Column(Integer, primary_key=True)
    record_date = Column(Date, nullable=False, index=True)
    raw_status = Column(String(1), nullable=False)       # 原始计算结果 A/B/C
    effective_status = Column(String(1), nullable=False)  # 滞后处理后的实际状态
    consecutive_days = Column(Integer, default=1)         # 当前状态连续天数
    days_since_switch = Column(Integer, default=999)      # 距上次切换的天数
    pending_switch_to = Column(String(1), nullable=True)  # 待确认的目标状态
    confirmation_progress = Column(Integer, default=0)    # 确认进度（0/3）
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('record_date', name='uix_regime_state_date'),
    )
```

#### 2. regime_gate.py 新增方法

在 `RegimeGateCalculator` 类中新增：

```python
CONFIRMATION_DAYS = 3
COOLDOWN_AFTER_SWITCH = 5

def calculate_regime_with_hysteresis(
    self,
    previous_effective_status: str = 'B',
    confirmation_progress: int = 0,
    days_since_last_switch: int = 999,
) -> Dict:
    """
    带滞后保护的 Regime 计算。

    Args:
        previous_effective_status: 上一个交易日的实际生效状态
        confirmation_progress: 当前已累积的确认天数
        days_since_last_switch: 距上次状态切换的天数

    Returns:
        dict: {
            'raw_status': str,           # 原始计算结果
            'effective_status': str,     # 滞后处理后的生效状态
            'switched': bool,            # 是否发生了切换
            'pending_switch_to': str|None,
            'confirmation_progress': int,
            'regime_locked': bool,       # 是否在冷却期内
            'data': dict,                # 原始 regime 数据
        }
    """
```

逻辑：
1. 调用 `self.calculate_regime()` 获取 `raw_status`
2. 如果 `days_since_last_switch < COOLDOWN_AFTER_SWITCH`：返回 `effective_status = previous_effective_status`，标记 `regime_locked = True`
3. 如果 `raw_status == previous_effective_status`：重置 `confirmation_progress = 0`，返回不变
4. 如果 `raw_status != previous_effective_status`：
   - `confirmation_progress += 1`
   - 如果 `confirmation_progress >= CONFIRMATION_DAYS`：执行切换，`effective_status = raw_status`，`days_since_last_switch = 0`
   - 否则：`effective_status = previous_effective_status`，`pending_switch_to = raw_status`

#### 3. market.py 集成

在 `GET /api/market/regime?refresh=true` 的处理逻辑中：
1. 读取最近一条 `RegimeStateHistory` 获取 previous 状态
2. 调用 `calculate_regime_with_hysteresis`
3. 写入新的 `RegimeStateHistory` 记录
4. 在返回的 JSON 中增加 `hysteresis` 字段（不影响现有字段）：

```json
{
    "status": "A",
    "regime_text": "RISK_ON 满火力",
    "hysteresis": {
        "raw_status": "B",
        "effective_status": "A",
        "regime_locked": false,
        "pending_switch_to": "B",
        "confirmation_progress": "1/3"
    }
}
```

### 约束

- 现有 `calculate_regime()` 方法不修改（保持无状态可单独调用）
- 前端 `computeRegime()` 不受影响（它始终使用无状态实时计算）
- 数据库迁移需用 `Base.metadata.create_all(engine)` 自动建表（项目已有此模式）
- 所有现有测试通过

### 验证标准

- 模拟 SPY 在 50DMA 附近 5 天震荡：raw_status 在 A/B 间切换，但 effective_status 保持不变
- 连续 3 天 raw_status = C → effective_status 从 B 切换到 C
- 切换后 5 天内即使 raw_status 变回 A，effective_status 仍为 C

---

## Task 2.2 — VIX 硬性降档

### 背景

当前 `regime_gate.py` 注释明确说"VIX 仅用于参考展示，不参与档位切换"（L14）。需要将 VIX > 30 作为硬性降档条件。

### 需要修改的文件

- `backend/app/services/calculators/regime_gate.py`

### 具体要求

在 `calculate_regime` 方法的判断逻辑（L247-274）中，在现有判断之前插入 VIX 检查：

```python
# 在 risk_off 变量计算之后、regime 判断之前：
vix_extreme = safe_vix is not None and safe_vix > 30
vix_elevated = safe_vix is not None and safe_vix > 25

# 修改判断逻辑：
if risk_off:
    status, regime, fire_power = 'C', 'RISK_OFF', '低火力/空仓'
elif vix_extreme:
    # VIX > 30 强制降到 B（即使价格在 50DMA 上方）
    status, regime, fire_power = 'B', 'NEUTRAL', '半火力'
elif near_50dma:
    status, regime, fire_power = 'B', 'NEUTRAL', '半火力'
elif risk_on:
    if vix_elevated:
        # VIX 25-30 区间：从满火力降为谨慎满火力（不影响状态码）
        status, regime, fire_power = 'A', 'RISK_ON', '满火力（VIX偏高）'
    else:
        status, regime, fire_power = 'A', 'RISK_ON', '满火力'
else:
    status, regime, fire_power = 'B', 'NEUTRAL', '半火力'
```

同时更新 `THRESHOLDS` 常量：

```python
THRESHOLDS = {
    'vix_low': 15,
    'vix_high': 25,
    'vix_extreme': 30,       # 新增
    'return_20d_bad': 0.0,
}
```

更新模块顶部注释（L14）：

```python
# - VIX > 30: 强制降档到 B (NEUTRAL)
# - VIX 25-30: 不影响状态码，但标记"VIX偏高"
```

### 约束

- 在 `RegimeData` dataclass 中增加 `vix_override: Optional[str]` 字段，记录 VIX 是否触发了降档
- 所有现有测试通过
- 新增测试用例：VIX=35 + 价格在 50DMA 上方 → 状态 = B

### 验证标准

- VIX=20, 价格在 50DMA 上方, 斜率正 → A
- VIX=28, 价格在 50DMA 上方, 斜率正 → A（标记 VIX 偏高）
- VIX=35, 价格在 50DMA 上方, 斜率正 → B（VIX 强制降档）
- VIX=35, 价格在 50DMA 下方, 收益为负 → C（risk_off 优先于 vix_extreme）

---

## Task 2.3 — 排名缓冲模块（Rank Buffer）

### 背景

当前 `etf_score.py` 的 `get_top_etfs` 方法每次调用都重新排名取 Top N，没有任何缓冲。文档要求：
- 已持有行业跌出 Top 4 但仍在 Top 6 → 保留
- 跌出 Top 6 且趋势质量 < 50 → 剔除
- 新进入行业需连续 3 日排名在 Top 4

### 需要新建/修改的文件

- **新建** `backend/app/services/calculators/rank_buffer.py`
- `backend/app/models/database.py`（新增 `RankBufferRecord` 表）
- `backend/app/services/calculators/__init__.py`（导出新模块）

### 具体要求

#### 1. 新建 `rank_buffer.py`

```python
"""
排名缓冲器 (Rank Buffer)

控制行业/个股换手频率，避免因排名抖动导致频繁切换。

规则：
- entry_top_k: 进入 Top K 才开始计算确认天数（默认 4）
- exit_top_m: 跌出 Top M 且趋势质量差才剔除（默认 6, M > K）
- confirmation_days: 连续 N 日在 Top K 才正式纳入（默认 3）
- forced_exit: 跌破关键均线且连续 N 日未收回 → 立即剔除

使用场景：
- 行业排名缓冲：每周更新行业篮子
- 个股排名缓冲：每日更新动能股池
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set
from datetime import date
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class RankBufferConfig:
    """排名缓冲配置"""
    entry_top_k: int = 4
    exit_top_m: int = 6
    confirmation_days: int = 3
    trend_quality_exit_threshold: float = 50.0


@dataclass
class RankBufferState:
    """排名缓冲状态（持久化到数据库）"""
    current_holdings: List[str] = field(default_factory=list)
    entry_candidates: Dict[str, int] = field(default_factory=dict)  # {symbol: 累积确认天数}
    last_update: Optional[str] = None  # ISO date string

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> 'RankBufferState':
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def empty(cls) -> 'RankBufferState':
        return cls()


class RankBuffer:
    """排名缓冲器"""

    def __init__(self, config: RankBufferConfig = None):
        self.config = config or RankBufferConfig()

    def update(
        self,
        ranked_symbols: List[str],
        trend_quality_map: Dict[str, float],
        state: RankBufferState,
    ) -> RankBufferState:
        """
        每日/每周更新排名缓冲状态。

        Args:
            ranked_symbols: 按评分降序排列的所有行业/个股代码列表
            trend_quality_map: {symbol: trend_quality_score}，用于退出判断
            state: 上一次的缓冲状态

        Returns:
            更新后的 RankBufferState
        """
        cfg = self.config
        top_k_set = set(ranked_symbols[:cfg.entry_top_k])
        top_m_set = set(ranked_symbols[:cfg.exit_top_m])
        current = set(state.current_holdings)

        # === 退出检查 ===
        to_remove = set()
        for symbol in current:
            if symbol not in top_m_set:
                tq = trend_quality_map.get(symbol, 0)
                if tq < cfg.trend_quality_exit_threshold:
                    to_remove.add(symbol)
                    logger.info(
                        f"RankBuffer EXIT: {symbol} (out of Top {cfg.exit_top_m}, "
                        f"TQ={tq:.1f} < {cfg.trend_quality_exit_threshold})"
                    )
        current -= to_remove

        # === 进入检查 ===
        new_candidates: Dict[str, int] = {}
        for symbol in top_k_set:
            if symbol in current:
                continue  # 已持有，不需要确认
            prev_days = state.entry_candidates.get(symbol, 0)
            new_days = prev_days + 1
            if new_days >= cfg.confirmation_days:
                current.add(symbol)
                logger.info(
                    f"RankBuffer ENTRY: {symbol} (confirmed {new_days}/{cfg.confirmation_days} days)"
                )
            else:
                new_candidates[symbol] = new_days
                logger.debug(
                    f"RankBuffer PENDING: {symbol} ({new_days}/{cfg.confirmation_days})"
                )

        # 不在 Top K 中的候选人重置（连续性中断）
        # new_candidates 只包含本轮仍在 top_k 中的未确认候选

        return RankBufferState(
            current_holdings=sorted(current),
            entry_candidates=new_candidates,
            last_update=date.today().isoformat(),
        )

    def get_active_holdings(self, state: RankBufferState) -> List[str]:
        """获取当前活跃持仓列表"""
        return list(state.current_holdings)

    def get_pending_entries(self, state: RankBufferState) -> Dict[str, str]:
        """获取待确认的进入候选，返回 {symbol: 'N/M'}"""
        return {
            sym: f"{days}/{self.config.confirmation_days}"
            for sym, days in state.entry_candidates.items()
        }
```

#### 2. 数据库新增表

在 `database.py` 中新增：

```python
class RankBufferRecord(Base):
    """排名缓冲状态持久化"""
    __tablename__ = 'rank_buffer_records'

    id = Column(Integer, primary_key=True)
    buffer_type = Column(String(20), nullable=False, index=True)  # 'sector' / 'industry' / 'stock'
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=True)
    state_json = Column(Text, nullable=False)  # RankBufferState 序列化
    config_json = Column(Text, nullable=True)  # RankBufferConfig 序列化
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('buffer_type', 'task_id', name='uix_rank_buffer_type_task'),
    )
```

#### 3. 更新 __init__.py

在 `backend/app/services/calculators/__init__.py` 中导出：

```python
from .rank_buffer import RankBuffer, RankBufferConfig, RankBufferState
```

### 约束

- `RankBuffer` 是纯计算类，不直接访问数据库（数据库读写在 API 层完成）
- 状态通过 `RankBufferState.to_json()` / `from_json()` 序列化
- 新增单元测试文件 `backend/tests/test_rank_buffer.py`

### 验证标准（需在测试中覆盖）

1. **基本进入**：某行业连续 3 次 update 都在 Top 4 → 第 3 次后加入 current_holdings
2. **进入中断**：某行业第 1、2 次在 Top 4，第 3 次跌出 → 重置计数，不加入
3. **基本退出**：已持有行业跌出 Top 6 且 TQ < 50 → 被剔除
4. **缓冲保护**：已持有行业排名第 5（在 Top 6 内但不在 Top 4）→ 不剔除
5. **趋势保护**：已持有行业跌出 Top 6 但 TQ = 75 → 不剔除（趋势仍好）
6. **序列化**：state → JSON → 反序列化 → 状态完全一致

---

# Phase 3：评分公式优化

## Task 3.1 — RelMom 计算跳过最近 1 周

### 背景

当前 `momentum.py` L48-51 的 RS 变化直接用 `pct_change(5/20/63)`，没有跳过最近 1 周。学术文献和实操经验表明，跳过最近 1 周能减少短期反转效应对动量信号的噪声。

### 需要修改的文件

- `backend/app/services/calculators/momentum.py`

### 具体要求

修改 `calculate_relative_strength` 方法（L21-52）：

**当前代码：**
```python
merged["RS_5D_change"] = cls._clean_series(merged["RS"].pct_change(5))
merged["RS_20D_change"] = cls._clean_series(merged["RS"].pct_change(20))
merged["RS_63D_change"] = cls._clean_series(merged["RS"].pct_change(63))
```

**改为：**
```python
SKIP = 5  # 跳过最近 1 周（5 个交易日）
rs = merged["RS"]

# 跳过最近 1 周的多周期 RS 变化
merged["RS_20D_change"] = cls._clean_series(
    (rs.shift(SKIP) - rs.shift(SKIP + 20)) / rs.shift(SKIP + 20)
)
merged["RS_63D_change"] = cls._clean_series(
    (rs.shift(SKIP) - rs.shift(SKIP + 63)) / rs.shift(SKIP + 63)
)

# 加速项：最近 5 天的 RS 变化（不跳过，用于捕捉近期加速）
merged["RS_5D_change"] = cls._clean_series(rs.pct_change(5))
```

同时修改 `calculate_rel_mom` 方法（L55-75）中的注释，说明权重含义：

```python
result["RelMom"] = (
    result["RS_5D_change"] * 0.20   # 近期加速确认（不跳过）
    + result["RS_20D_change"] * 0.45  # 主要动量信号（跳过最近 1 周）
    + result["RS_63D_change"] * 0.35  # 长期趋势锚（跳过最近 1 周）
)
```

### 约束

- `RS_5D_change` 的列名保持不变（前端/API 可能依赖）
- 新增 `RS_5D_accel` 列作为别名（可选，方便语义理解）
- 已有测试 `test_momentum_calculator.py` 必须通过（可能需要调整期望值）

### 验证标准

- 构造测试数据：最近 5 天 RS 暴跌但之前 20 天稳步上升 → RS_20D_change 仍为正值（因为跳过了最近 5 天）
- RS_5D_change 反映近期加速/减速（不受 skip 影响）

---

## Task 3.2 — 广度评分增加"等权 vs 市值权重"对比

### 背景

当前 `etf_score.py` 的广度评分只用了 3 个指标：%Above50DMA, %Above20DMA, %Near52WH。需要增加第四个：等权收益 vs 市值权重收益的偏差，用于识别"巨头独涨"的集中度风险。

### 需要修改的文件

- `backend/app/services/parsers/finviz_parser.py`（`calculate_breadth_metrics` 函数）
- `backend/app/services/calculators/etf_score.py`（`BREADTH_RAW_WEIGHTS` 和 `calculate_breadth_score`）

### 具体要求

#### 1. finviz_parser.py

在 `calculate_breadth_metrics` 函数的返回字典中新增 `ew_vs_mw_spread` 字段：

```python
# 等权收益 vs 加权收益
returns = [h.get('perf_month') for h in holdings_data if h.get('perf_month') is not None]
market_caps = [h.get('market_cap') for h in holdings_data if h.get('market_cap') is not None]

if returns and len(returns) >= 3:
    ew_return = sum(returns) / len(returns)
    if market_caps and len(market_caps) == len(returns) and sum(market_caps) > 0:
        total_cap = sum(market_caps)
        mw_return = sum(r * c for r, c in zip(returns, market_caps)) / total_cap
    else:
        mw_return = ew_return

    # 正值 → 等权跑赢 → 多数股票在涨 → 广度健康
    # 负值 → 市值权重跑赢 → 巨头独涨 → 集中度风险
    ew_vs_mw_spread = (ew_return - mw_return) if mw_return != 0 else 0
else:
    ew_vs_mw_spread = 0

breadth['ew_vs_mw_spread'] = ew_vs_mw_spread
```

#### 2. etf_score.py

修改权重配置：

```python
BREADTH_RAW_WEIGHTS = {
    'pct_above_sma50': 0.35,      # 从 0.50 降为 0.35
    'pct_above_sma20': 0.25,      # 从 0.30 降为 0.25
    'pct_near_52w_high': 0.15,    # 从 0.20 降为 0.15
    'ew_vs_mw_spread': 0.25,      # 新增
}
```

在 `calculate_breadth_score` 方法中增加对 `ew_vs_mw_spread` 的处理：

```python
ew_vs_mw = _safe_float(breadth.get('ew_vs_mw_spread')) or 0.0
# 将 spread 映射到 0-1 范围：
# spread = +5% → 1.0（非常健康）
# spread = 0%  → 0.5（中性）
# spread = -5% → 0.0（集中度风险）
ew_vs_mw_score = max(0.0, min(1.0, 0.5 + ew_vs_mw * 10))

breadth_raw = (
    self.BREADTH_RAW_WEIGHTS['pct_above_sma50'] * pct_above_50 +
    self.BREADTH_RAW_WEIGHTS['pct_above_sma20'] * pct_above_20 +
    self.BREADTH_RAW_WEIGHTS['pct_near_52w_high'] * pct_near_52w_high +
    self.BREADTH_RAW_WEIGHTS['ew_vs_mw_spread'] * ew_vs_mw_score
) * 100.0
```

在返回的 `data` dict 中增加：
```python
'ew_vs_mw_spread': round(ew_vs_mw, 4),
'ew_vs_mw_score': round(ew_vs_mw_score, 4),
```

### 约束

- 如果 Finviz 数据中没有 `market_cap` 字段，`ew_vs_mw_spread` 默认为 0（不影响评分）
- 已有测试通过

### 验证标准

- 构造测试数据：10 只成分股，NVDA 涨 20%（权重 30%），其他 9 只平均跌 2% → `ew_vs_mw_spread` 为负值 → breadth 评分降低

---

## Task 3.3 — 个股硬性门槛补齐

### 背景

当前 `stock_score.py` 的门槛只有 `Price > SMA50`（硬性）和 `RS > 0`（软性）。需要补齐到 5 个门槛。

由于 Phase 1 中个股评分已迁移到 `momentum_pool.py`，此任务在 `momentum_pool.py` 中实现门槛检查。

### 需要修改的文件

- `backend/app/services/calculators/momentum_pool.py`

### 具体要求

在 `calculate_momentum_pool_result` 函数中（或 `batch_calculate_momentum_pool` 中），增加门槛检查逻辑，在结果中增加 `thresholds` 字段：

```python
# 门槛定义
STOCK_THRESHOLDS = {
    'price_above_sma20': True,          # P > SMA20
    'sma20_above_sma50': True,          # SMA20 > SMA50（趋势结构完整）
    'min_avg_dollar_volume': 500_000,   # 20日平均日成交额 > $500K
    'min_market_cap': 1_000_000_000,    # 市值 > $1B
}

def check_stock_thresholds(
    analysis: TechnicalAnalysisResult,
    finviz_data: Optional[Dict] = None,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, str]:
    """
    检查个股硬性门槛。

    Returns:
        {
            'all_pass': bool,
            'details': {
                'price_above_sma20': 'PASS' | 'FAIL' | 'NO_DATA',
                'sma20_above_sma50': 'PASS' | 'FAIL' | 'NO_DATA',
                'min_dollar_volume': 'PASS' | 'FAIL' | 'NO_DATA',
                'min_market_cap': 'PASS' | 'FAIL' | 'NO_DATA',
            }
        }
    """
    results = {}
    all_pass = True

    # 1. P > SMA20
    p_above_20 = analysis.price > analysis.sma20 if analysis.sma20 else None
    results['price_above_sma20'] = 'PASS' if p_above_20 else ('FAIL' if p_above_20 is False else 'NO_DATA')
    if not p_above_20:
        all_pass = False

    # 2. SMA20 > SMA50
    sma20_gt_50 = analysis.sma20 > analysis.sma50 if (analysis.sma20 and analysis.sma50) else None
    results['sma20_above_sma50'] = 'PASS' if sma20_gt_50 else ('FAIL' if sma20_gt_50 is False else 'NO_DATA')
    if not sma20_gt_50:
        all_pass = False

    # 3. 日均成交额 > $500K
    if price_df is not None and 'volume' in price_df.columns and 'close' in price_df.columns:
        recent = price_df.tail(20)
        avg_dollar_vol = (recent['close'] * recent['volume']).mean()
        vol_pass = avg_dollar_vol >= STOCK_THRESHOLDS['min_avg_dollar_volume']
        results['min_dollar_volume'] = 'PASS' if vol_pass else 'FAIL'
        if not vol_pass:
            all_pass = False
    else:
        results['min_dollar_volume'] = 'NO_DATA'

    # 4. 市值 > $1B
    if finviz_data and finviz_data.get('market_cap') is not None:
        cap_pass = finviz_data['market_cap'] >= STOCK_THRESHOLDS['min_market_cap']
        results['min_market_cap'] = 'PASS' if cap_pass else 'FAIL'
        if not cap_pass:
            all_pass = False
    else:
        results['min_market_cap'] = 'NO_DATA'

    return {'all_pass': all_pass, 'details': results}
```

在 `MomentumPoolResult` 或返回 dict 中增加 `thresholds` 字段。

### 约束

- 门槛不通过不影响评分计算（评分仍然算出来），但在结果中标记 `thresholds_pass = False`
- `NO_DATA` 时不算 FAIL（数据缺失不应阻止评分）
- 与前端 `ThresholdCard.tsx` 组件兼容

### 验证标准

- 小市值低流动性股票（如某 penny stock）→ `min_dollar_volume` = FAIL, `min_market_cap` = FAIL
- SMA20 < SMA50 的股票 → `sma20_above_sma50` = FAIL
- 无 Finviz 数据时 → `min_market_cap` = NO_DATA（不影响 all_pass 判断）

---

## Task 3.4 — ETF 广度硬性门槛调整

### 背景

当前 `etf_score.py` L578 使用 `pct_above_sma50 >= 0.50` 作为硬性门槛。在行业轮动初期，广度从 30-40% 开始攀升时这个门槛会错过早期进入机会。

### 需要修改的文件

- `backend/app/services/calculators/etf_score.py`

### 具体要求

1. 将 `THRESHOLDS` 中 `breadth_min` 从 `0.50` 改为 `0.40`：

```python
THRESHOLDS = {
    'price_above_sma50': True,
    'rs_20d_positive': True,
    'breadth_min': 0.40,   # 从 0.50 降为 0.40
}
```

2. 将 `check_thresholds` 方法中的阈值判断名称更新：

```python
# L574-582 原来的 key 是 'breadth_above_50'，改为 'breadth_above_40'
results['breadth_above_40'] = 'PASS' if breadth_pass else 'FAIL'
```

3. 注意前端引用了 `breadth_above_50` 这个 key 名。搜索前端代码确认是否需要同步修改：

```bash
grep -rn "breadth_above_50" frontend/src/
```

如果前端直接使用了该 key，同步修改前端对应位置。

### 约束

- 如果前端使用了硬编码的 `breadth_above_50` key，必须同步修改
- 所有现有测试通过（可能需要调整预期值）

### 验证标准

- pct_above_sma50 = 0.45 的行业 → 门槛通过（旧版会 FAIL）
- pct_above_sma50 = 0.35 的行业 → 门槛 FAIL

---

## Task 3.5 — SMA 斜率改为百分比

### 背景

`regime_gate.py` L203 调用 `calculate_sma_slope` 返回绝对值（每日变化量），`technical.py` 已有 `calculate_sma_slope_pct` 但未被使用。

### 需要修改的文件

- `backend/app/services/calculators/regime_gate.py`

### 具体要求

将 L203：

```python
sma20_slope = calculate_sma_slope(sma20, period=5)
```

改为：

```python
sma20_slope = calculate_sma_slope_pct(sma20, period=5)
```

同时确认所有使用 `sma20_slope` 做 `> 0` 判断的地方不受影响（百分比变化方向与绝对值一致）。

### 约束

- 只修改 `regime_gate.py` 中的调用
- `etf_score.py` 也使用 `calculate_sma_slope`（L306），如果时间允许也改为 `_pct` 版本
- 需更新 import：`from .technical import calculate_sma, calculate_sma_slope_pct, calculate_returns`

### 验证标准

- 所有现有测试通过
- sma20_slope 的正负方向不变（只是数值从绝对变化量变为百分比变化率）
