"""
Rank Buffer — 行业/个股换手控制模块

通过确认天数和缓冲区机制，减少频繁换手：
- 新进入：连续 confirmation_days 日排名在 Top K 才纳入
- 退出：跌出 Top M（M > K）且趋势质量 < 阈值才剔除
- 不在 Top K 中则重置确认计数
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class RankBufferConfig:
    """换手控制配置"""

    entry_top_k: int = 4
    """进入门槛：排名需在前 K 名"""

    exit_top_m: int = 6
    """退出门槛：跌出前 M 名才触发退出检查（M > K）"""

    confirmation_days: int = 3
    """确认天数：连续 N 日在 Top K 才纳入"""

    trend_quality_exit_threshold: float = 50.0
    """退出趋势质量阈值：TQ 低于此值才允许退出"""


@dataclass
class RankBufferState:
    """换手缓冲状态"""

    current_holdings: List[str] = field(default_factory=list)
    """当前持仓列表"""

    entry_candidates: Dict[str, int] = field(default_factory=dict)
    """待确认候选 {symbol: 累积天数}"""

    last_update: Optional[str] = None
    """最后更新日期 ISO 格式"""

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> RankBufferState:
        """从 JSON 字符串反序列化

        Args:
            json_str: JSON 格式的状态字符串

        Returns:
            RankBufferState 实例
        """
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def empty(cls) -> RankBufferState:
        """创建空状态

        Returns:
            current_holdings 为空列表的初始状态
        """
        return cls()


class RankBuffer:
    """排名缓冲器 — 纯计算类，不访问数据库

    Args:
        config: 换手控制配置，为 None 时使用默认值
    """

    def __init__(self, config: RankBufferConfig | None = None) -> None:
        self.config = config or RankBufferConfig()

    def update(
        self,
        ranked_symbols: List[str],
        trend_quality_map: Dict[str, float],
        state: RankBufferState,
    ) -> RankBufferState:
        """根据当日排名更新缓冲状态

        Args:
            ranked_symbols: 按排名从高到低排列的 symbol 列表
            trend_quality_map: {symbol: trend_quality_score} 趋势质量映射
            state: 当前缓冲状态

        Returns:
            更新后的新 RankBufferState
        """
        cfg = self.config
        top_k = set(ranked_symbols[:cfg.entry_top_k])
        top_m = set(ranked_symbols[:cfg.exit_top_m])

        new_holdings = list(state.current_holdings)
        new_candidates = dict(state.entry_candidates)

        # --- 退出检查 ---
        for symbol in list(new_holdings):
            if symbol not in top_m:
                tq = trend_quality_map.get(symbol, 0.0)
                if tq < cfg.trend_quality_exit_threshold:
                    new_holdings.remove(symbol)

        # --- 进入检查 ---
        for symbol in top_k:
            if symbol in new_holdings:
                # 已持有，无需处理
                new_candidates.pop(symbol, None)
                continue
            # 累积确认天数
            new_candidates[symbol] = new_candidates.get(symbol, 0) + 1
            if new_candidates[symbol] >= cfg.confirmation_days:
                new_holdings.append(symbol)
                new_candidates.pop(symbol)

        # --- 重置不在 top_k 的候选 ---
        for symbol in list(new_candidates):
            if symbol not in top_k:
                del new_candidates[symbol]

        return RankBufferState(
            current_holdings=new_holdings,
            entry_candidates=new_candidates,
            last_update=state.last_update,
        )

    def get_active_holdings(self, state: RankBufferState) -> List[str]:
        """获取当前活跃持仓列表

        Args:
            state: 当前缓冲状态

        Returns:
            当前持仓 symbol 列表
        """
        return list(state.current_holdings)

    def get_pending_entries(self, state: RankBufferState) -> Dict[str, str]:
        """获取待确认候选及其进度

        Args:
            state: 当前缓冲状态

        Returns:
            {symbol: "N/M"} 格式的确认进度映射
        """
        total = self.config.confirmation_days
        return {
            symbol: f"{days}/{total}"
            for symbol, days in state.entry_candidates.items()
        }
