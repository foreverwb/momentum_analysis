"""VIX 硬性降档逻辑测试"""
import math
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.calculators.regime_gate import RegimeGateCalculator


def _make_ibkr(price: float, sma20: float, sma50: float, slope: float, ret20: float, vix: float):
    """构造 mock ibkr，返回可控的 SPY 数据和 VIX。"""
    # 构造足够长的价格序列（60+条），最后一条为 price
    n = 80
    prices = [price] * n
    # 让 calculate_sma 返回我们想要的值：把序列设计为均值恰好等于目标
    # 简单方案：mock technical 函数
    ibkr = MagicMock()
    ibkr.get_price_data.return_value = pd.DataFrame({'SPY': prices})
    ibkr.get_vix.return_value = vix
    return ibkr


@pytest.fixture
def _patch_technical(monkeypatch):
    """Patch technical 函数，使测试可以精确控制 sma/slope/return。"""

    def _patcher(sma20: float, sma50: float, slope: float, ret20: float):
        import app.services.calculators.regime_gate as rg_mod

        # regime_gate.py 在 calculate_regime 内部 from .technical import ...
        # 我们 patch 被导入的模块级函数
        from app.services.calculators import technical

        monkeypatch.setattr(technical, 'calculate_sma', lambda prices, period: pd.Series([sma20 if period == 20 else sma50] * len(prices)))
        monkeypatch.setattr(technical, 'calculate_sma_slope', lambda sma, period=5: slope)
        monkeypatch.setattr(technical, 'calculate_returns', lambda prices, period: ret20)

    return _patcher


class TestVixOverride:
    """VIX 降档条件测试"""

    def test_vix_normal_risk_on_gives_a(self, _patch_technical):
        """VIX=20, 价格在50DMA上方, 斜率正 → A"""
        _patch_technical(sma20=550, sma50=530, slope=0.5, ret20=0.03)
        ibkr = _make_ibkr(price=560, sma20=550, sma50=530, slope=0.5, ret20=0.03, vix=20)
        calc = RegimeGateCalculator(ibkr)
        result = calc.calculate_regime()
        assert result['status'] == 'A'
        assert 'VIX' not in result['fire_power']

    def test_vix_elevated_risk_on_gives_a_with_label(self, _patch_technical):
        """VIX=28, 同上 → A，fire_power 含 'VIX偏高'"""
        _patch_technical(sma20=550, sma50=530, slope=0.5, ret20=0.03)
        ibkr = _make_ibkr(price=560, sma20=550, sma50=530, slope=0.5, ret20=0.03, vix=28)
        calc = RegimeGateCalculator(ibkr)
        result = calc.calculate_regime()
        assert result['status'] == 'A'
        assert 'VIX偏高' in result['fire_power']

    def test_vix_extreme_forces_b(self, _patch_technical):
        """VIX=35, 价格在50DMA上方 → B（VIX强制降档）"""
        _patch_technical(sma20=550, sma50=530, slope=0.5, ret20=0.03)
        ibkr = _make_ibkr(price=560, sma20=550, sma50=530, slope=0.5, ret20=0.03, vix=35)
        calc = RegimeGateCalculator(ibkr)
        result = calc.calculate_regime()
        assert result['status'] == 'B'
        assert 'VIX极端' in result['fire_power']

    def test_vix_extreme_risk_off_stays_c(self, _patch_technical):
        """VIX=35, 价格在50DMA下方 + 收益负 → C（risk_off 优先）"""
        _patch_technical(sma20=510, sma50=530, slope=-0.5, ret20=-0.05)
        ibkr = _make_ibkr(price=500, sma20=510, sma50=530, slope=-0.5, ret20=-0.05, vix=35)
        calc = RegimeGateCalculator(ibkr)
        result = calc.calculate_regime()
        assert result['status'] == 'C'

    def test_vix_override_field_in_data(self, _patch_technical):
        """vix_override 字段正确设置"""
        _patch_technical(sma20=550, sma50=530, slope=0.5, ret20=0.03)
        ibkr = _make_ibkr(price=560, sma20=550, sma50=530, slope=0.5, ret20=0.03, vix=35)
        calc = RegimeGateCalculator(ibkr)
        result = calc.calculate_regime()
        assert result['data']['vix_override'] == 'extreme'
