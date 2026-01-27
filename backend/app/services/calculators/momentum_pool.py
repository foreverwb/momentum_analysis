"""
动能股池计算器
基于价格序列 + 导入的 Finviz/MarketChameleon 数据计算动能股池评分与指标。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any, Tuple

import pandas as pd

from .technical import (
    analyze_technical,
    calculate_returns,
    calculate_breakout_volume_ratio,
    calculate_atr_percent,
    calculate_deviation_from_ma,
    calculate_distance_from_high,
)


@dataclass
class MomentumPoolResult:
    total_score: float
    scores: Dict[str, float]
    metrics: Dict[str, Any]


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _safe_pct(value: Optional[float], digits: int = 1) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value) * 100, digits)
    except (TypeError, ValueError):
        return None


def _score_alignment(alignment: Optional[str]) -> float:
    mapping = {
        'strong_bullish': 100,
        'bullish': 80,
        'mixed': 50,
        'bearish': 30,
        'strong_bearish': 10
    }
    return float(mapping.get(alignment or '', 50))


def _score_slope(slope: float, base_price: float) -> float:
    if base_price <= 0:
        return 50.0
    daily_pct = slope / base_price
    if daily_pct >= 0.002:
        return 90.0
    if daily_pct >= 0.001:
        return 75.0
    if daily_pct > 0:
        return 60.0
    if daily_pct >= -0.001:
        return 40.0
    return 25.0


def _score_volume(rel_vol: float, obv_trend: str) -> float:
    if rel_vol >= 2.0:
        rel_score = 90
    elif rel_vol >= 1.5:
        rel_score = 75
    elif rel_vol >= 1.2:
        rel_score = 60
    elif rel_vol >= 1.0:
        rel_score = 50
    else:
        rel_score = 35

    obv_trend = (obv_trend or '').lower()
    if 'strong' in obv_trend:
        obv_score = 80
    elif 'neutral' in obv_trend:
        obv_score = 60
    else:
        obv_score = 40

    return round(rel_score * 0.6 + obv_score * 0.4, 2)


def _score_quality(
    max_drawdown_pct: Optional[float],
    atr_pct: Optional[float],
    deviation_pct: Optional[float]
) -> float:
    if max_drawdown_pct is None:
        max_drawdown_pct = 0.0
    if atr_pct is None:
        atr_pct = 0.0
    if deviation_pct is None:
        deviation_pct = 0.0

    drawdown_score = max(0.0, 100 - abs(max_drawdown_pct) * 2.5)
    atr_score = max(0.0, 100 - abs(atr_pct) * 4.0)
    deviation_score = max(0.0, 100 - abs(deviation_pct) * 3.0)

    return round((drawdown_score + atr_score + deviation_score) / 3.0, 2)


def _score_options(heat_score: Optional[float], ivr: Optional[float]) -> float:
    if heat_score is not None:
        return round(max(0.0, min(100.0, heat_score)), 2)
    if ivr is not None:
        return round(max(0.0, min(100.0, ivr)), 2)
    return 50.0


def _label_heat(heat_score: Optional[float], ivr: Optional[float]) -> str:
    reference = heat_score if heat_score is not None else ivr
    if reference is None:
        return 'Medium'
    if reference >= 70:
        return 'High'
    if reference >= 50:
        return 'Medium'
    return 'Low'


def _label_overheat(rsi: Optional[float]) -> str:
    if rsi is None:
        return 'Normal'
    if rsi >= 70:
        return 'Hot'
    if rsi <= 30:
        return 'Cold'
    if rsi >= 60:
        return 'Warm'
    return 'Normal'


def _label_alignment(alignment: Optional[str]) -> str:
    mapping = {
        'strong_bullish': '多头',
        'bullish': '多头',
        'mixed': '混合',
        'bearish': '空头',
        'strong_bearish': '空头',
    }
    return mapping.get(alignment or '', 'N/A')


def _compute_return_excluding_last(prices: pd.Series, period: int, exclude_last: int) -> Optional[float]:
    if len(prices) < period + exclude_last + 1:
        return None
    end_idx = -(exclude_last + 1)
    start_idx = -(exclude_last + period + 1)
    if abs(start_idx) > len(prices):
        return None
    base = prices.iloc[start_idx]
    if base == 0:
        return None
    return (prices.iloc[end_idx] - base) / base


def calculate_momentum_pool_result(
    price_df: pd.DataFrame,
    sector_df: Optional[pd.DataFrame] = None,
    finviz_data: Optional[Dict[str, Any]] = None,
    mc_data: Optional[Dict[str, Any]] = None,
    iv_data: Optional[Dict[str, Any]] = None
) -> Optional[MomentumPoolResult]:
    """
    计算单只股票的动能股池评分与指标。
    price_df 必须包含 close/high/low/volume 列。
    """
    analysis = analyze_technical(price_df)
    if analysis is None:
        return None

    prices = price_df['close']
    highs = price_df['high']
    lows = price_df['low']
    volumes = price_df['volume']

    current_price = float(prices.iloc[-1])

    return_5d = calculate_returns(prices, 5)
    return_20d = calculate_returns(prices, 20)
    return_63d = calculate_returns(prices, 63) if len(prices) >= 64 else 0.0
    return_20d_ex3d = _compute_return_excluding_last(prices, 20, 3)

    rs_diff_20d = None
    rs_ratio_20d = None
    sector_return_20d = None
    if sector_df is not None and not sector_df.empty:
        sector_prices = sector_df['close']
        if len(sector_prices) >= 21:
            sector_return_20d = calculate_returns(sector_prices, 20)
            rs_diff_20d = return_20d - sector_return_20d
            if sector_return_20d != 0:
                rs_ratio_20d = return_20d / sector_return_20d

    high_20d = highs.iloc[-20:].max() if len(highs) >= 20 else highs.max()
    distance_ratio = calculate_distance_from_high(current_price, high_20d)
    distance_to_high_pct = (1 - distance_ratio) * 100 if distance_ratio is not None else None

    breakout_volume = calculate_breakout_volume_ratio(prices, volumes)
    atr_pct = calculate_atr_percent(highs, lows, prices)
    deviation_pct = calculate_deviation_from_ma(current_price, analysis.sma20)

    # Momentum score (0-100)
    momentum_score = 0.0
    momentum_score += 25 if return_5d > 0 else 0
    momentum_score += 25 if return_20d > 0 else 0
    momentum_score += 25 if return_63d > 0 else 0
    if rs_diff_20d is None:
        momentum_score += 12.5
    else:
        momentum_score += 25 if rs_diff_20d > 0 else 0

    # Trend score (0-100)
    alignment_score = _score_alignment(analysis.ma_alignment)
    slope_score = _score_slope(analysis.sma20_slope, analysis.sma20 or current_price)
    persistence_score = analysis.trend_persistence * 100
    trend_score = alignment_score * 0.4 + slope_score * 0.3 + persistence_score * 0.3

    # Volume score (0-100)
    volume_score = _score_volume(analysis.volume_ratio, analysis.obv_trend)

    # Quality score (0-100)
    quality_score = _score_quality(
        _safe_pct(analysis.max_drawdown_20d, 1),
        _safe_pct(atr_pct, 1),
        _safe_pct(deviation_pct, 1)
    )

    # Options score (0-100)
    heat_score = mc_data.get('heat_score') if mc_data else None
    ivr = None
    if mc_data and mc_data.get('ivr') is not None:
        ivr = mc_data.get('ivr')
    elif iv_data and iv_data.get('ivr') is not None:
        ivr = iv_data.get('ivr')

    options_score = _score_options(heat_score, ivr)

    base_score = 0.65 * ((momentum_score + trend_score) / 2.0) + 0.15 * volume_score + 0.20 * options_score
    penalty_factor = 1.0
    if quality_score < 40:
        penalty_factor = 0.85
    elif quality_score < 60:
        penalty_factor = 0.90
    elif quality_score < 70:
        penalty_factor = 0.95

    total_score = round(base_score * penalty_factor, 2)

    metrics: Dict[str, Any] = {
        'return20d': _safe_pct(return_20d, 1),
        'return20dEx3d': _safe_pct(return_20d_ex3d, 1),
        'return63d': _safe_pct(return_63d, 1),
        'relativeStrength': _round(rs_ratio_20d, 2),
        'distanceToHigh20d': _round(distance_to_high_pct, 1),
        'volumeMultiple': _round(breakout_volume, 2),
        'maAlignment': _label_alignment(analysis.ma_alignment),
        'trendPersistence': _round(analysis.trend_persistence * 100, 1),
        'breakoutVolume': _round(breakout_volume, 2),
        'volumeRatio': _round(analysis.volume_ratio, 2),
        'obvTrend': analysis.obv_trend,
        'maxDrawdown20d': _safe_pct(analysis.max_drawdown_20d, 1),
        'atrPercent': _safe_pct(atr_pct, 1),
        'deviationFrom20ma': _safe_pct(deviation_pct, 1),
        'overheat': _label_overheat(analysis.rsi),
        'optionsHeat': _label_heat(heat_score, ivr),
        'optionsRelVolume': _round(
            (mc_data.get('rel_vol_to_90d') if mc_data else None) or (mc_data.get('rel_vol') if mc_data else None),
            2
        ) if mc_data else None,
        'ivr': _round(ivr, 1),
        'iv30': _round(
            mc_data.get('iv30') if mc_data else (iv_data.get('iv30') if iv_data else None),
            2
        ),
        'sma20Slope': _round(analysis.sma20_slope, 4)
    }

    scores = {
        'momentum': round(momentum_score, 2),
        'trend': round(trend_score, 2),
        'volume': round(volume_score, 2),
        'quality': round(quality_score, 2),
        'options': round(options_score, 2)
    }

    return MomentumPoolResult(
        total_score=total_score,
        scores=scores,
        metrics=metrics
    )
