"""
动能股池计算器
基于价格序列 + 导入的 Finviz/MarketChameleon 数据计算动能股池评分与指标。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd

from .etf_score import rank_percentile_normalize
from .technical import (
    analyze_technical,
    calculate_returns,
    calculate_breakout_volume_ratio,
    calculate_atr_percent,
    calculate_deviation_from_ma,
    calculate_distance_from_high,
)


STOCK_THRESHOLDS = {
    'price_above_sma20': True,
    'sma20_above_sma50': True,
    'min_avg_dollar_volume': 500_000,
    'min_market_cap': 1_000_000_000,
}


def check_stock_thresholds(
    analysis,
    finviz_data: Optional[Dict[str, Any]] = None,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    检查个股硬性门槛。

    Args:
        analysis: TechnicalAnalysisResult，需包含 price / sma20 / sma50 属性。
        finviz_data: Finviz 解析数据，需包含 market_cap 字段（单位：美元）。
        price_df: 价格 DataFrame，需包含 close / volume 列。

    Returns:
        {'all_pass': bool, 'details': {门槛名: 'PASS'|'FAIL'|'NO_DATA'}}
        NO_DATA 不算 FAIL。
    """
    results: Dict[str, str] = {}
    all_pass = True

    # 1. P > SMA20
    if analysis.sma20 is not None:
        p_above_20 = analysis.price > analysis.sma20
        results['price_above_sma20'] = 'PASS' if p_above_20 else 'FAIL'
        if not p_above_20:
            all_pass = False
    else:
        results['price_above_sma20'] = 'NO_DATA'

    # 2. SMA20 > SMA50
    if analysis.sma20 is not None and analysis.sma50 is not None:
        sma20_gt_50 = analysis.sma20 > analysis.sma50
        results['sma20_above_sma50'] = 'PASS' if sma20_gt_50 else 'FAIL'
        if not sma20_gt_50:
            all_pass = False
    else:
        results['sma20_above_sma50'] = 'NO_DATA'

    # 3. 日均成交额 > $500K（20日平均）
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
        try:
            cap = float(finviz_data['market_cap'])
            cap_pass = cap >= STOCK_THRESHOLDS['min_market_cap']
            results['min_market_cap'] = 'PASS' if cap_pass else 'FAIL'
            if not cap_pass:
                all_pass = False
        except (TypeError, ValueError):
            results['min_market_cap'] = 'NO_DATA'
    else:
        results['min_market_cap'] = 'NO_DATA'

    return {'all_pass': all_pass, 'details': results}


@dataclass
class MomentumPoolResult:
    total_score: float
    scores: Dict[str, float]
    metrics: Dict[str, Any]
    thresholds_pass: bool = True
    thresholds: Dict[str, str] = None

    def __post_init__(self):
        if self.thresholds is None:
            self.thresholds = {}


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
    required_cols = {"close", "high", "low", "volume"}
    if not isinstance(price_df, pd.DataFrame) or price_df.empty:
        return None
    if not required_cols.issubset(price_df.columns):
        return None
    if sector_df is not None:
        if not isinstance(sector_df, pd.DataFrame) or sector_df.empty or "close" not in sector_df.columns:
            sector_df = None
    if finviz_data is not None and not isinstance(finviz_data, dict):
        finviz_data = None
    if mc_data is not None and not isinstance(mc_data, dict):
        mc_data = None
    if iv_data is not None and not isinstance(iv_data, dict):
        iv_data = None

    try:
        analysis = analyze_technical(price_df)
    except Exception:
        return None

    if analysis is None:
        return None

    thresholds = check_stock_thresholds(analysis, finviz_data, price_df)

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

    # Price momentum: continuous raw values (not binary 0/25)
    abs_mom = 0.60 * (return_20d_ex3d or 0) + 0.40 * (return_63d or 0)
    rel_strength = rs_diff_20d or 0
    prox_high = distance_ratio or 0  # 1.0 = at high, lower = further away

    momentum_raw = {
        'abs_mom': abs_mom,
        'rel_strength': rel_strength,
        'prox_high': prox_high,
    }
    # Combine into a single price_mom score (raw, will be normalized in batch)
    price_mom_score = abs_mom * 100  # scale to roughly 0-100 range for standalone use

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

    # Weighted composite: PriceMom=0.40, TrendStr=0.25, VolScore=0.15, OptionsOv=0.20
    base_score = (
        0.40 * price_mom_score
        + 0.25 * trend_score
        + 0.15 * volume_score
        + 0.20 * options_score
    )

    # Quality adjustment: multiplicative penalty stacking
    quality_adj = 1.0
    if atr_pct is not None and atr_pct > 0.03:
        quality_adj *= 0.70
    if analysis.max_drawdown_20d is not None and analysis.max_drawdown_20d < -0.15:
        quality_adj *= 0.60
    if deviation_pct is not None and deviation_pct > 0.10:
        quality_adj *= 0.80
    quality_adj = max(quality_adj, 0.40)

    total_score = round(base_score * quality_adj, 2)

    metrics: Dict[str, Any] = {
        'return20d': _safe_pct(return_20d, 1),
        'return20dEx3d': _safe_pct(return_20d_ex3d, 1),
        'return63d': _safe_pct(return_63d, 1),
        'relativeStrength': _round(rs_ratio_20d, 2),
        'relativeStrengthDiff': _safe_pct(rs_diff_20d, 1),
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
        'sma20Slope': _round(analysis.sma20_slope, 4),
        'rsi': _round(analysis.rsi, 2),
        'beta': _round(finviz_data.get('beta') if finviz_data else None, 2),
        'absMom': _round(abs_mom, 4),
        'relStrength': _round(rel_strength, 4),
        'proxHigh': _round(prox_high, 4),
        'qualityAdj': _round(quality_adj, 2),
    }

    scores = {
        'price_mom': round(price_mom_score, 2),
        'trend': round(trend_score, 2),
        'volume': round(volume_score, 2),
        'options': round(options_score, 2),
        'quality_adj': round(quality_adj, 2),
    }

    return MomentumPoolResult(
        total_score=total_score,
        scores=scores,
        metrics=metrics,
        thresholds_pass=thresholds['all_pass'],
        thresholds=thresholds['details'],
    )


# ---------------------------------------------------------------------------
# 批量横截面标准化入口
# ---------------------------------------------------------------------------

_DIMENSION_KEYS = ('price_mom', 'trend', 'volume', 'options')
_WEIGHTS = {'price_mom': 0.40, 'trend': 0.25, 'volume': 0.15, 'options': 0.20}


def batch_calculate_momentum_pool(
    stock_data_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    批量计算动能股池评分，带横截面标准化。

    对每只股票先调用 calculate_momentum_pool_result 获取原始分，
    再用 rank_percentile_normalize 做横截面归一化后加权合成 total_score。

    Args:
        stock_data_map: {symbol: {'price_df': df, 'sector_df': df,
                         'finviz_data': {}, 'mc_data': {}, 'iv_data': {}}}

    Returns:
        按 total_score 降序排列的结果列表，每项包含：
        {
            'symbol': str,
            'total_score': float,           # 标准化后加权合成 × quality_adj
            'raw_scores': Dict[str, float],  # 标准化前的原始分
            'norm_scores': Dict[str, float], # 标准化后的 0-100 分
            'quality_adj': float,            # 质量调整系数
            'scores': Dict[str, float],      # 兼容旧结构
            'metrics': Dict[str, Any],       # 兼容旧结构
        }
    """
    # Step 1: 对每只股票调用单股计算，收集结果
    raw_results: Dict[str, MomentumPoolResult] = {}
    for sym, data in stock_data_map.items():
        result = calculate_momentum_pool_result(
            price_df=data.get('price_df'),
            sector_df=data.get('sector_df'),
            finviz_data=data.get('finviz_data'),
            mc_data=data.get('mc_data'),
            iv_data=data.get('iv_data'),
        )
        if result is not None:
            raw_results[sym] = result

    if not raw_results:
        return []

    # Step 2: 样本数 < 3 时退化为单股评分模式
    if len(raw_results) < 3:
        output = []
        for sym, result in raw_results.items():
            raw_scores = {d: result.scores.get(d, 0.0) for d in _DIMENSION_KEYS}
            output.append({
                'symbol': sym,
                'total_score': result.total_score,
                'raw_scores': raw_scores,
                'norm_scores': raw_scores.copy(),
                'quality_adj': result.scores.get('quality_adj', 1.0),
                'scores': result.scores,
                'metrics': result.metrics,
                'thresholds_pass': result.thresholds_pass,
                'thresholds': result.thresholds,
            })
        output.sort(key=lambda x: x['total_score'], reverse=True)
        return output

    # Step 3: 横截面标准化
    norm_maps: Dict[str, Dict[str, Optional[float]]] = {}
    for dim in _DIMENSION_KEYS:
        raw_map = {sym: res.scores.get(dim) for sym, res in raw_results.items()}
        norm_maps[dim] = rank_percentile_normalize(raw_map, winsorize_limits=(0.05, 0.95))

    # Step 4: 加权合成 total_score
    output: List[Dict[str, Any]] = []
    for sym, result in raw_results.items():
        quality_adj = result.scores.get('quality_adj', 1.0)

        norm_scores = {d: (norm_maps[d].get(sym) or 50.0) for d in _DIMENSION_KEYS}
        raw_scores = {d: result.scores.get(d, 0.0) for d in _DIMENSION_KEYS}

        total = sum(_WEIGHTS[d] * norm_scores[d] for d in _DIMENSION_KEYS)
        total_score = round(total * quality_adj, 2)

        output.append({
            'symbol': sym,
            'total_score': total_score,
            'raw_scores': raw_scores,
            'norm_scores': norm_scores,
            'quality_adj': quality_adj,
            'scores': {**norm_scores, 'quality_adj': quality_adj},
            'metrics': result.metrics,
            'thresholds_pass': result.thresholds_pass,
            'thresholds': result.thresholds,
        })

    # Step 5: 按 total_score 降序排列
    output.sort(key=lambda x: x['total_score'], reverse=True)
    return output
