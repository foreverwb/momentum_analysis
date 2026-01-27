"""
技术指标计算器
基于 IBKR 获取的价格数据进行本地计算

提供功能：
- 移动平均线 (SMA/EMA)
- 斜率计算
- 收益率计算
- 回撤计算
- 趋势持续度
- OBV (On Balance Volume)
- 均线排列检测
- 突破检测
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


# ==================== 移动平均线 ====================

def calculate_sma(prices: pd.Series, window: int) -> pd.Series:
    """
    计算简单移动平均线 (Simple Moving Average)
    
    Args:
        prices: 价格序列
        window: 窗口期
    
    Returns:
        SMA 序列
    """
    return prices.rolling(window=window).mean()


def calculate_ema(prices: pd.Series, window: int) -> pd.Series:
    """
    计算指数移动平均线 (Exponential Moving Average)
    
    Args:
        prices: 价格序列
        window: 窗口期（span）
    
    Returns:
        EMA 序列
    """
    return prices.ewm(span=window, adjust=False).mean()


def calculate_wma(prices: pd.Series, window: int) -> pd.Series:
    """
    计算加权移动平均线 (Weighted Moving Average)
    
    Args:
        prices: 价格序列
        window: 窗口期
    
    Returns:
        WMA 序列
    """
    weights = np.arange(1, window + 1)
    return prices.rolling(window).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


# ==================== 斜率与变化率 ====================

def calculate_sma_slope(sma: pd.Series, period: int = 5) -> float:
    """
    计算 SMA 斜率 (5日)
    
    公式: (SMA_t - SMA_{t-5}) / 5
    
    Args:
        sma: SMA 序列
        period: 斜率计算周期
    
    Returns:
        斜率值（每日变化量）
    """
    if len(sma) < period:
        return 0.0
    return (sma.iloc[-1] - sma.iloc[-period]) / period


def calculate_sma_slope_pct(sma: pd.Series, period: int = 5) -> float:
    """
    计算 SMA 斜率百分比
    
    公式: (SMA_t - SMA_{t-5}) / SMA_{t-5}
    
    Args:
        sma: SMA 序列
        period: 斜率计算周期
    
    Returns:
        斜率百分比
    """
    if len(sma) < period:
        return 0.0
    base = sma.iloc[-period]
    if base == 0:
        return 0.0
    return (sma.iloc[-1] - base) / base


def calculate_returns(prices: pd.Series, period: int) -> float:
    """
    计算收益率
    
    公式: (P_t - P_{t-n}) / P_{t-n}
    
    Args:
        prices: 价格序列
        period: 收益率计算周期
    
    Returns:
        收益率（小数形式，如 0.05 表示 5%）
    """
    if len(prices) < period + 1:
        return 0.0
    base = prices.iloc[-period - 1]
    if base == 0:
        return 0.0
    return (prices.iloc[-1] - base) / base


def calculate_multi_period_returns(prices: pd.Series) -> Dict[str, float]:
    """
    计算多周期收益率
    
    Returns:
        包含 5D, 10D, 20D, 63D 收益率的字典
    """
    return {
        'return_5d': calculate_returns(prices, 5),
        'return_10d': calculate_returns(prices, 10),
        'return_20d': calculate_returns(prices, 20),
        'return_63d': calculate_returns(prices, 63),
    }


# ==================== 回撤计算 ====================

def calculate_max_drawdown(prices: pd.Series, window: int = 20) -> float:
    """
    计算窗口期内最大回撤
    
    Args:
        prices: 价格序列
        window: 回撤计算窗口
    
    Returns:
        最大回撤（负值），如 -0.08 表示 -8% 回撤
    """
    if len(prices) < window:
        return 0.0
    
    window_prices = prices.iloc[-window:]
    peak = window_prices.expanding().max()
    drawdown = (window_prices - peak) / peak
    return float(drawdown.min())


def calculate_current_drawdown(prices: pd.Series, lookback: int = 252) -> float:
    """
    计算当前回撤（距离 lookback 期内最高点的回撤）
    
    Args:
        prices: 价格序列
        lookback: 回看周期（默认 252 天 = 1年）
    
    Returns:
        当前回撤（负值或0）
    """
    if len(prices) < 2:
        return 0.0
    
    lookback_prices = prices.iloc[-min(lookback, len(prices)):]
    peak = lookback_prices.max()
    current = prices.iloc[-1]
    
    if peak == 0:
        return 0.0
    
    return (current - peak) / peak


# ==================== 趋势指标 ====================

def calculate_trend_persistence(
    prices: pd.Series, 
    sma: pd.Series, 
    window: int = 20
) -> float:
    """
    计算趋势持续度
    
    公式: count(Price > SMA) / window
    
    Args:
        prices: 价格序列
        sma: SMA 序列
        window: 计算窗口
    
    Returns:
        0-1 之间的值，越高表示趋势越持续
    """
    if len(prices) < window or len(sma) < window:
        return 0.0
    
    recent_prices = prices.iloc[-window:]
    recent_sma = sma.iloc[-window:]
    above_count = (recent_prices > recent_sma).sum()
    return above_count / window


def calculate_deviation_from_ma(price: float, ma: float) -> float:
    """
    计算偏离均线程度
    
    公式: (Price - MA) / MA
    
    Args:
        price: 当前价格
        ma: 移动平均值
    
    Returns:
        偏离百分比（正值表示在均线上方）
    """
    if ma == 0:
        return 0.0
    return (price - ma) / ma


def calculate_distance_from_high(current_price: float, high_20d: float) -> float:
    """
    计算距离20日高点的距离
    
    Args:
        current_price: 当前价格
        high_20d: 20日最高价
    
    Returns:
        比率，如 0.98 表示当前价格是高点的 98%（距高点 2%）
    """
    if high_20d == 0:
        return 0.0
    return current_price / high_20d


def calculate_distance_from_52w_high(current_price: float, high_52w: float) -> float:
    """
    计算距离52周高点的百分比
    
    Returns:
        百分比（负值），如 -0.05 表示距离高点 5%
    """
    if high_52w == 0:
        return 0.0
    return (current_price - high_52w) / high_52w


# ==================== 成交量指标 ====================

def calculate_obv(prices: pd.Series, volumes: pd.Series) -> pd.Series:
    """
    计算 OBV (On Balance Volume)
    
    规则：
    - 价格上涨：OBV += volume
    - 价格下跌：OBV -= volume
    - 价格不变：OBV 不变
    
    Args:
        prices: 价格序列
        volumes: 成交量序列
    
    Returns:
        OBV 序列
    """
    obv = [0]
    for i in range(1, len(prices)):
        if prices.iloc[i] > prices.iloc[i - 1]:
            obv.append(obv[-1] + volumes.iloc[i])
        elif prices.iloc[i] < prices.iloc[i - 1]:
            obv.append(obv[-1] - volumes.iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=prices.index)


def calculate_obv_trend(obv: pd.Series, window: int = 20) -> str:
    """
    判断 OBV 趋势
    
    Args:
        obv: OBV 序列
        window: 判断窗口
    
    Returns:
        'Strong' / 'Weak' / 'Neutral'
    """
    if len(obv) < window:
        return 'Neutral'
    
    obv_sma = calculate_sma(obv, window)
    current_obv = obv.iloc[-1]
    current_sma = obv_sma.iloc[-1]
    
    # 计算 OBV 变化率
    base_obv = obv.iloc[-window]
    obv_change = (current_obv - base_obv) / abs(base_obv) if base_obv != 0 else 0
    
    if current_obv > current_sma and obv_change > 0.1:
        return 'Strong'
    elif current_obv < current_sma and obv_change < -0.1:
        return 'Weak'
    return 'Neutral'


def calculate_volume_ratio(current_volume: int, avg_volume: float) -> float:
    """
    计算成交量相对于均量的倍数
    
    Args:
        current_volume: 当前成交量
        avg_volume: 平均成交量
    
    Returns:
        倍数（如 1.5 表示 1.5 倍于平均量）
    """
    if avg_volume == 0:
        return 0.0
    return current_volume / avg_volume


def calculate_relative_volume(
    volumes: pd.Series, 
    current_volume: int = None, 
    avg_window: int = 20
) -> float:
    """
    计算相对成交量
    
    Args:
        volumes: 成交量序列
        current_volume: 当前成交量（如不提供则使用序列最后一个值）
        avg_window: 平均量计算窗口
    
    Returns:
        相对成交量倍数
    """
    if len(volumes) < avg_window:
        return 1.0
    
    if current_volume is None:
        current_volume = volumes.iloc[-1]
    
    avg_volume = volumes.iloc[-avg_window:].mean()
    return calculate_volume_ratio(current_volume, avg_volume)


def calculate_breakout_volume_ratio(
    prices: pd.Series, 
    volumes: pd.Series, 
    lookback: int = 5,
    volume_avg_window: int = 20
) -> float:
    """
    计算突破时的放量倍数
    
    检测最近 lookback 天内是否有突破，如有则返回放量倍数
    
    Args:
        prices: 价格序列
        volumes: 成交量序列
        lookback: 检测突破的回看天数
        volume_avg_window: 平均量计算窗口
    
    Returns:
        突破时的放量倍数（无突破返回 1.0）
    """
    if len(prices) < lookback + volume_avg_window:
        return 1.0
    
    avg_volume = volumes.iloc[-(volume_avg_window + lookback):-lookback].mean()
    
    # 检查是否有向上突破
    recent_high = prices.iloc[-lookback:].max()
    prior_high = prices.iloc[-(lookback + 20):-lookback].max()
    
    if recent_high > prior_high:
        # 找到突破那天的成交量
        breakout_idx = prices.iloc[-lookback:].idxmax()
        breakout_volume = volumes.loc[breakout_idx]
        return breakout_volume / avg_volume if avg_volume > 0 else 1.0
    
    return 1.0


# ==================== 均线排列 ====================

def check_ma_alignment(
    price: float, 
    sma20: float, 
    sma50: float, 
    sma200: float = None
) -> Dict:
    """
    检查均线排列
    
    Args:
        price: 当前价格
        sma20: 20日均线
        sma50: 50日均线
        sma200: 200日均线（可选）
    
    Returns:
        均线排列状态字典
    """
    result = {
        'price_above_sma20': price > sma20,
        'price_above_sma50': price > sma50,
        'sma20_above_sma50': sma20 > sma50,
        'alignment': 'mixed'
    }
    
    # 判断基本排列
    if price > sma20 > sma50:
        result['alignment'] = 'bullish'
    elif price < sma20 < sma50:
        result['alignment'] = 'bearish'
    
    # 如果有 SMA200，进一步判断
    if sma200 is not None:
        result['price_above_sma200'] = price > sma200
        result['sma50_above_sma200'] = sma50 > sma200
        
        if price > sma20 > sma50 > sma200:
            result['alignment'] = 'strong_bullish'
        elif price < sma20 < sma50 < sma200:
            result['alignment'] = 'strong_bearish'
    
    return result


def calculate_ma_convergence(sma20: float, sma50: float, sma200: float = None) -> Dict:
    """
    计算均线收敛/发散程度
    
    Returns:
        均线间距和收敛状态
    """
    result = {
        'sma20_50_spread': (sma20 - sma50) / sma50 if sma50 != 0 else 0,
    }
    
    if sma200 is not None:
        result['sma50_200_spread'] = (sma50 - sma200) / sma200 if sma200 != 0 else 0
        result['sma20_200_spread'] = (sma20 - sma200) / sma200 if sma200 != 0 else 0
    
    return result


# ==================== 波动率指标 ====================

def calculate_historical_volatility(prices: pd.Series, window: int = 20) -> float:
    """
    计算历史波动率 (HV)
    
    使用日收益率的标准差，年化
    
    Args:
        prices: 价格序列
        window: 计算窗口
    
    Returns:
        年化波动率（如 0.25 表示 25%）
    """
    if len(prices) < window + 1:
        return 0.0
    
    returns = prices.pct_change().dropna()
    if len(returns) < window:
        return 0.0
    
    std = returns.iloc[-window:].std()
    return std * np.sqrt(252)  # 年化


def calculate_atr(
    high: pd.Series, 
    low: pd.Series, 
    close: pd.Series, 
    window: int = 14
) -> pd.Series:
    """
    计算 ATR (Average True Range)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        window: ATR 周期
    
    Returns:
        ATR 序列
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=window).mean()


def calculate_atr_percent(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14
) -> float:
    """
    计算 ATR 百分比（ATR / 当前价格）
    
    Returns:
        ATR 百分比
    """
    atr = calculate_atr(high, low, close, window)
    if len(atr) == 0 or close.iloc[-1] == 0:
        return 0.0
    return atr.iloc[-1] / close.iloc[-1]


# ==================== RSI ====================

def calculate_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    """
    计算 RSI (Relative Strength Index)
    
    Args:
        prices: 价格序列
        window: RSI 周期
    
    Returns:
        RSI 序列 (0-100)
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    
    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


# ==================== MACD ====================

def calculate_macd(
    prices: pd.Series, 
    fast: int = 12, 
    slow: int = 26, 
    signal: int = 9
) -> Dict[str, pd.Series]:
    """
    计算 MACD
    
    Args:
        prices: 价格序列
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期
    
    Returns:
        包含 macd, signal, histogram 的字典
    """
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    
    return {
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }


# ==================== 综合分析函数 ====================

@dataclass
class TechnicalAnalysisResult:
    """技术分析结果"""
    # 价格位置
    price: float
    sma20: float
    sma50: float
    sma200: Optional[float]
    
    # 趋势
    sma20_slope: float
    trend_persistence: float
    ma_alignment: str
    
    # 动量
    return_5d: float
    return_20d: float
    return_63d: float
    rsi: float
    
    # 成交量
    volume_ratio: float
    obv_trend: str
    
    # 波动
    max_drawdown_20d: float
    current_drawdown: float
    
    # 52周数据
    distance_from_52w_high: Optional[float] = None


def analyze_technical(
    df: pd.DataFrame,
    symbol: str = None
) -> Optional[TechnicalAnalysisResult]:
    """
    综合技术分析
    
    Args:
        df: OHLCV DataFrame (columns: date, open, high, low, close, volume)
        symbol: 股票代码（用于日志）
    
    Returns:
        TechnicalAnalysisResult 或 None
    """
    if df is None or len(df) < 50:
        logger.warning(f"数据不足，无法进行技术分析")
        return None
    
    try:
        prices = df['close']
        volumes = df['volume']
        
        # 计算均线
        sma20 = calculate_sma(prices, 20)
        sma50 = calculate_sma(prices, 50)
        sma200 = calculate_sma(prices, 200) if len(prices) >= 200 else None
        
        current_price = prices.iloc[-1]
        current_sma20 = sma20.iloc[-1]
        current_sma50 = sma50.iloc[-1]
        current_sma200 = sma200.iloc[-1] if sma200 is not None else None
        
        # 均线排列
        alignment = check_ma_alignment(
            current_price, current_sma20, current_sma50, current_sma200
        )
        
        # OBV
        obv = calculate_obv(prices, volumes)
        obv_trend = calculate_obv_trend(obv)
        
        # RSI
        rsi = calculate_rsi(prices)
        
        # 构建结果
        result = TechnicalAnalysisResult(
            price=current_price,
            sma20=current_sma20,
            sma50=current_sma50,
            sma200=current_sma200,
            sma20_slope=calculate_sma_slope(sma20, 5),
            trend_persistence=calculate_trend_persistence(prices, sma20, 20),
            ma_alignment=alignment['alignment'],
            return_5d=calculate_returns(prices, 5),
            return_20d=calculate_returns(prices, 20),
            return_63d=calculate_returns(prices, 63) if len(prices) >= 64 else 0.0,
            rsi=rsi.iloc[-1] if len(rsi) > 0 else 50.0,
            volume_ratio=calculate_relative_volume(volumes),
            obv_trend=obv_trend,
            max_drawdown_20d=calculate_max_drawdown(prices, 20),
            current_drawdown=calculate_current_drawdown(prices, 252),
        )
        
        # 52周高点距离
        if len(df) >= 252:
            high_52w = df['high'].iloc[-252:].max()
            result.distance_from_52w_high = calculate_distance_from_52w_high(
                current_price, high_52w
            )
        
        return result
        
    except Exception as e:
        logger.error(f"技术分析失败: {e}")
        return None


def get_technical_summary(df: pd.DataFrame) -> Dict:
    """
    获取技术分析摘要（字典格式，便于 JSON 序列化）
    
    Args:
        df: OHLCV DataFrame
    
    Returns:
        技术分析摘要字典
    """
    result = analyze_technical(df)
    if result is None:
        return {}
    
    return {
        'price': result.price,
        'sma20': result.sma20,
        'sma50': result.sma50,
        'sma200': result.sma200,
        'sma20_slope': result.sma20_slope,
        'trend_persistence': result.trend_persistence,
        'ma_alignment': result.ma_alignment,
        'returns': {
            '5d': result.return_5d,
            '20d': result.return_20d,
            '63d': result.return_63d,
        },
        'rsi': result.rsi,
        'volume_ratio': result.volume_ratio,
        'obv_trend': result.obv_trend,
        'drawdown': {
            'max_20d': result.max_drawdown_20d,
            'current': result.current_drawdown,
        },
        'distance_from_52w_high': result.distance_from_52w_high,
    }