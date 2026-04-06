"""
ETF 综合评分计算器

升级点：
1) 先计算 raw_features，再在 batch 内做横截面 winsorize + rank percentile 标准化
2) 输出 raw_features / normalized_features / breakdown，增强可解释性
3) 缺失模块自动按比例重分配权重，避免 NO_DATA 直接拉低总分
4) 支持权重 preset（balanced / aggressive_short_term）
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _quantile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    sorted_values = sorted(float(v) for v in values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    q = _clip(float(q), 0.0, 1.0)
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(len(sorted_values) - 1, lo + 1)
    weight = pos - lo
    return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight


def _winsorize_value_map(
    value_map: Dict[str, Optional[float]],
    limits: Tuple[float, float] = (0.05, 0.95),
) -> Dict[str, Optional[float]]:
    valid_items = {k: float(v) for k, v in value_map.items() if v is not None}
    if not valid_items:
        return {k: None for k in value_map}

    lower_q, upper_q = limits
    values = list(valid_items.values())
    lower = _quantile(values, lower_q)
    upper = _quantile(values, upper_q)
    if lower is None or upper is None:
        return {k: valid_items.get(k) for k in value_map}

    winsorized: Dict[str, Optional[float]] = {}
    for key, raw_value in value_map.items():
        if raw_value is None:
            winsorized[key] = None
        else:
            winsorized[key] = _clip(float(raw_value), lower, upper)
    return winsorized


def rank_percentile_normalize(
    value_map: Dict[str, Optional[float]],
    winsorize_limits: Tuple[float, float] = (0.05, 0.95),
) -> Dict[str, Optional[float]]:
    """
    对横截面 raw 值做 winsorize 后的 rank percentile 标准化，输出 0..100。
    缺失值返回 None。
    """
    winsorized = _winsorize_value_map(value_map, limits=winsorize_limits)
    valid_values = [v for v in winsorized.values() if v is not None]
    n = len(valid_values)

    if n == 0:
        return {k: None for k in value_map}
    if n == 1:
        # 单样本时避免虚高，给中性分。
        return {k: (50.0 if winsorized.get(k) is not None else None) for k in value_map}

    normalized: Dict[str, Optional[float]] = {}
    for key, current in winsorized.items():
        if current is None:
            normalized[key] = None
            continue
        count_less = sum(1 for v in valid_values if v < current)
        count_equal = sum(1 for v in valid_values if v == current)
        # mid-rank percentile
        rank_position = count_less + 0.5 * max(0, count_equal - 1)
        percentile = (rank_position / (n - 1)) * 100.0
        normalized[key] = round(_clip(percentile, 0.0, 100.0), 2)

    return normalized


@dataclass
class ScoreResult:
    score: float
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"score": self.score, "data": self.data}


@dataclass
class ThresholdResult:
    all_pass: bool
    details: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {"all_pass": self.all_pass, "details": self.details}


@dataclass
class ETFScoreResult:
    symbol: str
    total_score: float
    thresholds_pass: bool
    thresholds: Dict[str, str]
    breakdown: Dict[str, Any]
    weights: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ETFScoreCalculator:
    """
    ETF 综合评分计算器（短周期 2-6 周风格）.
    """

    # 兼容旧测试：保留 class-level WEIGHTS 且和为 1
    WEIGHTS = {
        'rel_mom': 0.45,
        'trend_quality': 0.25,
        'breadth': 0.20,
        'options_confirm': 0.10,
    }

    WEIGHT_PRESETS = {
        # 与历史口径一致
        'balanced': {
            'module_weights': WEIGHTS,
        },
        # 短周期激进追趋势
        'aggressive_short_term': {
            'price_rs': 0.55,
            'breadth': 0.20,
            'options_confirm': 0.25,
        },
    }

    DEFAULT_PRESET = 'balanced'
    DEFAULT_PRICE_RS_ALPHA = 0.65
    DEFAULT_WINSORIZE_LIMITS = (0.05, 0.95)

    BREADTH_RAW_WEIGHTS = {
        'pct_above_sma50': 0.35,
        'pct_above_sma20': 0.25,
        'pct_near_52w_high': 0.15,
        'ew_vs_mw_spread': 0.25,
    }

    THRESHOLDS = {
        'price_above_sma50': True,
        'rs_20d_positive': True,
        'breadth_min': 0.40,
    }

    def __init__(
        self,
        ibkr=None,
        futu=None,
        weight_preset: str = DEFAULT_PRESET,
        price_rs_alpha: float = DEFAULT_PRICE_RS_ALPHA,
        winsorize_limits: Tuple[float, float] = DEFAULT_WINSORIZE_LIMITS,
    ):
        self.ibkr = ibkr
        self.futu = futu
        self.weight_preset = (
            weight_preset
            if weight_preset in self.WEIGHT_PRESETS
            else self.DEFAULT_PRESET
        )
        self.price_rs_alpha = _clip(float(price_rs_alpha), 0.0, 1.0)
        self.winsorize_limits = winsorize_limits

    def _resolve_effective_weights(self) -> Dict[str, float]:
        preset = self.WEIGHT_PRESETS[self.weight_preset]
        module_weights = preset.get('module_weights')
        if isinstance(module_weights, dict):
            return dict(module_weights)

        price_rs = float(preset.get('price_rs', 0.70))
        breadth = float(preset.get('breadth', 0.20))
        options_confirm = float(preset.get('options_confirm', 0.10))

        rel_mom = price_rs * self.price_rs_alpha
        trend_quality = price_rs * (1.0 - self.price_rs_alpha)

        effective = {
            'rel_mom': rel_mom,
            'trend_quality': trend_quality,
            'breadth': breadth,
            'options_confirm': options_confirm,
        }
        total = sum(effective.values())
        if total <= 0:
            return dict(self.WEIGHTS)
        return {k: round(v / total, 6) for k, v in effective.items()}

    @staticmethod
    def _map_rel_mom_absolute(rel_mom: Optional[float]) -> float:
        if rel_mom is None:
            return 0.0
        # 历史兼容映射（仅用于单维原始值展示）
        score = (float(rel_mom) + 0.1) / 0.25 * 100.0
        return round(_clip(score, 0.0, 100.0), 2)

    def _fetch_iv_map(self, symbols: Iterable[str]) -> Dict[str, Any]:
        symbols = [str(s).upper() for s in symbols]
        if not symbols or self.futu is None:
            return {}
        try:
            if hasattr(self.futu, "is_connected") and not self.futu.is_connected():
                return {}
            return self.futu.fetch_iv_terms(symbols, log_progress=False, log_fetch_summary=False)
        except TypeError:
            # 兼容旧签名（无 log_* 参数）
            try:
                return self.futu.fetch_iv_terms(symbols)
            except Exception as exc:
                logger.warning(f"批量获取 IV 数据失败: {exc}")
                return {}
        except Exception as exc:
            logger.warning(f"批量获取 IV 数据失败: {exc}")
            return {}

    @staticmethod
    def _extract_field(payload: Any, field_name: str) -> Optional[float]:
        if payload is None:
            return None
        if hasattr(payload, field_name):
            return _safe_float(getattr(payload, field_name))
        if isinstance(payload, dict):
            return _safe_float(payload.get(field_name))
        return None

    def calculate_rel_mom_score(self, symbol: str, benchmark: str = 'SPY') -> Dict[str, Any]:
        try:
            if self.ibkr is None:
                return {'score': 0.0, 'raw_score': None, 'data': None}

            result = self.ibkr.analyze_sector_vs_spy(symbol, benchmark)
            if not result:
                return {'score': 0.0, 'raw_score': None, 'data': None}

            rel_mom_raw = _safe_float(result.get('RelMom'))
            abs_score = self._map_rel_mom_absolute(rel_mom_raw)

            return {
                'score': abs_score,
                'raw_score': rel_mom_raw,
                'data': {
                    'RS': result.get('RS'),
                    'RS_5D': result.get('RS_5D'),
                    'RS_20D': result.get('RS_20D'),
                    'RS_63D': result.get('RS_63D'),
                    'RelMom': rel_mom_raw,
                    'strength': result.get('strength', 'NEUTRAL'),
                    'description': result.get('description', ''),
                    'rel_mom_raw': rel_mom_raw,
                },
            }
        except Exception as exc:
            logger.error(f"计算 {symbol} RelMom 分数失败: {exc}")
            return {'score': 0.0, 'raw_score': None, 'data': None}

    def calculate_trend_quality_score(self, symbol: str) -> Dict[str, Any]:
        from .technical import calculate_sma, calculate_sma_slope_pct, calculate_max_drawdown

        try:
            if self.ibkr is None:
                return {'score': 0.0, 'raw_score': None, 'data': None}

            price_df = self.ibkr.get_price_data(symbol, duration='100 D')
            if price_df is None or len(price_df) < 50:
                return {'score': 0.0, 'raw_score': None, 'data': None}

            prices = price_df[symbol]
            sma20 = calculate_sma(prices, 20)
            sma50 = calculate_sma(prices, 50)

            current_price = float(prices.iloc[-1])
            current_sma20 = float(sma20.iloc[-1])
            current_sma50 = float(sma50.iloc[-1])
            price_above_sma50 = current_price > current_sma50
            sma20_above_sma50 = current_sma20 > current_sma50
            sma20_slope = float(calculate_sma_slope_pct(sma20, period=5))
            max_dd = float(calculate_max_drawdown(prices, 20))

            score = 0.0
            score_breakdown: Dict[str, float] = {}
            if price_above_sma50:
                score += 25.0
                score_breakdown['price_above_sma50'] = 25.0
            else:
                score_breakdown['price_above_sma50'] = 0.0

            if sma20_above_sma50:
                score += 25.0
                score_breakdown['sma20_above_sma50'] = 25.0
            else:
                score_breakdown['sma20_above_sma50'] = 0.0

            if sma20_slope > 0:
                score += 25.0
                score_breakdown['sma20_slope_positive'] = 25.0
            else:
                score_breakdown['sma20_slope_positive'] = 0.0

            if max_dd > -0.10:
                score += 25.0
                score_breakdown['drawdown_acceptable'] = 25.0
            else:
                score_breakdown['drawdown_acceptable'] = 0.0

            score = round(_clip(score, 0.0, 100.0), 2)
            return {
                'score': score,
                'raw_score': score,
                'data': {
                    'price': round(current_price, 2),
                    'sma20': round(current_sma20, 2),
                    'sma50': round(current_sma50, 2),
                    'price_above_sma50': price_above_sma50,
                    'sma20_above_sma50': sma20_above_sma50,
                    'sma20_slope': round(sma20_slope, 4),
                    'max_drawdown_20d': round(max_dd, 4),
                    'score_breakdown': score_breakdown,
                    'trend_quality_raw': score,
                },
            }
        except Exception as exc:
            logger.error(f"计算 {symbol} 趋势质量分数失败: {exc}")
            return {'score': 0.0, 'raw_score': None, 'data': None}

    def calculate_breadth_score(
        self,
        etf_symbol: str,
        holdings_data: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if not holdings_data:
            return {'score': 0.0, 'raw_score': None, 'data': None}

        try:
            from ..parsers.finviz_parser import calculate_breadth_metrics

            breadth = calculate_breadth_metrics(holdings_data)
            pct_above_50 = _safe_float(breadth.get('pct_above_sma50')) or 0.0
            pct_above_20 = _safe_float(breadth.get('pct_above_sma20')) or 0.0
            pct_near_52w_high = _safe_float(breadth.get('pct_near_52w_high')) or 0.0

            ew_vs_mw = _safe_float(breadth.get('ew_vs_mw_spread')) or 0.0
            # 映射到 0-1：spread=+5% → 1.0, 0% → 0.5, -5% → 0.0
            ew_vs_mw_score = max(0.0, min(1.0, 0.5 + ew_vs_mw * 10))

            breadth_raw = (
                self.BREADTH_RAW_WEIGHTS['pct_above_sma50'] * pct_above_50 +
                self.BREADTH_RAW_WEIGHTS['pct_above_sma20'] * pct_above_20 +
                self.BREADTH_RAW_WEIGHTS['pct_near_52w_high'] * pct_near_52w_high +
                self.BREADTH_RAW_WEIGHTS['ew_vs_mw_spread'] * ew_vs_mw_score
            ) * 100.0
            breadth_raw = round(_clip(breadth_raw, 0.0, 100.0), 2)

            return {
                'score': breadth_raw,
                'raw_score': breadth_raw,
                'data': {
                    'pct_above_sma20': round(pct_above_20, 4),
                    'pct_above_sma50': round(pct_above_50, 4),
                    'pct_above_sma200': round(_safe_float(breadth.get('pct_above_sma200')) or 0.0, 4),
                    'pct_near_52w_high': round(pct_near_52w_high, 4),
                    'pct_near_52w_low': round(_safe_float(breadth.get('pct_near_52w_low')) or 0.0, 4),
                    'ew_vs_mw_spread': round(ew_vs_mw, 4),
                    'ew_vs_mw_score': round(ew_vs_mw_score, 4),
                    'total_count': breadth.get('total_count', 0),
                    'breadth_raw': breadth_raw,
                    'breadth_raw_weights': dict(self.BREADTH_RAW_WEIGHTS),
                },
            }
        except Exception as exc:
            logger.error(f"计算 {etf_symbol} 广度分数失败: {exc}")
            return {'score': 0.0, 'raw_score': None, 'data': None}

    def calculate_options_confirm_score(
        self,
        symbol: str,
        mc_data: Optional[Dict[str, Any]] = None,
        iv_data: Optional[Any] = None,
    ) -> Dict[str, Any]:
        from ..parsers.mc_parser import (
            calculate_positioning_score_from_iv,
            calculate_term_score,
            normalize_heat_type,
            to_legacy_heat_type,
        )

        components: Dict[str, Any] = {}
        try:
            if iv_data is None and self.futu is not None:
                try:
                    if hasattr(self.futu, "is_connected") and self.futu.is_connected():
                        iv_result = self.futu.fetch_iv_terms([symbol], log_progress=False, log_fetch_summary=False)
                        iv_data = iv_result.get(symbol)
                except TypeError:
                    iv_result = self.futu.fetch_iv_terms([symbol])
                    iv_data = iv_result.get(symbol)
                except Exception as exc:
                    logger.warning(f"获取 {symbol} 富途 IV 失败: {exc}")

            heat_score = _safe_float((mc_data or {}).get('heat_score'))
            risk_score = _safe_float((mc_data or {}).get('risk_score'))
            confidence_penalty = _safe_float((mc_data or {}).get('confidence_penalty'))
            base_heat_type = normalize_heat_type((mc_data or {}).get('heat_type'))
            put_pct = _safe_float((mc_data or {}).get('put_pct'))

            heat_score = 50.0 if heat_score is None else _clip(heat_score, 0.0, 100.0)
            risk_score = 50.0 if risk_score is None else _clip(risk_score, 0.0, 100.0)
            confidence_penalty = 50.0 if confidence_penalty is None else _clip(confidence_penalty, 0.0, 100.0)

            iv30 = self._extract_field(iv_data, 'iv30')
            iv60 = self._extract_field(iv_data, 'iv60')
            iv90 = self._extract_field(iv_data, 'iv90')
            slope = _safe_float((mc_data or {}).get('slope'))
            if slope is None and iv30 is not None and iv90 is not None:
                slope = iv30 - iv90

            delta_slope = _safe_float((mc_data or {}).get('delta_slope'))
            if delta_slope is None:
                slope_mc = _safe_float((mc_data or {}).get('slope_mc'))
                if slope is not None and slope_mc is not None:
                    delta_slope = slope - slope_mc

            term_score = _safe_float((mc_data or {}).get('term_score'))
            if term_score is None and all(v is not None for v in (iv30, iv60, iv90)):
                term_score = calculate_term_score(iv30, iv60, iv90, delta_slope=delta_slope)
            term_score = 50.0 if term_score is None else _clip(term_score, 0.0, 100.0)

            positioning_score = _safe_float((mc_data or {}).get('positioning_score'))
            positioning_details = None
            if positioning_score is None and iv_data is not None:
                positioning_score, positioning_details = calculate_positioning_score_from_iv(iv_data)
            positioning_score = 50.0 if positioning_score is None else _clip(positioning_score, 0.0, 100.0)

            iv30_chg = _safe_float((mc_data or {}).get('iv30_chg_pct'))
            if iv30_chg is None:
                iv30_chg = _safe_float((mc_data or {}).get('iv_change'))
            earnings_near = bool((mc_data or {}).get('earnings_near', False))
            trend_gate_pass = bool((mc_data or {}).get('trend_gate_pass', positioning_score >= 55))
            price_not_strong = bool((mc_data or {}).get('price_not_strong', (not trend_gate_pass) or (slope is None or slope > 0)))
            risk_score_rising = bool(iv30_chg is not None and iv30_chg > 0)

            event_heat = heat_score >= 70 and (risk_score >= 85 or earnings_near)
            trend_heat = heat_score >= 70 and risk_score < 80 and trend_gate_pass
            hedge_heat = bool(
                put_pct is not None and
                put_pct >= 60 and
                risk_score >= 75 and
                risk_score_rising and
                price_not_strong
            )

            overlay_label = base_heat_type if base_heat_type in {'trend', 'event', 'hedge', 'normal'} else 'normal'
            score_adjustment = 0.0
            position_suggestion = 'hold'

            if event_heat:
                overlay_label = 'event'
                score_adjustment = -18.0
                position_suggestion = 'reduce_exposure'
            elif trend_heat:
                overlay_label = 'trend'
                score_adjustment = +10.0
                position_suggestion = 'trend_confirmed'
            elif hedge_heat:
                overlay_label = 'hedge'
                score_adjustment = -8.0
                position_suggestion = 'stay_defensive'

            directional_confidence = 100.0 - confidence_penalty
            base_score = (
                0.35 * heat_score +
                0.25 * term_score +
                0.30 * positioning_score +
                0.10 * directional_confidence
            )
            risk_penalty = max(0.0, risk_score - 70.0) * 0.45
            raw_score = _clip(base_score - risk_penalty + score_adjustment, 0.0, 100.0)
            raw_score = round(raw_score, 2)

            components.update({
                'heat_score': round(heat_score, 2),
                'risk_score': round(risk_score, 2),
                'confidence_penalty': round(confidence_penalty, 2),
                'directional_confidence': round(directional_confidence, 2),
                'term_score': round(term_score, 2),
                'slope': round(slope, 4) if slope is not None else None,
                'delta_slope': round(delta_slope, 4) if delta_slope is not None else None,
                'positioning_score': round(positioning_score, 2),
                'overlay_label': overlay_label,
                'heat_type': overlay_label,
                'heat_type_legacy': to_legacy_heat_type(overlay_label),
                'position_suggestion': position_suggestion,
                'score_adjustment': score_adjustment,
                'risk_penalty': round(risk_penalty, 2),
                'base_score': round(base_score, 2),
                'event_heat': event_heat,
                'trend_heat': trend_heat,
                'source': 'mc+futu' if iv_data is not None else 'mc',
                'raw_score': raw_score,
            })

            if iv30 is not None:
                components['iv30_futu'] = iv30
            if iv60 is not None:
                components['iv60_futu'] = iv60
            if iv90 is not None:
                components['iv90_futu'] = iv90
            if positioning_details:
                components['positioning_inputs'] = positioning_details

            return {
                'score': raw_score,
                'raw_score': raw_score,
                'data': components,
            }
        except Exception as exc:
            logger.error(f"计算 {symbol} 期权确认分数失败: {exc}")
            return {
                'score': 50.0,
                'raw_score': None,
                'data': {'overlay_label': 'normal', 'position_suggestion': 'hold'},
            }

    def check_thresholds(
        self,
        rel_mom_data: Dict[str, Any],
        trend_data: Dict[str, Any],
        breadth_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        results: Dict[str, str] = {}
        all_pass = True

        trend_payload = (trend_data or {}).get('data') or {}
        rel_payload = (rel_mom_data or {}).get('data') or {}
        breadth_payload = (breadth_data or {}).get('data') or {}

        price_above_sma50 = bool(trend_payload.get('price_above_sma50'))
        results['price_above_sma50'] = 'PASS' if price_above_sma50 else 'FAIL'
        if not price_above_sma50:
            all_pass = False

        rs_20d = _safe_float(rel_payload.get('RS_20D'))
        if rs_20d is None:
            results['rs_20d_positive'] = 'NO_DATA'
            all_pass = False
        else:
            rs_pass = rs_20d > 0
            results['rs_20d_positive'] = 'PASS' if rs_pass else 'FAIL'
            if not rs_pass:
                all_pass = False

        pct_above_50 = _safe_float(breadth_payload.get('pct_above_sma50'))
        if pct_above_50 is None:
            results['breadth_above_40'] = 'NO_DATA'
        else:
            breadth_pass = pct_above_50 >= self.THRESHOLDS['breadth_min']
            results['breadth_above_40'] = 'PASS' if breadth_pass else 'FAIL'
            if not breadth_pass:
                all_pass = False

        return {'all_pass': all_pass, 'details': results}

    def _compose_total_score(
        self,
        normalized_features: Dict[str, Optional[float]],
        base_weights: Dict[str, float],
    ) -> Tuple[float, Dict[str, float]]:
        available_items = {
            key: value
            for key, value in normalized_features.items()
            if value is not None and key in base_weights
        }
        if not available_items:
            return 0.0, {}

        total_available_weight = sum(base_weights[key] for key in available_items)
        if total_available_weight <= 0:
            return 0.0, {}

        redistributed = {
            key: base_weights[key] / total_available_weight
            for key in available_items
        }
        total_score = sum(available_items[key] * redistributed[key] for key in available_items)
        return round(_clip(total_score, 0.0, 100.0), 2), redistributed

    def _build_symbol_modules(
        self,
        symbol: str,
        benchmark: str,
        holdings_data: Optional[List[Dict[str, Any]]],
        mc_data: Optional[Dict[str, Any]],
        iv_data: Optional[Any],
    ) -> Dict[str, Any]:
        rel_mom = self.calculate_rel_mom_score(symbol, benchmark)
        trend = self.calculate_trend_quality_score(symbol)
        breadth = self.calculate_breadth_score(symbol, holdings_data)
        options = self.calculate_options_confirm_score(symbol, mc_data=mc_data, iv_data=iv_data)

        raw_features = {
            'rel_mom_raw': rel_mom.get('raw_score'),
            'trend_quality_raw': trend.get('raw_score'),
            'breadth_raw': breadth.get('raw_score'),
            'options_raw': options.get('raw_score'),
        }
        return {
            'modules': {
                'rel_mom': rel_mom,
                'trend_quality': trend,
                'breadth': breadth,
                'options_confirm': options,
            },
            'raw_features': raw_features,
        }

    def calculate_composite_score(
        self,
        symbol: str,
        benchmark: str = 'SPY',
        holdings_data: Optional[List[Dict[str, Any]]] = None,
        mc_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # 复用 batch 流程，单样本时 normalize=50（中性），保证结构一致。
        results = self.batch_calculate_scores(
            symbols=[symbol],
            benchmark=benchmark,
            holdings_map={symbol: holdings_data or []},
            mc_map={symbol: mc_data or {}},
        )
        if results:
            return results[0]

        effective_weights = self._resolve_effective_weights()
        return {
            'symbol': symbol,
            'total_score': 0.0,
            'thresholds_pass': False,
            'thresholds': {
                'price_above_sma50': 'NO_DATA',
                'rs_20d_positive': 'NO_DATA',
                'breadth_above_50': 'NO_DATA',
            },
            'breakdown': {
                'rel_mom': {'score': 0.0, 'data': None},
                'trend_quality': {'score': 0.0, 'data': None},
                'breadth': {'score': 0.0, 'data': None},
                'options_confirm': {'score': 0.0, 'data': None},
                'raw_features': {},
                'normalized_features': {},
                'weight_allocation': {},
            },
            'weights': effective_weights,
            'weight_preset': self.weight_preset,
            'price_rs_alpha': self.price_rs_alpha,
        }

    def batch_calculate_scores(
        self,
        symbols: List[str],
        benchmark: str = 'SPY',
        holdings_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        mc_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        holdings_map = holdings_map or {}
        mc_map = mc_map or {}
        symbols = [str(s).upper() for s in symbols if str(s).strip()]
        if not symbols:
            return []

        iv_map = self._fetch_iv_map(symbols)
        effective_weights = self._resolve_effective_weights()

        symbol_payloads: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            try:
                symbol_payloads[symbol] = self._build_symbol_modules(
                    symbol=symbol,
                    benchmark=benchmark,
                    holdings_data=holdings_map.get(symbol),
                    mc_data=mc_map.get(symbol),
                    iv_data=iv_map.get(symbol),
                )
            except Exception as exc:
                logger.error(f"计算 {symbol} 原始特征失败: {exc}")
                continue

        # 横截面标准化
        rel_mom_map = {
            symbol: payload['raw_features'].get('rel_mom_raw')
            for symbol, payload in symbol_payloads.items()
        }
        trend_map = {
            symbol: payload['raw_features'].get('trend_quality_raw')
            for symbol, payload in symbol_payloads.items()
        }
        breadth_map = {
            symbol: payload['raw_features'].get('breadth_raw')
            for symbol, payload in symbol_payloads.items()
        }
        options_map = {
            symbol: payload['raw_features'].get('options_raw')
            for symbol, payload in symbol_payloads.items()
        }

        rel_mom_norm = rank_percentile_normalize(rel_mom_map, winsorize_limits=self.winsorize_limits)
        trend_norm = rank_percentile_normalize(trend_map, winsorize_limits=self.winsorize_limits)
        breadth_norm = rank_percentile_normalize(breadth_map, winsorize_limits=self.winsorize_limits)
        options_norm = rank_percentile_normalize(options_map, winsorize_limits=self.winsorize_limits)

        results: List[Dict[str, Any]] = []
        for symbol, payload in symbol_payloads.items():
            modules = payload['modules']
            raw_features = payload['raw_features']
            normalized_features = {
                'rel_mom_normalized': rel_mom_norm.get(symbol),
                'trend_quality_normalized': trend_norm.get(symbol),
                'breadth_normalized': breadth_norm.get(symbol),
                'options_normalized': options_norm.get(symbol),
            }
            normalized_by_module = {
                'rel_mom': normalized_features['rel_mom_normalized'],
                'trend_quality': normalized_features['trend_quality_normalized'],
                'breadth': normalized_features['breadth_normalized'],
                'options_confirm': normalized_features['options_normalized'],
            }

            total_score, redistributed_weights = self._compose_total_score(
                normalized_features=normalized_by_module,
                base_weights=effective_weights,
            )

            # 模块 score 用 normalized 分数（保持旧字段结构兼容）
            rel_mom_module = dict(modules['rel_mom'])
            trend_module = dict(modules['trend_quality'])
            breadth_module = dict(modules['breadth'])
            options_module = dict(modules['options_confirm'])

            rel_mom_module['score'] = round(rel_mom_norm.get(symbol) or 0.0, 2)
            trend_module['score'] = round(trend_norm.get(symbol) or 0.0, 2)
            breadth_module['score'] = round(breadth_norm.get(symbol) or 0.0, 2)
            options_module['score'] = round(options_norm.get(symbol) or 0.0, 2)

            thresholds = self.check_thresholds(
                rel_mom_data=rel_mom_module,
                trend_data=trend_module,
                breadth_data=breadth_module,
            )

            result = {
                'symbol': symbol,
                'total_score': total_score,
                'thresholds_pass': thresholds['all_pass'],
                'thresholds': thresholds['details'],
                'breakdown': {
                    'rel_mom': rel_mom_module,
                    'trend_quality': trend_module,
                    'breadth': breadth_module,
                    'options_confirm': options_module,
                    'raw_features': raw_features,
                    'normalized_features': normalized_features,
                    'weight_allocation': {
                        key: round(value, 6) for key, value in redistributed_weights.items()
                    },
                },
                'weights': effective_weights,
                'weight_preset': self.weight_preset,
                'price_rs_alpha': self.price_rs_alpha,
            }
            results.append(result)

        results.sort(key=lambda item: item.get('total_score', 0.0), reverse=True)
        return results

    def get_top_etfs(
        self,
        symbols: List[str],
        top_n: int = 5,
        must_pass_thresholds: bool = True,
    ) -> List[Dict[str, Any]]:
        all_results = self.batch_calculate_scores(symbols)
        if must_pass_thresholds:
            all_results = [item for item in all_results if item.get('thresholds_pass')]
        return all_results[:top_n]


def create_etf_calculator(ibkr, futu=None) -> ETFScoreCalculator:
    return ETFScoreCalculator(ibkr=ibkr, futu=futu)


SECTOR_ETFS = [
    'XLK',   # Technology
    'XLF',   # Financials
    'XLE',   # Energy
    'XLV',   # Health Care
    'XLI',   # Industrials
    'XLY',   # Consumer Discretionary
    'XLP',   # Consumer Staples
    'XLU',   # Utilities
    'XLB',   # Materials
    'XLRE',  # Real Estate
    'XLC',   # Communication Services
]


INDUSTRY_ETFS = [
    'SOXX',  # Semiconductors
    'IGV',   # Software
    'SMH',   # Semiconductors (VanEck)
    'XBI',   # Biotech
    'KBE',   # Banks
    'XOP',   # Oil & Gas Exploration
    'OIH',   # Oil Services
    'ITA',   # Aerospace & Defense
    'XRT',   # Retail
    'XHB',   # Homebuilders
    'IBB',   # Biotech (iShares)
]
