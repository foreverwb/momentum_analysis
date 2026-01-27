"""
Parsers Package
数据解析器 (Finviz, MarketChameleon等)

Modules:
- finviz_parser: Finviz 技术指标数据解析
- mc_parser: MarketChameleon 期权数据解析
"""

from .finviz_parser import (
    # 解析函数
    parse_finviz_json,
    parse_finviz_csv,
    parse_percentage,
    parse_number,
    
    # 验证
    validate_finviz_data,
    
    # 广度指标
    calculate_breadth_metrics,
    calculate_sector_breadth,
    
    # 筛选与排序
    filter_stocks,
    sort_stocks,
    
    # 统计
    get_summary_statistics,
    
    # 常量
    FINVIZ_FIELD_MAPPING,
)

from .mc_parser import (
    # 解析函数
    parse_mc_json,
    process_mc_data,
    process_mc_data_with_iv,
    
    # 评分计算
    calculate_heat_score,
    calculate_risk_score,
    calculate_confidence_penalty,
    calculate_term_score,
    calculate_put_call_sentiment,
    
    # 分类
    classify_heat_type,
    get_heat_type_details,
    HeatClassification,
    
    # 筛选与排序
    filter_mc_data,
    sort_mc_data,
    get_top_heat_stocks,
    
    # 统计
    get_mc_summary,
    
    # 常量
    MC_FIELD_MAPPING,
)

__all__ = [
    # Finviz
    'parse_finviz_json',
    'parse_finviz_csv',
    'parse_percentage',
    'parse_number',
    'validate_finviz_data',
    'calculate_breadth_metrics',
    'calculate_sector_breadth',
    'filter_stocks',
    'sort_stocks',
    'get_summary_statistics',
    'FINVIZ_FIELD_MAPPING',
    
    # MarketChameleon
    'parse_mc_json',
    'process_mc_data',
    'process_mc_data_with_iv',
    'calculate_heat_score',
    'calculate_risk_score',
    'calculate_confidence_penalty',
    'calculate_term_score',
    'calculate_put_call_sentiment',
    'classify_heat_type',
    'get_heat_type_details',
    'HeatClassification',
    'filter_mc_data',
    'sort_mc_data',
    'get_top_heat_stocks',
    'get_mc_summary',
    'MC_FIELD_MAPPING',
]