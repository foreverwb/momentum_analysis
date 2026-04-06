"""RankBuffer 换手控制模块测试"""

import pytest

from app.services.calculators.rank_buffer import (
    RankBuffer,
    RankBufferConfig,
    RankBufferState,
)


@pytest.fixture
def buffer() -> RankBuffer:
    return RankBuffer(RankBufferConfig(
        entry_top_k=4,
        exit_top_m=6,
        confirmation_days=3,
        trend_quality_exit_threshold=50.0,
    ))


RANKED = ["XLK", "XLF", "XLV", "XLI", "XLE", "XLU", "XLB", "XLC", "XLY", "XLP", "XLRE"]
TQ_MAP = {s: 80.0 for s in RANKED}


# ---- 1. 基本进入 ----

def test_entry_after_confirmation(buffer: RankBuffer):
    """连续 3 次 update 排名在 Top 4 → 第 3 次后加入 current_holdings"""
    state = RankBufferState.empty()

    state = buffer.update(RANKED, TQ_MAP, state)
    assert "XLK" not in state.current_holdings
    assert state.entry_candidates.get("XLK") == 1

    state = buffer.update(RANKED, TQ_MAP, state)
    assert "XLK" not in state.current_holdings
    assert state.entry_candidates.get("XLK") == 2

    state = buffer.update(RANKED, TQ_MAP, state)
    assert "XLK" in state.current_holdings
    assert "XLK" not in state.entry_candidates


# ---- 2. 进入中断 ----

def test_entry_interrupted_resets_count(buffer: RankBuffer):
    """第 1、2 次在 Top 4，第 3 次跌出 → 重置计数"""
    state = RankBufferState.empty()

    state = buffer.update(RANKED, TQ_MAP, state)
    state = buffer.update(RANKED, TQ_MAP, state)
    assert state.entry_candidates.get("XLK") == 2

    # 第 3 次 XLK 跌到第 5 位（不在 top_k=4）
    ranked_drop = ["XLF", "XLV", "XLI", "XLE", "XLK", "XLU", "XLB"]
    state = buffer.update(ranked_drop, TQ_MAP, state)

    assert "XLK" not in state.current_holdings
    assert "XLK" not in state.entry_candidates


# ---- 3. 基本退出 ----

def test_exit_when_out_of_top_m_and_low_tq(buffer: RankBuffer):
    """已持有行业跌出 Top 6 且 TQ < 50 → 被剔除"""
    state = RankBufferState(current_holdings=["XLK"])

    # XLK 排到第 7 位 → 不在 top_m=6
    ranked_drop = ["XLF", "XLV", "XLI", "XLE", "XLU", "XLB", "XLK"]
    tq_low = {s: 80.0 for s in ranked_drop}
    tq_low["XLK"] = 30.0  # 低于 50

    state = buffer.update(ranked_drop, tq_low, state)
    assert "XLK" not in state.current_holdings


# ---- 4. 缓冲保护 ----

def test_buffer_protection_within_top_m(buffer: RankBuffer):
    """已持有行业排名第 5（在 Top 6 内）→ 不剔除"""
    state = RankBufferState(current_holdings=["XLK"])

    # XLK 排第 5 → 仍在 top_m=6
    ranked = ["XLF", "XLV", "XLI", "XLE", "XLK", "XLU", "XLB"]
    tq_low = {s: 30.0 for s in ranked}

    state = buffer.update(ranked, tq_low, state)
    assert "XLK" in state.current_holdings


# ---- 5. 趋势保护 ----

def test_trend_protection_high_tq(buffer: RankBuffer):
    """已持有行业跌出 Top 6 但 TQ=75 → 不剔除"""
    state = RankBufferState(current_holdings=["XLK"])

    ranked_drop = ["XLF", "XLV", "XLI", "XLE", "XLU", "XLB", "XLK"]
    tq_high = {s: 80.0 for s in ranked_drop}
    tq_high["XLK"] = 75.0  # 高于 50

    state = buffer.update(ranked_drop, tq_high, state)
    assert "XLK" in state.current_holdings


# ---- 6. 序列化往返 ----

def test_serialization_roundtrip():
    """state → to_json → from_json → 状态完全一致"""
    state = RankBufferState(
        current_holdings=["XLK", "XLF"],
        entry_candidates={"XLV": 2, "XLI": 1},
        last_update="2026-04-07",
    )

    json_str = state.to_json()
    restored = RankBufferState.from_json(json_str)

    assert restored.current_holdings == state.current_holdings
    assert restored.entry_candidates == state.entry_candidates
    assert restored.last_update == state.last_update


# ---- 7. 空状态初始化 ----

def test_empty_state():
    """RankBufferState.empty() → current_holdings 为空列表"""
    state = RankBufferState.empty()

    assert state.current_holdings == []
    assert state.entry_candidates == {}
    assert state.last_update is None
