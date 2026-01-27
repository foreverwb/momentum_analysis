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
from datetime import datetime
import statistics
import logging

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
    
    # Call/Put 数据
    "Call Volume": "call_volume",
    "CallVolume": "call_volume",
    "Put Volume": "put_volume",
    "PutVolume": "put_volume",
    "Put %": "put_pct",
    "PutPct": "put_pct",
    "Call %": "call_pct",
    "CallPct": "call_pct",
    "P/C Ratio": "pc_ratio",
    "PCRatio": "pc_ratio",
    
    # 交易类型
    "% Single-Leg": "single_leg_pct",
    "SingleLegPct": "single_leg_pct",
    "% Multi Leg": "multi_leg_pct",
    "MultiLegPct": "multi_leg_pct",
    "% ContingentPct": "contingent_pct",
    "% Contingent": "contingent_pct",
    "ContingentPct": "contingent_pct",
    
    # IV 相关
    "Current IV30": "iv30",
    "IV30": "iv30",
    "IV30 % Rank": "ivr",
    "IVR": "ivr",
    "IV Rank": "ivr",
    "IV30 52-Week Position": "iv_52w_position",
    "IV52WPosition": "iv_52w_position",
    
    # 历史波动率
    "20-Day Historical Vol": "hv20",
    "HV20": "hv20",
    "1-Year Historical Vol": "hv1y",
    "HV1Y": "hv1y",
    "HV252": "hv1y",
    
    # IV 变化
    "Volatility % Chg": "iv30_chg_pct",
    "IV30ChgPct": "iv30_chg_pct",
    "IV % Change": "iv30_chg_pct",
    
    # OI 相关
    "Open Interest % Rank": "oi_pct_rank",
    "OIPctRank": "oi_pct_rank",
    "Open Interest": "open_interest",
    "OI": "open_interest",
    
    # 其他
    "Trade Count": "trade_count",
    "TradeCount": "trade_count",
    "Trades": "trade_count",
    "Earnings": "earnings_date",
    "Earnings Date": "earnings_date",
    "Days to Earnings": "days_to_earnings",
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
    
    count_below = sum(1 for v in valid_values if v < value)
    return (count_below / len(valid_values)) * 100


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
    # 相对名义价值排名（权重 60%）
    rel_notional_rank = _percentile_rank(
        data.get('rel_notional_to_90d'),
        [d.get('rel_notional_to_90d') for d in all_data]
    )
    
    # 相对成交量排名（权重 30%）
    rel_vol_rank = _percentile_rank(
        data.get('rel_vol_to_90d'),
        [d.get('rel_vol_to_90d') for d in all_data]
    )
    
    # 交易笔数排名（权重 10%）
    trade_count_rank = _percentile_rank(
        data.get('trade_count'),
        [d.get('trade_count') for d in all_data]
    )
    
    return 0.6 * rel_notional_rank + 0.3 * rel_vol_rank + 0.1 * trade_count_rank


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
    # IVR 排名（权重 50%）
    ivr_rank = _percentile_rank(
        data.get('ivr'),
        [d.get('ivr') for d in all_data]
    )
    
    # IV/HV 比率排名（权重 30%）
    iv30 = data.get('iv30', 0) or 0
    hv20 = data.get('hv20', 1) or 1
    hv20 = max(hv20, 0.01)  # 避免除零
    iv_hv_ratio = iv30 / hv20
    
    iv_hv_ratios = []
    for d in all_data:
        d_iv30 = d.get('iv30', 0) or 0
        d_hv20 = d.get('hv20', 1) or 1
        d_hv20 = max(d_hv20, 0.01)
        iv_hv_ratios.append(d_iv30 / d_hv20)
    
    iv_hv_rank = _percentile_rank(iv_hv_ratio, iv_hv_ratios)
    
    # IV 变化排名（权重 20%）
    iv_chg_rank = _percentile_rank(
        data.get('iv30_chg_pct'),
        [d.get('iv30_chg_pct') for d in all_data]
    )
    
    return 0.5 * ivr_rank + 0.3 * iv_hv_rank + 0.2 * iv_chg_rank


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
    # Multi-Leg 占比排名（权重 60%）
    multi_leg_rank = _percentile_rank(
        data.get('multi_leg_pct'),
        [d.get('multi_leg_pct') for d in all_data]
    )
    
    # Contingent 占比排名（权重 40%）
    contingent_rank = _percentile_rank(
        data.get('contingent_pct'),
        [d.get('contingent_pct') for d in all_data]
    )
    
    return 0.6 * multi_leg_rank + 0.4 * contingent_rank


def calculate_term_score(
    iv30: Optional[float], 
    iv60: Optional[float], 
    iv90: Optional[float]
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
    if not all([iv30, iv60, iv90]):
        return 50.0
    
    # 计算斜率
    slope_30_60 = (iv60 - iv30) / iv30 if iv30 > 0 else 0
    slope_60_90 = (iv90 - iv60) / iv60 if iv60 > 0 else 0
    
    # 正向期限结构得分高
    if slope_30_60 > 0 and slope_60_90 > 0:
        # 正向结构，斜率越陡，分数越高
        score = 70 + min(30, (slope_30_60 + slope_60_90) * 100)
    elif slope_30_60 < 0 and slope_60_90 < 0:
        # 倒挂结构（可能有事件）
        score = 30 + max(0, 20 + (slope_30_60 + slope_60_90) * 50)
    else:
        # 混合结构
        score = 50
    
    return min(100, max(0, score))


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
    risk_score: float
) -> str:
    """
    分类热度类型
    
    Args:
        data: 单条数据
        heat_score: 热度分数
        risk_score: 风险分数
    
    Returns:
        热度类型:
        - TREND_HEAT: 趋势热（热度高+风险适中）
        - EVENT_HEAT: 事件热（热度高+风险高）
        - HEDGE_HEAT: 对冲热（Put占比高+风险高）
        - NORMAL: 正常
    """
    put_pct = data.get('put_pct', 50) or 50
    
    if heat_score > 70 and risk_score < 80:
        return 'TREND_HEAT'
    elif heat_score > 70 and risk_score >= 80:
        return 'EVENT_HEAT'
    elif put_pct > 60 and risk_score > 70:
        return 'HEDGE_HEAT'
    else:
        return 'NORMAL'


def get_heat_type_details(heat_type: str) -> HeatClassification:
    """
    获取热度类型的详细说明
    
    Args:
        heat_type: 热度类型代码
    
    Returns:
        HeatClassification 对象
    """
    classifications = {
        'TREND_HEAT': HeatClassification(
            heat_type='TREND_HEAT',
            description='趋势热：高关注度 + 适中风险定价',
            trading_implication='可能有持续性的方向性交易机会'
        ),
        'EVENT_HEAT': HeatClassification(
            heat_type='EVENT_HEAT',
            description='事件热：高关注度 + 高风险定价',
            trading_implication='近期可能有重大事件（财报、FDA等），谨慎交易'
        ),
        'HEDGE_HEAT': HeatClassification(
            heat_type='HEDGE_HEAT',
            description='对冲热：Put占比高 + 高风险定价',
            trading_implication='机构可能在对冲，暗示下行风险'
        ),
        'NORMAL': HeatClassification(
            heat_type='NORMAL',
            description='正常：无明显异常',
            trading_implication='按常规策略操作'
        ),
    }
    return classifications.get(heat_type, classifications['NORMAL'])


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
        
        # 热度类型
        item['heat_type'] = classify_heat_type(
            item, item['heat_score'], item['risk_score']
        )
        
        # Put/Call 情绪
        pc_sentiment = calculate_put_call_sentiment(item)
        item['sentiment'] = pc_sentiment['sentiment']
        item['sentiment_score'] = pc_sentiment['sentiment_score']
        
        # 计算综合分数（可用于排序）
        # 综合分数 = 热度分数 × (1 - 置信度惩罚/100) × 风险调整因子
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
    
    # 如果有 IV 数据，计算 TermScore
    if iv_data:
        for item in parsed:
            symbol = item.get('symbol')
            if symbol and symbol in iv_data:
                iv_info = iv_data[symbol]
                # 支持 dict 和 dataclass
                if hasattr(iv_info, 'iv30'):
                    iv30 = iv_info.iv30
                    iv60 = iv_info.iv60
                    iv90 = iv_info.iv90
                else:
                    iv30 = iv_info.get('iv30')
                    iv60 = iv_info.get('iv60')
                    iv90 = iv_info.get('iv90')
                
                item['term_score'] = round(calculate_term_score(iv30, iv60, iv90), 2)
                item['iv30_futu'] = iv30
                item['iv60_futu'] = iv60
                item['iv90_futu'] = iv90
    
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
            if item.get('heat_type') not in heat_types:
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
        filtered = [d for d in data if d.get('heat_type') != 'EVENT_HEAT']
    
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