"""
Finviz 数据解析器
解析用户导入的 Finviz 技术指标 JSON 数据

提供功能：
- 解析 Finviz 导出的 JSON 数据
- 字段标准化映射
- 数据验证
- 广度指标计算（% above SMA, near 52W high/low）
- 批量处理与统计
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)


# ==================== Finviz 字段映射 ====================

FINVIZ_FIELD_MAPPING = {
    # 基础信息
    'Ticker': 'symbol',
    'Company': 'company_name',
    'Sector': 'sector',
    'Industry': 'industry',
    'Country': 'country',
    
    # 价格数据
    'Price': 'price',
    'Change': 'change_pct',
    'Volume': 'volume',
    'Avg Volume': 'avg_volume',
    'Rel Volume': 'rel_volume',
    
    # 均线
    'SMA20': 'sma20',
    'SMA50': 'sma50',
    'SMA200': 'sma200',
    
    # 52周数据
    '52W High': 'week52_high',
    '52W Low': 'week52_low',
    '52W Range': 'week52_range',
    
    # 技术指标
    'RSI': 'rsi',
    'RSI (14)': 'rsi',
    'Beta': 'beta',
    'ATR': 'atr',
    'ATR (14)': 'atr',
    'Volatility': 'volatility',
    'Volatility W': 'volatility_week',
    'Volatility M': 'volatility_month',
    
    # 业绩表现
    'Perf Week': 'perf_week',
    'Perf Month': 'perf_month',
    'Perf Quart': 'perf_quarter',
    'Perf Quarter': 'perf_quarter',
    'Perf Half': 'perf_half',
    'Perf Year': 'perf_year',
    'Perf YTD': 'perf_ytd',
    
    # 基本面
    'Market Cap': 'market_cap',
    'P/E': 'pe_ratio',
    'Forward P/E': 'forward_pe',
    'PEG': 'peg',
    'P/S': 'ps_ratio',
    'P/B': 'pb_ratio',
    'EPS (ttm)': 'eps_ttm',
    'EPS next Y': 'eps_next_year',
    'EPS growth next Y': 'eps_growth_next_year',
    'Dividend': 'dividend_yield',
    'Dividend %': 'dividend_yield',
    
    # 其他
    'Target Price': 'target_price',
    'Recom': 'analyst_recom',
    'Optionable': 'optionable',
    'Shortable': 'shortable',
    'Short Float': 'short_float',
    'Short Ratio': 'short_ratio',
    'Earnings': 'earnings_date',
    'Earnings Date': 'earnings_date',
}

# 需要解析为百分比的字段
PERCENTAGE_FIELDS = {
    'change_pct', 'perf_week', 'perf_month', 'perf_quarter', 
    'perf_half', 'perf_year', 'perf_ytd', 'dividend_yield',
    'eps_growth_next_year', 'short_float', 'volatility',
    'volatility_week', 'volatility_month', 'sma20', 'sma50', 'sma200'
}

# 数值字段
NUMERIC_FIELDS = {
    'price', 'atr', 'week52_high', 'week52_low', 'rsi', 'beta',
    'volume', 'avg_volume', 'rel_volume', 'market_cap', 
    'pe_ratio', 'forward_pe', 'peg', 'ps_ratio', 'pb_ratio',
    'eps_ttm', 'eps_next_year', 'target_price', 'analyst_recom',
    'short_ratio'
}


# ==================== 解析辅助函数 ====================

def parse_percentage(value: Any) -> Optional[float]:
    """
    解析百分比字符串
    
    支持格式：
    - "5.23%" -> 0.0523
    - "-2.1%" -> -0.021
    - 5.23 -> 0.0523 (假设已经是百分比数值)
    
    Args:
        value: 原始值
    
    Returns:
        小数形式的百分比，或 None
    """
    if value is None or value == '' or value == '-':
        return None
    
    if isinstance(value, (int, float)):
        # 如果是小数值且较小，假设已经是百分比形式
        if abs(value) < 10:
            return float(value) / 100
        return float(value)
    
    if isinstance(value, str):
        value = value.strip()
        if '%' in value:
            try:
                return float(value.replace('%', '').replace(',', '')) / 100
            except ValueError:
                return None
        # 尝试解析纯数字字符串
        try:
            num = float(value.replace(',', ''))
            # 如果值在合理的百分比范围内
            if -100 <= num <= 1000:
                return num / 100
            return num
        except ValueError:
            return None
    
    return None


def parse_number(value: Any) -> Optional[float]:
    """
    解析数字字符串
    
    支持格式：
    - "1,234.56" -> 1234.56
    - "1.5K" -> 1500
    - "2.3M" -> 2300000
    - "1.2B" -> 1200000000
    - "1.5T" -> 1500000000000
    
    Args:
        value: 原始值
    
    Returns:
        数值，或 None
    """
    if value is None or value == '' or value == '-':
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
    
    if isinstance(value, str):
        value = value.strip().replace(',', '').replace('$', '')
        
        # 处理 K/M/B/T 后缀
        multipliers = {
            'K': 1e3, 'k': 1e3,
            'M': 1e6, 'm': 1e6,
            'B': 1e9, 'b': 1e9,
            'T': 1e12, 't': 1e12,
        }
        
        for suffix, mult in multipliers.items():
            if value.endswith(suffix):
                try:
                    return float(value[:-1]) * mult
                except ValueError:
                    return None
        
        # 普通数字
        try:
            return float(value)
        except ValueError:
            return None
    
    return None


def parse_sma_deviation(value: Any) -> Optional[float]:
    """
    解析 SMA 偏离值
    
    Finviz 的 SMA20/50/200 字段表示价格相对于 SMA 的偏离百分比
    如 "5.23%" 表示价格高于 SMA 5.23%
    
    Args:
        value: 原始值
    
    Returns:
        偏离百分比（小数形式）
    """
    return parse_percentage(value)


# ==================== 主解析函数 ====================

def parse_finviz_json(json_data: List[Dict]) -> List[Dict]:
    """
    解析 Finviz 导出的 JSON 数据
    
    Args:
        json_data: Finviz 导出的原始 JSON 列表
    
    Returns:
        标准化后的数据列表
    """
    results = []
    
    for item in json_data:
        parsed = {}
        
        for finviz_key, our_key in FINVIZ_FIELD_MAPPING.items():
            if finviz_key in item:
                value = item[finviz_key]
                
                # 根据字段类型选择解析方法
                if our_key in PERCENTAGE_FIELDS:
                    if our_key in ('sma20', 'sma50', 'sma200'):
                        parsed[our_key] = parse_sma_deviation(value)
                    else:
                        parsed[our_key] = parse_percentage(value)
                elif our_key in NUMERIC_FIELDS:
                    parsed[our_key] = parse_number(value)
                else:
                    # 保持原值（字符串字段）
                    parsed[our_key] = value if value != '-' else None
        
        # 只添加有 symbol 的记录
        if parsed.get('symbol'):
            # 清理 symbol（去除空格和特殊字符）
            parsed['symbol'] = parsed['symbol'].strip().upper()
            results.append(parsed)
    
    logger.info(f"成功解析 {len(results)} 条 Finviz 数据")
    return results


def parse_finviz_csv(csv_text: str) -> List[Dict]:
    """
    解析 Finviz 导出的 CSV 文本
    
    Args:
        csv_text: CSV 格式的文本
    
    Returns:
        标准化后的数据列表
    """
    import csv
    from io import StringIO
    
    reader = csv.DictReader(StringIO(csv_text))
    json_data = list(reader)
    return parse_finviz_json(json_data)


# ==================== 数据验证 ====================

@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    total_records: int
    field_coverage: Dict[str, float]
    missing_required_fields: List[str]
    warnings: List[str]


def validate_finviz_data(parsed_data: List[Dict]) -> Dict:
    """
    验证解析后的数据完整性
    
    Args:
        parsed_data: 解析后的数据列表
    
    Returns:
        验证结果字典
    """
    total = len(parsed_data)
    
    if total == 0:
        return {
            'is_valid': False,
            'total_records': 0,
            'field_coverage': {},
            'missing_required_fields': ['symbol'],
            'warnings': ['数据为空']
        }
    
    # 统计各字段的填充率
    field_counts = {}
    for item in parsed_data:
        for key, value in item.items():
            if value is not None:
                field_counts[key] = field_counts.get(key, 0) + 1
    
    field_coverage = {k: v / total for k, v in field_counts.items()}
    
    # 检查必要字段（至少 80% 的记录有值）
    required_fields = ['symbol', 'price']
    important_fields = ['sma20', 'sma50', 'rsi', 'volume']
    
    missing_required = []
    warnings = []
    
    for field in required_fields:
        if field_counts.get(field, 0) < total * 0.8:
            missing_required.append(field)
    
    for field in important_fields:
        coverage = field_coverage.get(field, 0)
        if coverage < 0.5:
            warnings.append(f"字段 '{field}' 覆盖率较低 ({coverage:.1%})")
    
    return {
        'is_valid': len(missing_required) == 0,
        'total_records': total,
        'field_coverage': field_coverage,
        'missing_required_fields': missing_required,
        'warnings': warnings
    }


# ==================== 广度指标计算 ====================

@dataclass
class BreadthMetrics:
    """广度指标"""
    pct_above_sma20: float
    pct_above_sma50: float
    pct_above_sma200: float
    pct_near_52w_high: float
    pct_near_52w_low: float
    avg_rsi: float
    total_count: int


def calculate_breadth_metrics(parsed_data: List[Dict]) -> Dict:
    """
    从 Finviz 数据计算广度指标
    
    广度指标用于评估整体市场或板块的健康程度
    
    Args:
        parsed_data: 解析后的数据列表
    
    Returns:
        广度统计数据
    """
    total = len(parsed_data)
    
    if total == 0:
        return {
            'pct_above_sma20': 0,
            'pct_above_sma50': 0,
            'pct_above_sma200': 0,
            'pct_near_52w_high': 0,
            'pct_near_52w_low': 0,
            'avg_rsi': 50,
            'total_count': 0
        }
    
    above_sma20 = 0
    above_sma50 = 0
    above_sma200 = 0
    near_52w_high = 0
    near_52w_low = 0
    rsi_values = []
    
    for d in parsed_data:
        price = d.get('price')
        
        # SMA 偏离 > 0 表示价格在均线上方
        sma20_dev = d.get('sma20')  # 这是偏离百分比
        sma50_dev = d.get('sma50')
        sma200_dev = d.get('sma200')
        
        high_52w = d.get('week52_high')
        low_52w = d.get('week52_low')
        rsi = d.get('rsi')
        
        # 计算均线上方比例
        # Finviz 的 SMA 字段是偏离百分比，正值表示在均线上方
        if sma20_dev is not None and sma20_dev > 0:
            above_sma20 += 1
        if sma50_dev is not None and sma50_dev > 0:
            above_sma50 += 1
        if sma200_dev is not None and sma200_dev > 0:
            above_sma200 += 1
        
        # 52周高低点附近（5%以内）
        if price and high_52w and price > high_52w * 0.95:
            near_52w_high += 1
        if price and low_52w and price < low_52w * 1.05:
            near_52w_low += 1
        
        # RSI
        if rsi is not None:
            rsi_values.append(rsi)
    
    avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else 50.0
    
    return {
        'pct_above_sma20': above_sma20 / total,
        'pct_above_sma50': above_sma50 / total,
        'pct_above_sma200': above_sma200 / total,
        'pct_near_52w_high': near_52w_high / total,
        'pct_near_52w_low': near_52w_low / total,
        'avg_rsi': avg_rsi,
        'total_count': total
    }


def calculate_sector_breadth(parsed_data: List[Dict]) -> Dict[str, Dict]:
    """
    按板块计算广度指标
    
    Args:
        parsed_data: 解析后的数据列表
    
    Returns:
        {sector: breadth_metrics} 字典
    """
    # 按板块分组
    sector_data = {}
    for item in parsed_data:
        sector = item.get('sector', 'Unknown')
        if sector not in sector_data:
            sector_data[sector] = []
        sector_data[sector].append(item)
    
    # 计算每个板块的广度
    results = {}
    for sector, data in sector_data.items():
        results[sector] = calculate_breadth_metrics(data)
    
    return results


# ==================== 筛选与排序 ====================

def filter_stocks(
    parsed_data: List[Dict],
    min_price: float = None,
    max_price: float = None,
    min_volume: float = None,
    above_sma20: bool = None,
    above_sma50: bool = None,
    above_sma200: bool = None,
    min_rsi: float = None,
    max_rsi: float = None,
    near_52w_high: bool = None,
    sectors: List[str] = None,
) -> List[Dict]:
    """
    根据条件筛选股票
    
    Args:
        parsed_data: 解析后的数据列表
        min_price: 最低价格
        max_price: 最高价格
        min_volume: 最低成交量
        above_sma20: 是否在 SMA20 上方
        above_sma50: 是否在 SMA50 上方
        above_sma200: 是否在 SMA200 上方
        min_rsi: 最低 RSI
        max_rsi: 最高 RSI
        near_52w_high: 是否接近 52 周高点
        sectors: 板块列表
    
    Returns:
        符合条件的股票列表
    """
    results = []
    
    for item in parsed_data:
        # 价格筛选
        price = item.get('price')
        if min_price is not None and (price is None or price < min_price):
            continue
        if max_price is not None and (price is None or price > max_price):
            continue
        
        # 成交量筛选
        volume = item.get('avg_volume')
        if min_volume is not None and (volume is None or volume < min_volume):
            continue
        
        # SMA 筛选
        if above_sma20 is not None:
            sma20_dev = item.get('sma20')
            if sma20_dev is None or (above_sma20 and sma20_dev <= 0) or (not above_sma20 and sma20_dev > 0):
                continue
        
        if above_sma50 is not None:
            sma50_dev = item.get('sma50')
            if sma50_dev is None or (above_sma50 and sma50_dev <= 0) or (not above_sma50 and sma50_dev > 0):
                continue
        
        if above_sma200 is not None:
            sma200_dev = item.get('sma200')
            if sma200_dev is None or (above_sma200 and sma200_dev <= 0) or (not above_sma200 and sma200_dev > 0):
                continue
        
        # RSI 筛选
        rsi = item.get('rsi')
        if min_rsi is not None and (rsi is None or rsi < min_rsi):
            continue
        if max_rsi is not None and (rsi is None or rsi > max_rsi):
            continue
        
        # 52周高点筛选
        if near_52w_high is not None:
            high_52w = item.get('week52_high')
            is_near = price and high_52w and price > high_52w * 0.95
            if near_52w_high and not is_near:
                continue
            if not near_52w_high and is_near:
                continue
        
        # 板块筛选
        if sectors is not None:
            sector = item.get('sector')
            if sector not in sectors:
                continue
        
        results.append(item)
    
    return results


def sort_stocks(
    parsed_data: List[Dict],
    sort_by: str = 'perf_week',
    ascending: bool = False
) -> List[Dict]:
    """
    排序股票
    
    Args:
        parsed_data: 数据列表
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
    
    return sorted(parsed_data, key=get_sort_key, reverse=not ascending)


# ==================== 汇总统计 ====================

def get_summary_statistics(parsed_data: List[Dict]) -> Dict:
    """
    获取汇总统计
    
    Args:
        parsed_data: 解析后的数据列表
    
    Returns:
        统计摘要
    """
    if not parsed_data:
        return {}
    
    # 收集数值
    prices = [d['price'] for d in parsed_data if d.get('price') is not None]
    changes = [d['change_pct'] for d in parsed_data if d.get('change_pct') is not None]
    rsi_values = [d['rsi'] for d in parsed_data if d.get('rsi') is not None]
    
    # 计算统计量
    import statistics
    
    def safe_stats(values):
        if not values:
            return {'mean': None, 'median': None, 'stdev': None}
        result = {
            'mean': statistics.mean(values),
            'median': statistics.median(values),
        }
        if len(values) > 1:
            result['stdev'] = statistics.stdev(values)
        else:
            result['stdev'] = 0
        return result
    
    # 表现分布
    gainers = len([c for c in changes if c and c > 0])
    losers = len([c for c in changes if c and c < 0])
    unchanged = len(changes) - gainers - losers
    
    return {
        'total_stocks': len(parsed_data),
        'price_stats': safe_stats(prices),
        'change_stats': safe_stats(changes),
        'rsi_stats': safe_stats(rsi_values),
        'gainers': gainers,
        'losers': losers,
        'unchanged': unchanged,
        'advance_decline_ratio': gainers / losers if losers > 0 else float('inf'),
        'breadth': calculate_breadth_metrics(parsed_data),
    }