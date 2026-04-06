"""
Regime Gate hysteresis tests.

Scenarios:
1. SPY oscillates near 50DMA for 5 days: raw toggles A/B, effective stays stable
2. 3 consecutive days raw=C: effective switches from B to C
3. After switch, cooldown blocks further changes for 5 days
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from unittest.mock import MagicMock

from app.services.calculators.regime_gate import RegimeGateCalculator


def _make_calculator_with_status(status: str) -> RegimeGateCalculator:
    """Create a calculator whose calculate_regime() returns the given status."""
    ibkr = MagicMock()
    calc = RegimeGateCalculator(ibkr)

    status_to_regime = {
        'A': {'status': 'A', 'regime': 'RISK_ON', 'fire_power': '满火力', 'data': {'spy_price': 550.0}},
        'B': {'status': 'B', 'regime': 'NEUTRAL', 'fire_power': '半火力', 'data': {'spy_price': 540.0}},
        'C': {'status': 'C', 'regime': 'RISK_OFF', 'fire_power': '低火力/空仓', 'data': {'spy_price': 520.0}},
    }
    calc.calculate_regime = MagicMock(return_value=status_to_regime[status])
    return calc


class TestHysteresisOscillation:
    """SPY 在 50DMA 附近 5 天震荡，raw 在 A/B 切换，effective 保持不变"""

    def test_oscillation_keeps_effective_stable(self):
        """Alternating A/B raw status should NOT switch effective from B."""
        effective = 'B'
        progress = 0
        days_since = 999

        raw_sequence = ['A', 'B', 'A', 'B', 'A']

        for raw in raw_sequence:
            calc = _make_calculator_with_status(raw)
            result = calc.calculate_regime_with_hysteresis(
                previous_effective_status=effective,
                confirmation_progress=progress,
                days_since_last_switch=days_since,
            )
            assert result['effective_status'] == 'B', (
                f"Expected effective=B but got {result['effective_status']} "
                f"on raw={raw}, progress was {progress}"
            )
            assert result['switched'] is False

            # Update state for next iteration
            effective = result['effective_status']
            progress = result['confirmation_progress']
            days_since = days_since + 1

    def test_oscillation_resets_confirmation(self):
        """When raw flips back, confirmation progress resets to 0."""
        # Day 1: raw=A (effective=B, progress 0→1)
        calc = _make_calculator_with_status('A')
        r1 = calc.calculate_regime_with_hysteresis(
            previous_effective_status='B',
            confirmation_progress=0,
            days_since_last_switch=999,
        )
        assert r1['confirmation_progress'] == 1
        assert r1['pending_switch_to'] == 'A'

        # Day 2: raw=B (same as effective, progress resets to 0)
        calc = _make_calculator_with_status('B')
        r2 = calc.calculate_regime_with_hysteresis(
            previous_effective_status='B',
            confirmation_progress=r1['confirmation_progress'],
            days_since_last_switch=1000,
        )
        assert r2['confirmation_progress'] == 0
        assert r2['pending_switch_to'] is None


class TestHysteresisConfirmation:
    """连续 3 天 raw=C → effective 从 B 切到 C"""

    def test_three_consecutive_days_triggers_switch(self):
        effective = 'B'
        progress = 0
        days_since = 999

        for day in range(1, 4):
            calc = _make_calculator_with_status('C')
            result = calc.calculate_regime_with_hysteresis(
                previous_effective_status=effective,
                confirmation_progress=progress,
                days_since_last_switch=days_since,
            )

            if day < 3:
                assert result['effective_status'] == 'B'
                assert result['switched'] is False
                assert result['pending_switch_to'] == 'C'
                assert result['confirmation_progress'] == day
            else:
                # Day 3: switch happens
                assert result['effective_status'] == 'C'
                assert result['switched'] is True
                assert result['confirmation_progress'] == 3

            effective = result['effective_status']
            progress = result['confirmation_progress']
            days_since = days_since + 1

    def test_two_days_then_reset(self):
        """2 days raw=C then raw=B → no switch, progress resets."""
        # Day 1
        calc = _make_calculator_with_status('C')
        r1 = calc.calculate_regime_with_hysteresis('B', 0, 999)
        assert r1['confirmation_progress'] == 1

        # Day 2
        calc = _make_calculator_with_status('C')
        r2 = calc.calculate_regime_with_hysteresis('B', r1['confirmation_progress'], 1000)
        assert r2['confirmation_progress'] == 2
        assert r2['effective_status'] == 'B'

        # Day 3: raw goes back to B → reset
        calc = _make_calculator_with_status('B')
        r3 = calc.calculate_regime_with_hysteresis('B', r2['confirmation_progress'], 1001)
        assert r3['confirmation_progress'] == 0
        assert r3['effective_status'] == 'B'
        assert r3['switched'] is False


class TestHysteresisCooldown:
    """切换后 5 天内 raw 变回 A → effective 仍为 C（冷却期）"""

    def test_cooldown_blocks_switch(self):
        """After switching to C, raw=A within 5 days should be blocked."""
        for days_since in range(0, 5):
            calc = _make_calculator_with_status('A')
            result = calc.calculate_regime_with_hysteresis(
                previous_effective_status='C',
                confirmation_progress=0,
                days_since_last_switch=days_since,
            )
            assert result['effective_status'] == 'C', (
                f"Expected effective=C during cooldown (day {days_since})"
            )
            assert result['regime_locked'] is True
            assert result['switched'] is False

    def test_after_cooldown_confirmation_starts(self):
        """After cooldown expires, confirmation process begins normally."""
        calc = _make_calculator_with_status('A')
        result = calc.calculate_regime_with_hysteresis(
            previous_effective_status='C',
            confirmation_progress=0,
            days_since_last_switch=5,  # Cooldown expired
        )
        assert result['regime_locked'] is False
        assert result['confirmation_progress'] == 1
        assert result['pending_switch_to'] == 'A'
        assert result['effective_status'] == 'C'  # Not yet switched

    def test_full_cycle_switch_then_cooldown_then_switch_back(self):
        """Full lifecycle: B→C switch, cooldown, then C→A switch."""
        effective = 'B'
        progress = 0
        days_since = 999

        # 3 days raw=C → switch to C
        for _ in range(3):
            calc = _make_calculator_with_status('C')
            r = calc.calculate_regime_with_hysteresis(effective, progress, days_since)
            effective = r['effective_status']
            progress = r['confirmation_progress']
            days_since = 0 if r['switched'] else days_since + 1

        assert effective == 'C'

        # Cooldown: 5 days raw=A, but locked
        for day in range(5):
            calc = _make_calculator_with_status('A')
            r = calc.calculate_regime_with_hysteresis(effective, 0, day)
            assert r['effective_status'] == 'C'
            assert r['regime_locked'] is True

        # After cooldown: 3 days raw=A → switch to A
        days_since = 5
        progress = 0
        for day in range(3):
            calc = _make_calculator_with_status('A')
            r = calc.calculate_regime_with_hysteresis(effective, progress, days_since)
            progress = r['confirmation_progress']
            days_since += 1
            if r['switched']:
                effective = r['effective_status']

        assert effective == 'A'


class TestHysteresisUnknownStatus:
    """UNKNOWN/ERROR 状态不触发切换逻辑"""

    def test_unknown_preserves_previous(self):
        ibkr = MagicMock()
        calc = RegimeGateCalculator(ibkr)
        calc.calculate_regime = MagicMock(return_value={
            'status': 'UNKNOWN',
            'regime': 'UNKNOWN',
            'fire_power': '未知',
            'data': None,
            'error': 'No data',
        })

        result = calc.calculate_regime_with_hysteresis('A', 2, 10)
        assert result['effective_status'] == 'A'
        assert result['switched'] is False
        assert result['confirmation_progress'] == 0
