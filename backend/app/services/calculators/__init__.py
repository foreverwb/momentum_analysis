"""
Calculators Package
技术指标、评分等计算器

Modules:
- technical: 技术指标计算器 (SMA, EMA, RSI, MACD, OBV 等)
- etf_score: ETF 综合评分计算器
- stock_score: 个股评分计算器
- regime_gate: 市场环境 (Regime Gate) 计算器
"""

from .technical import (
    # 移动平均线
    calculate_sma,
    calculate_ema,
    calculate_wma,
    
    # 斜率与变化率
    calculate_sma_slope,
    calculate_sma_slope_pct,
    calculate_returns,
    calculate_multi_period_returns,
    
    # 回撤
    calculate_max_drawdown,
    calculate_current_drawdown,
    
    # 趋势指标
    calculate_trend_persistence,
    calculate_deviation_from_ma,
    calculate_distance_from_high,
    calculate_distance_from_52w_high,
    
    # 成交量指标
    calculate_obv,
    calculate_obv_trend,
    calculate_volume_ratio,
    calculate_relative_volume,
    calculate_breakout_volume_ratio,
    
    # 均线排列
    check_ma_alignment,
    calculate_ma_convergence,
    
    # 波动率
    calculate_historical_volatility,
    calculate_atr,
    calculate_atr_percent,
    
    # RSI & MACD
    calculate_rsi,
    calculate_macd,
    
    # 综合分析
    analyze_technical,
    get_technical_summary,
    TechnicalAnalysisResult,
)

__all__ = [
    # 移动平均线
    'calculate_sma',
    'calculate_ema',
    'calculate_wma',
    
    # 斜率与变化率
    'calculate_sma_slope',
    'calculate_sma_slope_pct',
    'calculate_returns',
    'calculate_multi_period_returns',
    
    # 回撤
    'calculate_max_drawdown',
    'calculate_current_drawdown',
    
    # 趋势指标
    'calculate_trend_persistence',
    'calculate_deviation_from_ma',
    'calculate_distance_from_high',
    'calculate_distance_from_52w_high',
    
    # 成交量指标
    'calculate_obv',
    'calculate_obv_trend',
    'calculate_volume_ratio',
    'calculate_relative_volume',
    'calculate_breakout_volume_ratio',
    
    # 均线排列
    'check_ma_alignment',
    'calculate_ma_convergence',
    
    # 波动率
    'calculate_historical_volatility',
    'calculate_atr',
    'calculate_atr_percent',
    
    # RSI & MACD
    'calculate_rsi',
    'calculate_macd',
    
    # 综合分析
    'analyze_technical',
    'get_technical_summary',
    'TechnicalAnalysisResult',
]

# ETF 评分计算器
from .etf_score import (
    ETFScoreCalculator,
    create_etf_calculator,
    SECTOR_ETFS,
    INDUSTRY_ETFS,
)

# 个股评分计算器
from .stock_score import (
    StockScoreCalculator,
    create_stock_calculator,
)

# Regime Gate 计算器
from .regime_gate import (
    RegimeGateCalculator,
    create_regime_calculator,
    get_quick_regime,
)

__all__ += [
    # ETF 评分
    'ETFScoreCalculator',
    'create_etf_calculator',
    'SECTOR_ETFS',
    'INDUSTRY_ETFS',
    
    # 个股评分
    'StockScoreCalculator',
    'create_stock_calculator',
    
    # Regime Gate
    'RegimeGateCalculator',
    'create_regime_calculator',
    'get_quick_regime',
]