"""
Regime Gate 计算器
市场环境判断：RISK_ON / NEUTRAL / RISK_OFF

市场环境决定仓位火力:
- A档 (RISK_ON): 满火力，可积极做多
- B档 (NEUTRAL): 半火力，谨慎做多
- C档 (RISK_OFF): 低火力/空仓，防守为主

更新后的判断依据:
- SPY 收盘价相对 20DMA / 50DMA
- SMA20 斜率 或 20日收益率
- (可选) 市场广度
- VIX 仅用于参考展示，不参与档位切换

数据源: IBKR
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
import math
import logging

logger = logging.getLogger(__name__)


@dataclass
class RegimeData:
    """市场环境数据"""
    spy_price: float
    sma20: float
    sma50: float
    dist_to_sma20: Optional[float]
    dist_to_sma50: Optional[float]
    sma20_slope: float
    return_20d: float
    vix: Optional[float]
    price_above_sma20: bool
    price_above_sma50: bool
    sma20_above_sma50: bool
    near_sma50: bool
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RegimeResult:
    """市场环境判断结果"""
    status: str  # A, B, C
    regime: str  # RISK_ON, NEUTRAL, RISK_OFF
    fire_power: str  # 满火力, 半火力, 低火力/空仓
    data: Optional[RegimeData] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        result = {
            'status': self.status,
            'regime': self.regime,
            'fire_power': self.fire_power,
        }
        if self.data:
            result['data'] = self.data.to_dict()
        if self.error:
            result['error'] = self.error
        return result


class RegimeGateCalculator:
    """
    市场环境判断计算器 (Regime Gate)
    
    市场环境分为三档:
    
    A档 - RISK_ON (满火力):
    - SPY > 50DMA
    - SMA20 斜率 > 0 或 20日收益率为正
    - （可选）市场广度不差
    - 且与 50DMA 距离超过 2%
    
    B档 - NEUTRAL (半火力):
    - 价格贴近 50DMA（|price-50DMA| < 2%）或趋势方向不明
    
    C档 - RISK_OFF (低火力/空仓):
    - SPY < 50DMA 且 20日收益率为负
    - 或广度快速坍塌
    
    使用示例:
    ```python
    ibkr = IBKRConnector()
    ibkr.connect()
    
    calc = RegimeGateCalculator(ibkr)
    result = calc.calculate_regime()
    
    print(f"市场状态: {result['status']}")  # A, B, C
    print(f"环境: {result['regime']}")       # RISK_ON, NEUTRAL, RISK_OFF
    print(f"火力: {result['fire_power']}")   # 满火力, 半火力, 低火力/空仓
    
    ibkr.disconnect()
    ```
    """
    
    # Regime 阈值配置
    THRESHOLDS = {
        'vix_low': 15,      # VIX 低于此值为低波动
        'vix_high': 25,     # VIX 高于此值为高波动
        'return_20d_bad': 0.0,  # 20日收益率低于此值为负
    }
    
    def __init__(self, ibkr):
        """
        初始化 Regime Gate 计算器
        
        Args:
            ibkr: IBKRConnector 实例
        """
        self.ibkr = ibkr

    @staticmethod
    def _safe_number(value: Optional[float], default=None):
        """Return a JSON-safe number; strip NaN/inf to default."""
        try:
            if value is None:
                return default
            # bool is subclass of int; keep as-is
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                if math.isnan(value) or math.isinf(value):
                    return default
            return value
        except Exception:
            return default
    
    def calculate_regime(self) -> Dict:
        """
        计算当前市场环境
        
        Returns:
            dict: {
                'status': str,       # A, B, C
                'regime': str,       # RISK_ON, NEUTRAL, RISK_OFF
                'fire_power': str,   # 满火力, 半火力, 低火力/空仓
                'data': dict,        # 详细数据
                'error': str         # 错误信息（如有）
            }
        """
        from .technical import calculate_sma, calculate_sma_slope, calculate_returns
        
        logger.info("开始计算市场环境 (Regime Gate)...")
        
        try:
            # 获取 SPY 数据（约 120 天足够覆盖 50DMA 与斜率）
            spy_df = self.ibkr.get_price_data('SPY', duration='120 D')
            
            if spy_df is None or len(spy_df) < 60:
                logger.error("无法获取足够的 SPY 数据")
                return {
                    'status': 'UNKNOWN',
                    'regime': 'UNKNOWN',
                    'fire_power': '未知',
                    'data': None,
                    'error': 'Failed to get SPY data'
                }
            
            prices = spy_df['SPY']
            
            # 计算均线
            sma20 = calculate_sma(prices, 20)
            sma50 = calculate_sma(prices, 50)
            
            current_price = prices.iloc[-1]
            current_sma20 = sma20.iloc[-1]
            current_sma50 = sma50.iloc[-1]
            
            # 与均线的距离
            dist_to_sma20 = (current_price - current_sma20) / current_sma20 if current_sma20 else math.nan
            dist_to_sma50 = (current_price - current_sma50) / current_sma50 if current_sma50 else math.nan
            
            # 计算斜率和收益率
            sma20_slope = calculate_sma_slope(sma20, period=5)
            return_20d = calculate_returns(prices, 20)
            
            # 获取 VIX
            vix = self.ibkr.get_vix()

            # JSON 安全的数值（去除 NaN/Inf）
            safe_price = self._safe_number(float(current_price))
            safe_sma20 = self._safe_number(float(current_sma20))
            safe_sma50 = self._safe_number(float(current_sma50))
            safe_dist20 = self._safe_number(dist_to_sma20)
            safe_dist50 = self._safe_number(dist_to_sma50)
            safe_sma20_slope = self._safe_number(float(sma20_slope), 0.0)
            safe_return_20d = self._safe_number(float(return_20d), 0.0)
            safe_vix = self._safe_number(vix)

            # 构建数据对象（布尔值也需防 None 比较报错）
            near_50dma = False
            try:
                near_50dma = abs(dist_to_sma50) < 0.02
            except Exception:
                near_50dma = False

            data = RegimeData(
                spy_price=safe_price,
                sma20=safe_sma20,
                sma50=safe_sma50,
                dist_to_sma20=safe_dist20,
                dist_to_sma50=safe_dist50,
                sma20_slope=safe_sma20_slope,
                return_20d=safe_return_20d,
                vix=safe_vix,
                price_above_sma20=bool(
                    safe_price is not None and safe_sma20 is not None and safe_price > safe_sma20
                ),
                price_above_sma50=bool(
                    safe_price is not None and safe_sma50 is not None and safe_price > safe_sma50
                ),
                sma20_above_sma50=bool(
                    safe_sma20 is not None and safe_sma50 is not None and safe_sma20 > safe_sma50
                ),
                near_sma50=near_50dma
            )
            
            # ============ 判断 Regime ============
            
            # C档（Risk-Off）条件: 价格跌破50DMA且20日收益为负
            price_below_50 = safe_price is not None and safe_sma50 is not None and safe_price < safe_sma50
            slope_positive = safe_sma20_slope is not None and safe_sma20_slope > 0
            return_positive = safe_return_20d is not None and safe_return_20d > 0
            risk_off = price_below_50 and (safe_return_20d or 0) < self.THRESHOLDS['return_20d_bad']
            # A档（Risk-On）条件: 价格站上50DMA且短期趋势向上
            price_above_50 = data.price_above_sma50
            risk_on = price_above_50 and (slope_positive or return_positive)
            near_50dma = data.near_sma50  # ±2% 视为靠近

            if risk_off:
                regime = 'RISK_OFF'
                fire_power = '低火力/空仓'
                status = 'C'
            elif near_50dma:
                regime = 'NEUTRAL'
                fire_power = '半火力'
                status = 'B'
            elif risk_on:
                regime = 'RISK_ON'
                fire_power = '满火力'
                status = 'A'
            else:
                regime = 'NEUTRAL'
                fire_power = '半火力'
                status = 'B'
            
            logger.info(f"✅ Regime Gate: {status} ({regime}) - {fire_power}")
            
            return {
                'status': status,
                'regime': regime,
                'fire_power': fire_power,
                'data': data.to_dict()
            }
            
        except Exception as e:
            logger.error(f"计算 Regime Gate 失败: {e}")
            return {
                'status': 'UNKNOWN',
                'regime': 'UNKNOWN',
                'fire_power': '未知',
                'data': None,
                'error': str(e)
            }
    
    def get_regime_summary(self) -> Dict:
        """
        获取 Regime 摘要（用于前端显示）
        
        Returns:
            dict: 简化的 Regime 信息
            {
                'status': str,
                'regime_text': str,
                'spy': dict,
                'vix': float,
                'indicators': dict
            }
        """
        result = self.calculate_regime()
        
        if result.get('data') is None:
            return {
                'status': 'UNKNOWN',
                'regime_text': '未知',
                'spy': None,
                'vix': None,
                'indicators': None,
                'error': result.get('error')
            }
        
        data = result['data']
        
        return {
            'status': result['status'],
            'regime_text': f"{result['regime']} {result['fire_power']}",
            'spy': {
                'price': data['spy_price'],
                'sma20': data['sma20'],
                'sma50': data['sma50'],
                'dist_to_sma20': data.get('dist_to_sma20'),
                'dist_to_sma50': data.get('dist_to_sma50'),
                'return_20d': data['return_20d'],
                'sma20_slope': data['sma20_slope'],
            },
            'vix': data['vix'],
            'indicators': {
                'price_above_sma20': data['price_above_sma20'],
                'price_above_sma50': data['price_above_sma50'],
                'sma20_slope': data['sma20_slope'],
                'sma20_slope_positive': data['sma20_slope'] > 0,
                'sma20_above_sma50': data['sma20_above_sma50'],
                'return_20d': data['return_20d'],
                'dist_to_sma20': data.get('dist_to_sma20'),
                'dist_to_sma50': data.get('dist_to_sma50'),
                'near_sma50': data.get('near_sma50'),
            }
        }
    
    def get_detailed_analysis(self) -> Dict:
        """
        获取详细市场分析
        
        Returns:
            dict: 包含详细分析的结果
        """
        result = self.calculate_regime()
        
        if result.get('data') is None:
            return result
        
        data = result['data']
        
        # 添加分析和建议
        analysis = {
            'trend_analysis': self._analyze_trend(data),
            'volatility_analysis': self._analyze_volatility(data),
            'recommendations': self._get_recommendations(result['status']),
        }
        
        result['analysis'] = analysis
        return result
    
    def _analyze_trend(self, data: Dict) -> Dict:
        """分析趋势状态"""
        price = data['spy_price']
        sma50 = data['sma50']
        sma20 = data['sma20']
        sma20_slope = data['sma20_slope']
        
        # 趋势强度评估
        if data['price_above_sma50'] and data['sma20_above_sma50'] and sma20_slope > 0:
            trend_strength = 'STRONG_UPTREND'
            trend_description = '强势上升趋势，价格与短中期均线均向上'
        elif data['price_above_sma50']:
            trend_strength = 'UPTREND'
            trend_description = '上升趋势，价格在 SMA50 上方'
        elif price is not None and sma20 is not None and price > sma20:
            trend_strength = 'WEAK_UPTREND'
            trend_description = '弱上升趋势，价格在 20DMA 上方但在 50DMA 下方'
        elif price < sma50:
            trend_strength = 'DOWNTREND'
            trend_description = '下降趋势，价格在 50DMA 下方'
        else:
            trend_strength = 'SIDEWAYS'
            trend_description = '横盘整理'
        
        # 趋势方向
        if sma20_slope > 0.5:
            momentum = '加速上涨'
        elif sma20_slope > 0:
            momentum = '温和上涨'
        elif sma20_slope > -0.5:
            momentum = '温和下跌'
        else:
            momentum = '加速下跌'
        
        return {
            'strength': trend_strength,
            'description': trend_description,
            'momentum': momentum,
            'sma20_slope': data['sma20_slope']
        }
    
    def _analyze_volatility(self, data: Dict) -> Dict:
        """分析波动率状态"""
        vix = data.get('vix')
        
        if vix is None:
            return {
                'level': 'UNKNOWN',
                'description': 'VIX 数据不可用'
            }
        
        if vix < self.THRESHOLDS['vix_low']:
            return {
                'level': 'LOW',
                'vix': vix,
                'description': f'低波动率环境 (VIX={vix:.1f})'
            }
        elif vix > self.THRESHOLDS['vix_high']:
            return {
                'level': 'HIGH',
                'vix': vix,
                'description': f'高波动率环境 (VIX={vix:.1f})，注意风险'
            }
        else:
            return {
                'level': 'NORMAL',
                'vix': vix,
                'description': f'正常波动率环境 (VIX={vix:.1f})'
            }
    
    def _get_recommendations(self, status: str) -> Dict:
        """根据 Regime 给出操作建议"""
        recommendations = {
            'A': {
                'position_size': '满仓 (100%)',
                'strategy': '积极做多',
                'focus': '关注强势板块和突破个股',
                'risk_management': '可适度放宽止损',
                'actions': [
                    '寻找突破新高的强势股',
                    '加仓 RelMom 排名靠前的板块',
                    '减少现金头寸',
                    '可考虑杠杆做多'
                ]
            },
            'B': {
                'position_size': '半仓 (50%)',
                'strategy': '谨慎做多',
                'focus': '只交易最强势的板块和个股',
                'risk_management': '严格止损，控制单笔风险',
                'actions': [
                    '只做 RelMom Top 3 板块',
                    '降低单笔交易仓位',
                    '保持一定现金头寸',
                    '避免追高'
                ]
            },
            'C': {
                'position_size': '空仓或 20%',
                'strategy': '防守为主',
                'focus': '保本第一，避免亏损',
                'risk_management': '极低风险容忍度',
                'actions': [
                    '清仓或大幅减仓',
                    '增加现金头寸',
                    '可考虑对冲或做空',
                    '等待市场企稳再入场'
                ]
            }
        }
        
        return recommendations.get(status, recommendations['B'])
    
    def check_regime_change(self, previous_status: str) -> Dict:
        """
        检查 Regime 是否发生变化
        
        Args:
            previous_status: 之前的状态 ('A', 'B', 'C')
        
        Returns:
            dict: {
                'changed': bool,
                'previous': str,
                'current': str,
                'direction': str,  # 'upgrade', 'downgrade', 'unchanged'
                'alert': str
            }
        """
        current = self.calculate_regime()
        current_status = current['status']
        
        if current_status == previous_status:
            return {
                'changed': False,
                'previous': previous_status,
                'current': current_status,
                'direction': 'unchanged',
                'alert': None
            }
        
        # 判断变化方向
        status_rank = {'A': 3, 'B': 2, 'C': 1}
        prev_rank = status_rank.get(previous_status, 2)
        curr_rank = status_rank.get(current_status, 2)
        
        if curr_rank > prev_rank:
            direction = 'upgrade'
            alert = f"🟢 市场环境改善: {previous_status} → {current_status}"
        else:
            direction = 'downgrade'
            alert = f"🔴 市场环境恶化: {previous_status} → {current_status}"
        
        return {
            'changed': True,
            'previous': previous_status,
            'current': current_status,
            'direction': direction,
            'alert': alert,
            'details': current
        }


# 便捷函数
def create_regime_calculator(ibkr) -> RegimeGateCalculator:
    """
    创建 Regime Gate 计算器的工厂函数
    
    Args:
        ibkr: IBKRConnector 实例
    
    Returns:
        RegimeGateCalculator 实例
    """
    return RegimeGateCalculator(ibkr=ibkr)


def get_quick_regime(ibkr) -> str:
    """
    快速获取当前 Regime 状态
    
    Args:
        ibkr: IBKRConnector 实例
    
    Returns:
        str: 'A', 'B', 'C', or 'UNKNOWN'
    """
    calc = RegimeGateCalculator(ibkr)
    result = calc.calculate_regime()
    return result['status']
