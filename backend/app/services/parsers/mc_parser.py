"""
MarketChameleon 数据解析器
解析用户导入的 MarketChameleon 期权数据 JSON

提供功能：
- 解析 MarketChameleon 导出的 JSON 数据
- 计算 HeatScore（热度分数）
- 计算 RiskScore（风险定价分数）
- 计算 ConfidencePenalty（方向置信度惩罚）
- 计算 TermScore（期限结构分数）
- 热度类型分类（趋势热/事件热/对冲热）
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, date
import statistics
import logging

from app.core.time_utils import beijing_today

logger = logging.getLogger(__name__)


# ==================== MarketChameleon 字段映射 ====================

MC_FIELD_MAPPING = {
    # 基础信息
    "symbol": "symbol",
    "Symbol": "symbol",
    "Ticker": "symbol",
    
    # 成交量相关
    "Relative Volume to 90-Day Avg": "rel_vol_to_90d",
    "Rel Volume to 90-Day Avg": "rel_vol_to_90d",
    "RelVolume90d": "rel_vol_to_90d",
    "Relative Notional to 90-Day Avg": "rel_notional_to_90d",
    "Rel Notional to 90-Day Avg": "rel_notional_to_90d",
    "RelNotional90d": "rel_notional_to_90d",
    "RelNotionalTo90D": "rel_notional_to_90d",
    "RelVolTo90D": "rel_vol_to_90d",
    "rel_notional": "rel_notional",
    "rel_notional_to_90d": "rel_notional_to_90d",
    "rel_vol": "rel_vol",
    "rel_vol_to_90d": "rel_vol_to_90d",
    
    # Call/Put 数据
    "Call Volume": "call_volume",
    "CallVolume": "call_volume",
    "Call Notional": "call_notional",
    "CallNotional": "call_notional",
    "Put Volume": "put_volume",
    "PutVolume": "put_volume",
    "Put Notional": "put_notional",
    "PutNotional": "put_notional",
    "call_notional": "call_notional",
    "put_notional": "put_notional",
    "Put %": "put_pct",
    "PutPct": "put_pct",
    "put_pct": "put_pct",
    "Call %": "call_pct",
    "CallPct": "call_pct",
    "call_pct": "call_pct",
    "P/C Ratio": "pc_ratio",
    "PCRatio": "pc_ratio",
    "pc_ratio": "pc_ratio",
    
    # 交易类型
    "% Single-Leg": "single_leg_pct",
    "SingleLegPct": "single_leg_pct",
    "% Multi Leg": "multi_leg_pct",
    "MultiLegPct": "multi_leg_pct",
    "multi_leg_pct": "multi_leg_pct",
    "% ContingentPct": "contingent_pct",
    "% Contingent": "contingent_pct",
    "ContingentPct": "contingent_pct",
    "contingent_pct": "contingent_pct",
    
    # IV 相关
    "Current IV30": "iv30",
    "IV30": "iv30",
    "iv30": "iv30",
    "iv60": "iv60",
    "iv90": "iv90",
    "IV30 % Rank": "ivr",
    "IVR": "ivr",
    "IV Rank": "ivr",
    "ivr": "ivr",
    "IV30 52-Week Position": "iv_52w_position",
    "IV52WPosition": "iv_52w_position",
    "IV_52W_P": "iv_52w_position",
    "IV/HV Ratio": "iv_hv_ratio",
    "IVHVRatio": "iv_hv_ratio",
    "IV_HV_Ratio": "iv_hv_ratio",
    "iv_hv_ratio": "iv_hv_ratio",
    
    # 历史波动率
    "20-Day Historical Vol": "hv20",
    "HV20": "hv20",
    "hv20": "hv20",
    "1-Year Historical Vol": "hv1y",
    "HV1Y": "hv1y",
    "HV252": "hv1y",
    
    # IV 变化
    "Volatility % Chg": "iv30_chg_pct",
    "IV30ChgPct": "iv30_chg_pct",
    "IV % Change": "iv30_chg_pct",
    "iv30_chg_pct": "iv30_chg_pct",
    "iv_change": "iv30_chg_pct",
    
    # OI 相关
    "Open Interest % Rank": "oi_pct_rank",
    "OIPctRank": "oi_pct_rank",
    "OI_PctRank": "oi_pct_rank",
    "Open Interest": "open_interest",
    "OI": "open_interest",
    
    # 其他
    "Trade Count": "trade_count",
    "TradeCount": "trade_count",
    "Trades": "trade_count",
    "trade_count": "trade_count",
    "Earnings": "earnings_date",
    "Earnings Date": "earnings_date",
    "earnings_date": "earnings_date",
    "Days to Earnings": "days_to_earnings",
    "days_to_earnings": "days_to_earnings",
}


# ==================== 解析辅助函数 ====================

def _parse_value(value: Any) -> Optional[float]:
    """
    解析数值（处理百分比和普通数字）
    
    Args:
        value: 原始值
    
    Returns:
        解析后的数值
    """
    if value is None or value == '' or value == '-' or value == 'N/A':
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
    
    if isinstance(value, str):
        value = value.strip()
        
        # 处理百分比
        if '%' in value:
            try:
                return float(value.replace('%', '').replace(',', ''))
            except ValueError:
                return None
        
        # 处理 K/M/B 后缀
        multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9}
        for suffix, mult in multipliers.items():
            if value.upper().endswith(suffix):
                try:
                    return float(value[:-1].replace(',', '')) * mult
                except ValueError:
                    return None
        
        # 普通数字
        try:
            return float(value.replace(',', ''))
        except ValueError:
            return None
    
    return None


def _percentile_rank(value: Optional[float], all_values: List[Optional[float]]) -> float:
    """
    计算百分位排名
    
    Args:
        value: 要计算排名的值
        all_values: 所有值的列表
    
    Returns:
        0-100 之间的百分位排名
    """
    if value is None:
        return 50.0  # 无数据时返回中位数
    
    valid_values = [v for v in all_values if v is not None]
    if not valid_values:
        return 50.0
    if len(valid_values) == 1:
        return 50.0
    
    count_below = sum(1 for v in valid_values if v < value)
    return (count_below / len(valid_values)) * 100


HEAT_TYPE_MAP = {
    'trend': 'trend',
    'trend_heat': 'trend',
    'event': 'event',
    'event_heat': 'event',
    'hedge': 'hedge',
    'hedge_heat': 'hedge',
    'normal': 'normal',
}

HEAT_TYPE_LEGACY_MAP = {
    'trend': 'TREND_HEAT',
    'event': 'EVENT_HEAT',
    'hedge': 'HEDGE_HEAT',
    'normal': 'NORMAL',
}


def normalize_heat_type(value: Any, default: str = 'normal') -> str:
    text = str(value or '').strip().lower().replace(' ', '_')
    if text in HEAT_TYPE_MAP:
        return HEAT_TYPE_MAP[text]
    if 'trend' in text:
        return 'trend'
    if 'event' in text:
        return 'event'
    if 'hedge' in text:
        return 'hedge'
    if 'normal' in text:
        return 'normal'
    return default


def to_legacy_heat_type(value: Any) -> str:
    return HEAT_TYPE_LEGACY_MAP[normalize_heat_type(value)]


def _value_from_keys(data: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for key in keys:
        if key not in data:
            continue
        parsed = _parse_value(data.get(key))
        if parsed is not None:
            return parsed
    return None


def _weighted_rank_score(rank_values: List[Tuple[Optional[float], List[Optional[float]], float]]) -> float:
    total_weight = 0.0
    weighted_score = 0.0
    for value, all_values, weight in rank_values:
        if weight <= 0:
            continue
        if value is None:
            continue
        weighted_score += weight * _percentile_rank(value, all_values)
        total_weight += weight
    if total_weight <= 0:
        return 50.0
    return weighted_score / total_weight


def _parse_earnings_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {'-', 'N/A', 'None'}:
        return None
    head = text.split()[0]
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _is_earnings_near(data: Dict[str, Any], horizon_days: int = 7) -> bool:
    days_to_earnings = _parse_value(data.get('days_to_earnings'))
    if days_to_earnings is not None:
        return 0 <= days_to_earnings <= horizon_days
    earnings_date = _parse_earnings_date(data.get('earnings_date'))
    if earnings_date is None:
        return False
    delta_days = (earnings_date - beijing_today()).days
    return 0 <= delta_days <= horizon_days


# ==================== 主解析函数 ====================

def parse_mc_json(json_data: List[Dict]) -> List[Dict]:
    """
    解析 MarketChameleon 导出的 JSON 数据
    
    Args:
        json_data: MC 导出的原始 JSON 列表
    
    Returns:
        标准化后的数据列表
    """
    results = []
    
    for item in json_data:
        parsed = {}
        
        for mc_key, our_key in MC_FIELD_MAPPING.items():
            if mc_key in item:
                value = item[mc_key]
                # symbol 字段保持原值，不作为数字解析
                if our_key == 'symbol':
                    parsed[our_key] = str(value) if value else None
                # 财报事件字段是文本（如 "29-Jan-2026 AMC"），不能按数值解析
                elif our_key == 'earnings_date':
                    if value is None:
                        parsed[our_key] = None
                    else:
                        text_value = str(value).strip()
                        parsed[our_key] = text_value if text_value and text_value not in {'-', 'N/A'} else None
                else:
                    parsed[our_key] = _parse_value(value)
        
        # 只添加有 symbol 的记录
        if parsed.get('symbol'):
            # 清理 symbol
            symbol = parsed['symbol']
            if isinstance(symbol, str):
                parsed['symbol'] = symbol.strip().upper()
            results.append(parsed)
    
    logger.info(f"成功解析 {len(results)} 条 MarketChameleon 数据")
    return results


# ==================== 评分计算 ====================

def calculate_heat_score(data: Dict, all_data: List[Dict]) -> float:
    """
    计算热度分数 (HeatScore)
    
    衡量期权市场对该标的的关注程度
    
    公式: 0.6×rank(RelNotionalTo90D) + 0.3×rank(RelVolTo90D) + 0.1×rank(TradeCount)
    
    Args:
        data: 单条数据
        all_data: 所有数据（用于计算排名）
    
    Returns:
        0-100 的热度分数
    """
    rel_notional = _value_from_keys(
        data,
        ['rel_notional_to_90d', 'rel_notional'],
    )
    rel_vol = _value_from_keys(
        data,
        ['rel_vol_to_90d', 'rel_vol'],
    )
    trade_count = _value_from_keys(
        data,
        ['trade_count'],
    )

    # 在缺失 rel_notional/trade_count 的源数据里用更弱代理兜底。
    if rel_notional is None:
        call_notional = _value_from_keys(data, ['call_notional'])
        put_notional = _value_from_keys(data, ['put_notional'])
        if call_notional is not None or put_notional is not None:
            rel_notional = (call_notional or 0.0) + (put_notional or 0.0)

    if trade_count is None:
        call_volume = _value_from_keys(data, ['call_volume'])
        put_volume = _value_from_keys(data, ['put_volume'])
        if call_volume is not None or put_volume is not None:
            trade_count = (call_volume or 0.0) + (put_volume or 0.0)

    rel_notional_all = [
        _value_from_keys(item, ['rel_notional_to_90d', 'rel_notional'])
        or (
            (_value_from_keys(item, ['call_notional']) or 0.0)
            + (_value_from_keys(item, ['put_notional']) or 0.0)
            if _value_from_keys(item, ['call_notional']) is not None
            or _value_from_keys(item, ['put_notional']) is not None
            else None
        )
        for item in all_data
    ]
    rel_vol_all = [
        _value_from_keys(item, ['rel_vol_to_90d', 'rel_vol'])
        for item in all_data
    ]
    trade_count_all = [
        _value_from_keys(item, ['trade_count'])
        or (
            (_value_from_keys(item, ['call_volume']) or 0.0)
            + (_value_from_keys(item, ['put_volume']) or 0.0)
            if _value_from_keys(item, ['call_volume']) is not None
            or _value_from_keys(item, ['put_volume']) is not None
            else None
        )
        for item in all_data
    ]

    score = _weighted_rank_score(
        [
            (rel_notional, rel_notional_all, 0.6),
            (rel_vol, rel_vol_all, 0.3),
            (trade_count, trade_count_all, 0.1),
        ]
    )
    return round(score, 2)


def calculate_risk_score(data: Dict, all_data: List[Dict]) -> float:
    """
    计算风险定价分数 (RiskScore)
    
    衡量期权市场对该标的风险的定价程度
    
    公式: 0.5×rank(IVR) + 0.3×rank(IV30/HV20) + 0.2×rank(IV30ChgPct)
    
    Args:
        data: 单条数据
        all_data: 所有数据
    
    Returns:
        0-100 的风险分数
    """
    ivr = _value_from_keys(data, ['ivr', 'iv_52w_position'])

    iv_hv_ratio = _value_from_keys(data, ['iv_hv_ratio'])
    if iv_hv_ratio is None:
        iv30 = _value_from_keys(data, ['iv30'])
        hv20 = _value_from_keys(data, ['hv20'])
        if iv30 is not None and hv20 is not None and hv20 > 0:
            iv_hv_ratio = iv30 / max(hv20, 0.01)

    iv30_chg = _value_from_keys(data, ['iv30_chg_pct', 'iv_change'])

    ivr_all = [_value_from_keys(item, ['ivr', 'iv_52w_position']) for item in all_data]

    iv_hv_all: List[Optional[float]] = []
    for item in all_data:
        ratio = _value_from_keys(item, ['iv_hv_ratio'])
        if ratio is None:
            d_iv30 = _value_from_keys(item, ['iv30'])
            d_hv20 = _value_from_keys(item, ['hv20'])
            if d_iv30 is not None and d_hv20 is not None and d_hv20 > 0:
                ratio = d_iv30 / max(d_hv20, 0.01)
        iv_hv_all.append(ratio)

    iv30_chg_all = [_value_from_keys(item, ['iv30_chg_pct', 'iv_change']) for item in all_data]

    score = _weighted_rank_score(
        [
            (ivr, ivr_all, 0.5),
            (iv_hv_ratio, iv_hv_all, 0.3),
            (iv30_chg, iv30_chg_all, 0.2),
        ]
    )
    return round(score, 2)


def calculate_confidence_penalty(data: Dict, all_data: List[Dict]) -> float:
    """
    计算方向置信度惩罚 (ConfidencePenalty)
    
    高 Multi-Leg 和 Contingent 交易占比意味着机构在做对冲或套利，
    方向性信号较弱
    
    公式: 0.6×rank(MultiLegPct) + 0.4×rank(ContingentPct)
    
    Args:
        data: 单条数据
        all_data: 所有数据
    
    Returns:
        0-100 的惩罚分数（越高表示方向性越弱）
    """
    multi_leg = _value_from_keys(data, ['multi_leg_pct'])
    contingent = _value_from_keys(data, ['contingent_pct'])
    multi_leg_all = [_value_from_keys(item, ['multi_leg_pct']) for item in all_data]
    contingent_all = [_value_from_keys(item, ['contingent_pct']) for item in all_data]

    score = _weighted_rank_score(
        [
            (multi_leg, multi_leg_all, 0.6),
            (contingent, contingent_all, 0.4),
        ]
    )
    return round(score, 2)


def calculate_term_score(
    iv30: Optional[float], 
    iv60: Optional[float], 
    iv90: Optional[float],
    delta_slope: Optional[float] = None,
) -> float:
    """
    计算期限结构分数 (TermScore)
    
    基于 IV 期限结构的陡峭程度
    - 正向期限结构（IV30 < IV60 < IV90）：市场平静，得分高
    - 倒挂（IV30 > IV60 > IV90）：可能有近期事件，得分低
    
    Args:
        iv30: 30天 IV
        iv60: 60天 IV
        iv90: 90天 IV
    
    Returns:
        0-100 的期限结构分数
    """
    if iv30 is None or iv60 is None or iv90 is None:
        return 50.0
    
    slope = iv30 - iv90
    slope30_60 = iv60 - iv30
    slope60_90 = iv90 - iv60

    # 以 slope 为主，辅以局部形态。
    # slope > 0: 短端更贵，事件/恐慌风险提升 => 评分偏低。
    # slope < 0: 常态/正向结构 => 评分偏高。
    slope_penalty = max(0.0, slope) * 2.2
    slope_bonus = max(0.0, -slope) * 1.4
    local_shape_bonus = 6.0 if slope30_60 > 0 and slope60_90 > 0 else 0.0
    local_shape_penalty = 6.0 if slope30_60 < 0 and slope60_90 < 0 else 0.0
    score = 55.0 + slope_bonus - slope_penalty + local_shape_bonus - local_shape_penalty

    # ΔSlope > 0 代表近端相对远端继续抬升（风险在加速）。
    if delta_slope is not None:
        score -= max(0.0, delta_slope) * 1.2
        score += max(0.0, -delta_slope) * 0.5

    return round(min(100.0, max(0.0, score)), 2)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_iv_field(iv_info: Any, field_name: str) -> Optional[float]:
    if iv_info is None:
        return None

    # dataclass/object path
    if hasattr(iv_info, field_name):
        return _coerce_float(getattr(iv_info, field_name))

    # dict path
    if isinstance(iv_info, dict):
        return _coerce_float(iv_info.get(field_name))

    return None


def calculate_positioning_score_from_iv(iv_info: Any) -> Tuple[float, Dict[str, Optional[float]]]:
    """
    基于富途 bucket OI 与滚动 ΔOI 估算定位分数 (0-100)。

    偏向中长端（8-30D / 31-90D）净增，避免把近端事件噪声当作趋势确认。
    """
    bucket_weights = {
        '0_7': 0.20,
        '8_30': 0.45,
        '31_90': 0.35,
    }
    horizon_weights = {
        '3d': 0.35,
        '5d': 0.65,
    }

    components: List[float] = []
    details: Dict[str, Optional[float]] = {}
    call_put_imbalance: List[float] = []

    for suffix in ('0_7', '8_30', '31_90'):
        bucket_total = _extract_iv_field(iv_info, f'oi_bucket_{suffix}')
        call_delta_1d = _extract_iv_field(iv_info, f'call_delta_oi_{suffix}')
        put_delta_1d = _extract_iv_field(iv_info, f'put_delta_oi_{suffix}')
        delta3d = _extract_iv_field(iv_info, f'net_delta3d_{suffix}')
        delta5d = _extract_iv_field(iv_info, f'net_delta5d_{suffix}')
        delta1d = _extract_iv_field(iv_info, f'net_delta_oi_{suffix}')

        if bucket_total and bucket_total > 0:
            ratio3d = (delta3d / bucket_total) if delta3d is not None else None
            ratio5d = (delta5d / bucket_total) if delta5d is not None else None
            ratio1d = (delta1d / bucket_total) if delta1d is not None else None
        else:
            ratio3d = None
            ratio5d = None
            ratio1d = None

        bucket_component = 0.0
        bucket_component_weight = 0.0
        if ratio3d is not None:
            bucket_component += horizon_weights['3d'] * ratio3d
            bucket_component_weight += horizon_weights['3d']
        if ratio5d is not None:
            bucket_component += horizon_weights['5d'] * ratio5d
            bucket_component_weight += horizon_weights['5d']
        if bucket_component_weight == 0.0 and ratio1d is not None:
            bucket_component = ratio1d
            bucket_component_weight = 1.0

        if bucket_component_weight > 0:
            components.append(bucket_weights[suffix] * (bucket_component / bucket_component_weight))

        if (
            call_delta_1d is not None and
            put_delta_1d is not None and
            bucket_total is not None and
            bucket_total > 0
        ):
            call_put_imbalance.append((put_delta_1d - call_delta_1d) / bucket_total)

        details[f'bucket_{suffix}_ratio_3d'] = ratio3d
        details[f'bucket_{suffix}_ratio_5d'] = ratio5d
        details[f'bucket_{suffix}_ratio_1d'] = ratio1d
        details[f'net_delta3d_{suffix}'] = delta3d
        details[f'net_delta5d_{suffix}'] = delta5d
        details[f'call_delta_oi_{suffix}'] = call_delta_1d
        details[f'put_delta_oi_{suffix}'] = put_delta_1d
        details[f'oi_bucket_{suffix}'] = bucket_total

    positioning_raw = sum(components) if components else 0.0
    score = 50.0 + positioning_raw * 380.0
    score = max(0.0, min(100.0, score))

    hedge_pressure = statistics.mean(call_put_imbalance) if call_put_imbalance else None
    details['hedge_pressure'] = hedge_pressure

    return round(score, 2), details


def calculate_put_call_sentiment(data: Dict) -> Dict:
    """
    计算 Put/Call 情绪指标
    
    Args:
        data: 单条数据
    
    Returns:
        情绪指标字典
    """
    put_pct = data.get('put_pct', 50) or 50
    call_pct = data.get('call_pct', 50) or (100 - put_pct)
    
    # P/C 比率
    pc_ratio = data.get('pc_ratio')
    if pc_ratio is None and call_pct > 0:
        pc_ratio = put_pct / call_pct
    
    # 情绪判断
    if put_pct > 60:
        sentiment = 'bearish'
        sentiment_score = -1 * min(1, (put_pct - 50) / 30)
    elif put_pct < 40:
        sentiment = 'bullish'
        sentiment_score = min(1, (50 - put_pct) / 30)
    else:
        sentiment = 'neutral'
        sentiment_score = 0
    
    return {
        'put_pct': put_pct,
        'call_pct': call_pct,
        'pc_ratio': pc_ratio,
        'sentiment': sentiment,
        'sentiment_score': sentiment_score
    }


# ==================== 热度类型分类 ====================

@dataclass
class HeatClassification:
    """热度分类结果"""
    heat_type: str
    description: str
    trading_implication: str


def classify_heat_type(
    data: Dict,
    heat_score: float,
    risk_score: float,
    trend_gate_pass: Optional[bool] = None,
    price_not_strong: Optional[bool] = None,
    risk_score_rising: Optional[bool] = None,
    earnings_near: Optional[bool] = None,
) -> str:
    """
    分类热度类型
    
    Args:
        data: 单条数据
        heat_score: 热度分数
        risk_score: 风险分数
    
    Returns:
        热度类型（统一小写）:
        - trend: 趋势热
        - event: 事件热
        - hedge: 对冲热
        - normal: 正常
    """
    put_pct = _value_from_keys(data, ['put_pct']) or 50.0
    heat_high = heat_score >= 70
    risk_extreme = risk_score >= 85
    risk_high = risk_score >= 75

    if trend_gate_pass is None:
        trend_gate_pass = bool(data.get('trend_gate_pass', data.get('thresholds_pass', True)))
    if price_not_strong is None:
        price_not_strong = bool(data.get('price_not_strong', data.get('price_below_sma50', True)))
    if risk_score_rising is None:
        iv30_chg = _value_from_keys(data, ['iv30_chg_pct', 'iv_change'])
        risk_score_rising = bool(iv30_chg is not None and iv30_chg > 0)
    if earnings_near is None:
        earnings_near = _is_earnings_near(data, horizon_days=7)

    if heat_high and (risk_extreme or earnings_near):
        return 'event'
    if heat_high and risk_score < 80 and trend_gate_pass:
        return 'trend'
    if put_pct >= 60 and risk_high and risk_score_rising and price_not_strong:
        return 'hedge'
    return 'normal'


def get_heat_type_details(heat_type: str) -> HeatClassification:
    """
    获取热度类型的详细说明
    
    Args:
        heat_type: 热度类型代码
    
    Returns:
        HeatClassification 对象
    """
    normalized = normalize_heat_type(heat_type)
    classifications = {
        'trend': HeatClassification(
            heat_type='trend',
            description='趋势热：高关注度 + 适中风险定价',
            trading_implication='可能有持续性的方向性交易机会'
        ),
        'event': HeatClassification(
            heat_type='event',
            description='事件热：高关注度 + 高风险定价',
            trading_implication='近期可能有重大事件（财报、FDA等），谨慎交易'
        ),
        'hedge': HeatClassification(
            heat_type='hedge',
            description='对冲热：Put占比高 + 高风险定价',
            trading_implication='机构可能在对冲，暗示下行风险'
        ),
        'normal': HeatClassification(
            heat_type='normal',
            description='正常：无明显异常',
            trading_implication='按常规策略操作'
        ),
    }
    return classifications.get(normalized, classifications['normal'])


# ==================== 完整处理流程 ====================

def process_mc_data(json_data: List[Dict]) -> List[Dict]:
    """
    完整处理 MarketChameleon 数据
    
    解析 + 计算所有评分
    
    Args:
        json_data: 原始 JSON 数据
    
    Returns:
        处理后的数据列表（包含所有计算的分数）
    """
    # 1. 解析原始数据
    parsed = parse_mc_json(json_data)
    
    if not parsed:
        logger.warning("没有有效数据可处理")
        return []
    
    # 2. 计算各项分数
    for item in parsed:
        # 热度分数
        item['heat_score'] = round(calculate_heat_score(item, parsed), 2)
        
        # 风险分数
        item['risk_score'] = round(calculate_risk_score(item, parsed), 2)
        
        # 方向置信度惩罚
        item['confidence_penalty'] = round(calculate_confidence_penalty(item, parsed), 2)

        iv30 = _value_from_keys(item, ['iv30'])
        iv60 = _value_from_keys(item, ['iv60'])
        iv90 = _value_from_keys(item, ['iv90'])
        if iv30 is not None and iv60 is not None and iv90 is not None:
            item['term_score'] = round(calculate_term_score(iv30, iv60, iv90), 2)

        iv30_chg = _value_from_keys(item, ['iv30_chg_pct', 'iv_change'])
        item['risk_score_rising'] = bool(iv30_chg is not None and iv30_chg > 0)
        item['earnings_near'] = _is_earnings_near(item, horizon_days=7)
        
        # 热度类型
        item['heat_type'] = classify_heat_type(
            item,
            item['heat_score'],
            item['risk_score'],
            trend_gate_pass=True,
            price_not_strong=None,
            risk_score_rising=item.get('risk_score_rising'),
            earnings_near=item.get('earnings_near'),
        )
        item['heat_type_legacy'] = to_legacy_heat_type(item['heat_type'])
        
        # Put/Call 情绪
        pc_sentiment = calculate_put_call_sentiment(item)
        item['sentiment'] = pc_sentiment['sentiment']
        item['sentiment_score'] = pc_sentiment['sentiment_score']
        
        # 计算综合分数（可用于排序）
        # 综合分数 = 热度分数 × (1 - 置信度惩罚/200) × 风险调整因子
        risk_factor = 1.0 if item['risk_score'] < 80 else 0.8
        item['composite_score'] = round(
            item['heat_score'] * (1 - item['confidence_penalty'] / 200) * risk_factor, 2
        )
    
    logger.info(f"完成 {len(parsed)} 条数据的评分计算")
    return parsed


def process_mc_data_with_iv(
    json_data: List[Dict],
    iv_data: Dict[str, Any] = None
) -> List[Dict]:
    """
    处理 MarketChameleon 数据并整合 IV 期限结构数据
    
    Args:
        json_data: MC 原始数据
        iv_data: 从 Futu 获取的 IV 数据 {symbol: IVTermResult}
    
    Returns:
        处理后的数据列表
    """
    # 基础处理
    parsed = process_mc_data(json_data)

    for item in parsed:
        # 先基于 MC 自身 IV 计算 baseline slope，作为 delta_slope 参考
        mc_iv30 = _coerce_float(item.get('iv30'))
        mc_iv60 = _coerce_float(item.get('iv60'))
        mc_iv90 = _coerce_float(item.get('iv90'))
        mc_slope = (mc_iv30 - mc_iv90) if (mc_iv30 is not None and mc_iv90 is not None) else None
        if mc_slope is not None:
            item['slope_mc'] = round(mc_slope, 4)

        # 若尚无 term_score，先用 MC 版本兜底
        if item.get('term_score') is None and all(v is not None for v in (mc_iv30, mc_iv60, mc_iv90)):
            item['term_score'] = round(calculate_term_score(mc_iv30, mc_iv60, mc_iv90), 2)

        symbol = item.get('symbol')
        iv_info = iv_data.get(symbol) if (iv_data and symbol) else None
        if not iv_info:
            continue

        iv30 = _extract_iv_field(iv_info, 'iv30')
        iv60 = _extract_iv_field(iv_info, 'iv60')
        iv90 = _extract_iv_field(iv_info, 'iv90')
        slope = (iv30 - iv90) if (iv30 is not None and iv90 is not None) else None
        delta_slope = (slope - mc_slope) if (slope is not None and mc_slope is not None) else None

        term_score = calculate_term_score(iv30, iv60, iv90, delta_slope=delta_slope) if all(
            v is not None for v in (iv30, iv60, iv90)
        ) else (item.get('term_score') or 50.0)
        positioning_score, positioning_inputs = calculate_positioning_score_from_iv(iv_info)

        heat_score = _coerce_float(item.get('heat_score')) or 50.0
        risk_score = _coerce_float(item.get('risk_score')) or 50.0
        confidence_penalty = _coerce_float(item.get('confidence_penalty')) or 50.0
        iv30_chg = _value_from_keys(item, ['iv30_chg_pct', 'iv_change'])
        risk_score_rising = bool(iv30_chg is not None and iv30_chg > 0)
        earnings_near = _is_earnings_near(item, horizon_days=7)
        trend_gate_pass = bool(item.get('trend_gate_pass', item.get('thresholds_pass', positioning_score >= 55)))
        price_not_strong = bool(
            item.get('price_not_strong', (slope is None or slope > 0))
            or (slope is not None and slope > 0)
        )
        label = classify_heat_type(
            item,
            heat_score=heat_score,
            risk_score=risk_score,
            trend_gate_pass=trend_gate_pass,
            price_not_strong=price_not_strong,
            risk_score_rising=risk_score_rising,
            earnings_near=earnings_near,
        )

        item['term_score'] = round(float(term_score), 2)
        item['slope'] = round(slope, 4) if slope is not None else None
        item['delta_slope'] = round(delta_slope, 4) if delta_slope is not None else None
        item['positioning_score'] = positioning_score
        item['overlay_label'] = label
        item['heat_type'] = label
        item['heat_type_legacy'] = to_legacy_heat_type(label)
        item['risk_score_rising'] = risk_score_rising
        item['earnings_near'] = earnings_near
        item['iv30_futu'] = iv30
        item['iv60_futu'] = iv60
        item['iv90_futu'] = iv90
        item['positioning_inputs'] = positioning_inputs

        # 将方向性置信度作为补充风险信息对外透出，供 overlay 使用
        item['directional_confidence'] = round(max(0.0, 100.0 - confidence_penalty), 2)

    return parsed


# ==================== 筛选与排序 ====================

def filter_mc_data(
    data: List[Dict],
    min_heat_score: float = None,
    max_heat_score: float = None,
    min_risk_score: float = None,
    max_risk_score: float = None,
    heat_types: List[str] = None,
    min_ivr: float = None,
    max_ivr: float = None,
) -> List[Dict]:
    """
    筛选 MC 数据
    
    Args:
        data: 处理后的数据列表
        min_heat_score: 最低热度分数
        max_heat_score: 最高热度分数
        min_risk_score: 最低风险分数
        max_risk_score: 最高风险分数
        heat_types: 热度类型列表
        min_ivr: 最低 IVR
        max_ivr: 最高 IVR
    
    Returns:
        筛选后的数据列表
    """
    results = []
    
    for item in data:
        # 热度分数筛选
        heat = item.get('heat_score', 0)
        if min_heat_score is not None and heat < min_heat_score:
            continue
        if max_heat_score is not None and heat > max_heat_score:
            continue
        
        # 风险分数筛选
        risk = item.get('risk_score', 0)
        if min_risk_score is not None and risk < min_risk_score:
            continue
        if max_risk_score is not None and risk > max_risk_score:
            continue
        
        # 热度类型筛选
        if heat_types is not None:
            normalized_allowed = {normalize_heat_type(value) for value in heat_types}
            if normalize_heat_type(item.get('heat_type')) not in normalized_allowed:
                continue
        
        # IVR 筛选
        ivr = item.get('ivr')
        if min_ivr is not None and (ivr is None or ivr < min_ivr):
            continue
        if max_ivr is not None and (ivr is None or ivr > max_ivr):
            continue
        
        results.append(item)
    
    return results


def sort_mc_data(
    data: List[Dict],
    sort_by: str = 'heat_score',
    ascending: bool = False
) -> List[Dict]:
    """
    排序 MC 数据
    
    Args:
        data: 数据列表
        sort_by: 排序字段
        ascending: 是否升序
    
    Returns:
        排序后的列表
    """
    def get_sort_key(item):
        value = item.get(sort_by)
        if value is None:
            return float('-inf') if not ascending else float('inf')
        return value
    
    return sorted(data, key=get_sort_key, reverse=not ascending)


def get_top_heat_stocks(
    data: List[Dict],
    n: int = 10,
    exclude_event_heat: bool = False
) -> List[Dict]:
    """
    获取热度最高的股票
    
    Args:
        data: 处理后的数据列表
        n: 返回数量
        exclude_event_heat: 是否排除事件热
    
    Returns:
        Top N 热度股票
    """
    filtered = data
    if exclude_event_heat:
        filtered = [d for d in data if normalize_heat_type(d.get('heat_type')) != 'event']
    
    sorted_data = sort_mc_data(filtered, 'heat_score', ascending=False)
    return sorted_data[:n]


# ==================== 汇总统计 ====================

def get_mc_summary(data: List[Dict]) -> Dict:
    """
    获取 MC 数据汇总统计
    
    Args:
        data: 处理后的数据列表
    
    Returns:
        统计摘要
    """
    if not data:
        return {}
    
    heat_scores = [d['heat_score'] for d in data if d.get('heat_score') is not None]
    risk_scores = [d['risk_score'] for d in data if d.get('risk_score') is not None]
    
    # 热度类型分布
    heat_type_counts = {}
    for item in data:
        ht = item.get('heat_type', 'UNKNOWN')
        heat_type_counts[ht] = heat_type_counts.get(ht, 0) + 1
    
    # 情绪分布
    sentiment_counts = {'bullish': 0, 'neutral': 0, 'bearish': 0}
    for item in data:
        sentiment = item.get('sentiment', 'neutral')
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
    
    return {
        'total_stocks': len(data),
        'heat_score_stats': {
            'mean': statistics.mean(heat_scores) if heat_scores else 0,
            'median': statistics.median(heat_scores) if heat_scores else 0,
            'max': max(heat_scores) if heat_scores else 0,
            'min': min(heat_scores) if heat_scores else 0,
        },
        'risk_score_stats': {
            'mean': statistics.mean(risk_scores) if risk_scores else 0,
            'median': statistics.median(risk_scores) if risk_scores else 0,
            'max': max(risk_scores) if risk_scores else 0,
            'min': min(risk_scores) if risk_scores else 0,
        },
        'heat_type_distribution': heat_type_counts,
        'sentiment_distribution': sentiment_counts,
        'high_heat_count': len([s for s in heat_scores if s > 70]),
        'high_risk_count': len([s for s in risk_scores if s > 80]),
    }
