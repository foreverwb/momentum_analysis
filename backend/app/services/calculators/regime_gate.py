"""
Regime Gate 计算器
市场环境判断：RISK_ON / NEUTRAL / RISK_OFF

市场环境决定仓位火力:
- A档 (RISK_ON): 满火力，可积极做多
- B档 (NEUTRAL): 半火力，谨慎做多
- C档 (RISK_OFF): 低火力/空仓，防守为主

判断依据:
- SPY 价格与均线关系
- SMA20 斜率
- 20日收益率
- VIX 水平

数据源: IBKR
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class RegimeData:
    """市场环境数据"""
    spy_price: float
    sma20: float
    sma50: float
    sma200: float
    vs_200ma: str
    sma20_slope: float
    return_20d: float
    vix: Optional[float]
    price_above_sma50: bool
    price_above_sma200: bool
    sma20_above_sma50: bool
    sma50_above_sma200: bool
    
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
    - SPY > SMA50
    - SMA20 斜率 > 0
    - SMA20 > SMA50
    条件：全部满足
    
    B档 - NEUTRAL (半火力):
    - 不满足 A档 条件
    - 不满足 C档 条件
    条件：A、C 都不满足
    
    C档 - RISK_OFF (低火力/空仓):
    - SPY < SMA50
    - 20日收益率 < -5%
    条件：全部满足
    
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
        'return_20d_bad': -0.05,  # 20日收益率低于此值为差
    }
    
    def __init__(self, ibkr):
        """
        初始化 Regime Gate 计算器
        
        Args:
            ibkr: IBKRConnector 实例
        """
        self.ibkr = ibkr
    
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
            # 获取 SPY 数据 (需要 250 天来计算 200日均线)
            spy_df = self.ibkr.get_price_data('SPY', duration='250 D')
            
            if spy_df is None or len(spy_df) < 200:
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
            sma200 = calculate_sma(prices, 200)
            
            current_price = prices.iloc[-1]
            current_sma20 = sma20.iloc[-1]
            current_sma50 = sma50.iloc[-1]
            current_sma200 = sma200.iloc[-1]
            
            # 计算斜率和收益率
            sma20_slope = calculate_sma_slope(sma20, period=5)
            return_20d = calculate_returns(prices, 20)
            
            # 获取 VIX
            vix = self.ibkr.get_vix()
            
            # 计算相对 200MA 的位置
            vs_200ma = ((current_price / current_sma200) - 1) * 100
            vs_200ma_str = f"{vs_200ma:+.1f}%"
            
            # 构建数据对象
            data = RegimeData(
                spy_price=round(current_price, 2),
                sma20=round(current_sma20, 2),
                sma50=round(current_sma50, 2),
                sma200=round(current_sma200, 2),
                vs_200ma=vs_200ma_str,
                sma20_slope=round(sma20_slope, 4),
                return_20d=round(return_20d, 4),
                vix=vix,
                price_above_sma50=current_price > current_sma50,
                price_above_sma200=current_price > current_sma200,
                sma20_above_sma50=current_sma20 > current_sma50,
                sma50_above_sma200=current_sma50 > current_sma200
            )
            
            # ============ 判断 Regime ============
            
            # A档（Risk-On）条件: 全部满足
            risk_on_conditions = [
                current_price > current_sma50,      # SPY > SMA50
                sma20_slope > 0,                     # SMA20 斜率 > 0
                current_sma20 > current_sma50       # SMA20 > SMA50
            ]
            
            # C档（Risk-Off）条件: 全部满足
            risk_off_conditions = [
                current_price < current_sma50,      # SPY < SMA50
                return_20d < self.THRESHOLDS['return_20d_bad']  # 20日收益 < -5%
            ]
            
            # 判断
            if all(risk_on_conditions):
                regime = 'RISK_ON'
                fire_power = '满火力'
                status = 'A'
            elif all(risk_off_conditions):
                regime = 'RISK_OFF'
                fire_power = '低火力/空仓'
                status = 'C'
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
                'vs200ma': data['vs_200ma'],
                'trend': 'up' if data['price_above_sma200'] else 'down'
            },
            'vix': data['vix'],
            'indicators': {
                'price_above_sma50': data['price_above_sma50'],
                'price_above_sma200': data['price_above_sma200'],
                'sma20_slope_positive': data['sma20_slope'] > 0,
                'sma20_above_sma50': data['sma20_above_sma50'],
                'return_20d': data['return_20d']
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
        sma200 = data['sma200']
        sma20_slope = data['sma20_slope']
        
        # 趋势强度评估
        if data['price_above_sma200'] and data['sma50_above_sma200']:
            trend_strength = 'STRONG_UPTREND'
            trend_description = '强势上升趋势，均线多头排列'
        elif data['price_above_sma50']:
            trend_strength = 'UPTREND'
            trend_description = '上升趋势，价格在 SMA50 上方'
        elif data['price_above_sma200']:
            trend_strength = 'WEAK_UPTREND'
            trend_description = '弱上升趋势，价格在 SMA200 上方但在 SMA50 下方'
        elif price < sma200:
            trend_strength = 'DOWNTREND'
            trend_description = '下降趋势，价格在 SMA200 下方'
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
