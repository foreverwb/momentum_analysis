"""
ETF 综合评分计算器
整合多数据源计算 ETF 综合评分

评分体系:
- 相对动量 (RelMom): 45%
- 趋势质量: 25%
- 广度/参与度: 20%
- 期权确认: 10%

硬性门槛:
- Price > SMA50
- RS_20D > 0
- Breadth > 50%

数据源:
- IBKR: 价格数据、RelMom
- Futu: IV 数据
- Finviz: 广度指标
- MarketChameleon: HeatScore
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    """单项评分结果"""
    score: float
    data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict:
        return {
            'score': self.score,
            'data': self.data
        }


@dataclass
class ThresholdResult:
    """门槛检查结果"""
    all_pass: bool
    details: Dict[str, str]
    
    def to_dict(self) -> Dict:
        return {
            'all_pass': self.all_pass,
            'details': self.details
        }


@dataclass
class ETFScoreResult:
    """ETF 综合评分结果"""
    symbol: str
    total_score: float
    thresholds_pass: bool
    thresholds: Dict[str, str]
    breakdown: Dict[str, Any]
    weights: Dict[str, float]
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ETFScoreCalculator:
    """
    ETF 综合评分计算器
    
    整合多数据源计算 ETF 综合评分:
    1. 相对动量 (45%) - IBKR
    2. 趋势质量 (25%) - IBKR + 本地计算
    3. 广度/参与度 (20%) - Finviz
    4. 期权确认 (10%) - Futu + MarketChameleon
    
    使用示例:
    ```python
    ibkr = IBKRConnector()
    ibkr.connect()
    
    calc = ETFScoreCalculator(ibkr)
    result = calc.calculate_composite_score('XLK', 'SPY')
    
    print(f"总分: {result['total_score']}")
    print(f"门槛通过: {result['thresholds_pass']}")
    
    ibkr.disconnect()
    ```
    """
    
    # 权重配置
    WEIGHTS = {
        'rel_mom': 0.45,        # 相对动量
        'trend_quality': 0.25,  # 趋势质量
        'breadth': 0.20,        # 广度/参与度
        'options_confirm': 0.10 # 期权确认
    }
    
    # 硬性门槛配置
    THRESHOLDS = {
        'price_above_sma50': True,
        'rs_20d_positive': True,
        'breadth_min': 0.50
    }
    
    def __init__(self, ibkr, futu=None):
        """
        初始化 ETF 评分计算器
        
        Args:
            ibkr: IBKRConnector 实例
            futu: FutuConnector 实例（可选）
        """
        self.ibkr = ibkr
        self.futu = futu
    
    def calculate_rel_mom_score(self, symbol: str, benchmark: str = 'SPY') -> Dict:
        """
        计算相对动量分数 (权重: 45%)
        
        数据源: IBKR
        
        评分逻辑:
        - RelMom 值范围映射 [-0.1, 0.15] -> [0, 100]
        - RelMom > 0.05: 强势
        - RelMom > 0: 中性偏强
        - RelMom < 0: 弱势
        
        Args:
            symbol: ETF 代码
            benchmark: 基准指数 (默认 SPY)
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        try:
            result = self.ibkr.analyze_sector_vs_spy(symbol, benchmark)
            
            if not result:
                logger.warning(f"无法获取 {symbol} 的 RelMom 数据")
                return {'score': 0, 'data': None}
            
            # RelMom 值转换为 0-100 分数
            # 假设 RelMom 范围 [-0.1, 0.15] 映射到 [0, 100]
            rel_mom = result.get('RelMom', 0) or 0
            
            # 线性映射: -0.1 -> 0, 0.15 -> 100
            score = (rel_mom + 0.1) / 0.25 * 100
            score = min(100, max(0, score))
            
            return {
                'score': round(score, 2),
                'data': {
                    'RS': result.get('RS'),
                    'RS_5D': result.get('RS_5D'),
                    'RS_20D': result.get('RS_20D'),
                    'RS_63D': result.get('RS_63D'),
                    'RelMom': result.get('RelMom'),
                    'strength': result.get('strength', 'NEUTRAL'),
                    'description': result.get('description', '')
                }
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} RelMom 分数失败: {e}")
            return {'score': 0, 'data': None}
    
    def calculate_trend_quality_score(self, symbol: str) -> Dict:
        """
        计算趋势质量分数 (权重: 25%)
        
        数据源: IBKR + 本地计算
        
        评分项 (每项25分):
        1. Price > SMA50 (+25分)
        2. SMA20 > SMA50 (+25分)
        3. SMA20 Slope > 0 (+25分)
        4. Max Drawdown 20D > -10% (+25分)
        
        Args:
            symbol: ETF 代码
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        from .technical import calculate_sma, calculate_sma_slope, calculate_max_drawdown
        
        try:
            # 获取价格数据 (需要100天来计算50日均线)
            price_df = self.ibkr.get_price_data(symbol, duration='100 D')
            
            if price_df is None or len(price_df) < 50:
                logger.warning(f"数据不足，无法计算 {symbol} 趋势质量")
                return {'score': 0, 'data': None}
            
            prices = price_df[symbol]
            
            # 计算均线
            sma20 = calculate_sma(prices, 20)
            sma50 = calculate_sma(prices, 50)
            
            current_price = prices.iloc[-1]
            current_sma20 = sma20.iloc[-1]
            current_sma50 = sma50.iloc[-1]
            
            # 评分项
            price_above_sma50 = current_price > current_sma50
            sma20_above_sma50 = current_sma20 > current_sma50
            sma20_slope = calculate_sma_slope(sma20, period=5)
            max_dd = calculate_max_drawdown(prices, 20)
            
            # 计算分数 (每项25分)
            score = 0
            score_breakdown = {}
            
            if price_above_sma50:
                score += 25
                score_breakdown['price_above_sma50'] = 25
            else:
                score_breakdown['price_above_sma50'] = 0
            
            if sma20_above_sma50:
                score += 25
                score_breakdown['sma20_above_sma50'] = 25
            else:
                score_breakdown['sma20_above_sma50'] = 0
            
            if sma20_slope > 0:
                score += 25
                score_breakdown['sma20_slope_positive'] = 25
            else:
                score_breakdown['sma20_slope_positive'] = 0
            
            if max_dd > -0.10:  # 回撤大于 -10%（即回撤不超过10%）
                score += 25
                score_breakdown['drawdown_acceptable'] = 25
            else:
                score_breakdown['drawdown_acceptable'] = 0
            
            return {
                'score': score,
                'data': {
                    'price': round(current_price, 2),
                    'sma20': round(current_sma20, 2),
                    'sma50': round(current_sma50, 2),
                    'price_above_sma50': price_above_sma50,
                    'sma20_above_sma50': sma20_above_sma50,
                    'sma20_slope': round(sma20_slope, 4),
                    'max_drawdown_20d': round(max_dd, 4),
                    'score_breakdown': score_breakdown
                }
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} 趋势质量分数失败: {e}")
            return {'score': 0, 'data': None}
    
    def calculate_breadth_score(
        self, 
        etf_symbol: str, 
        holdings_data: List[Dict] = None
    ) -> Dict:
        """
        计算广度/参与度分数 (权重: 20%)
        
        数据源: Finviz 导入数据
        
        评分逻辑:
        - 基于 %Above50DMA 计算分数
        - 80%+ 以上 = 100分
        - 50% = 50分
        - 线性映射
        
        Args:
            etf_symbol: ETF 代码
            holdings_data: ETF 持仓的 Finviz 数据列表
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        if not holdings_data:
            logger.warning(f"无 Finviz 数据，跳过 {etf_symbol} 广度计算")
            return {'score': 0, 'data': None}
        
        try:
            from ..parsers.finviz_parser import calculate_breadth_metrics
            
            breadth = calculate_breadth_metrics(holdings_data)
            
            # 基于 %Above50DMA 计算分数
            pct_above_50 = breadth.get('pct_above_sma50', 0)
            
            # 线性映射：0% -> 0分, 100% -> 100分
            score = min(100, pct_above_50 * 100)
            
            return {
                'score': round(score, 2),
                'data': {
                    'pct_above_sma20': round(breadth.get('pct_above_sma20', 0), 4),
                    'pct_above_sma50': round(breadth.get('pct_above_sma50', 0), 4),
                    'pct_above_sma200': round(breadth.get('pct_above_sma200', 0), 4),
                    'pct_near_52w_high': round(breadth.get('pct_near_52w_high', 0), 4),
                    'pct_near_52w_low': round(breadth.get('pct_near_52w_low', 0), 4),
                    'total_count': breadth.get('total_count', 0)
                }
            }
            
        except Exception as e:
            logger.error(f"计算 {etf_symbol} 广度分数失败: {e}")
            return {'score': 0, 'data': None}
    
    def calculate_options_confirm_score(
        self, 
        symbol: str, 
        mc_data: Dict = None
    ) -> Dict:
        """
        计算期权确认分数 (权重: 10%)
        
        数据源: 富途 IV + MarketChameleon HeatScore
        
        评分逻辑:
        - HeatScore > 70 且 RiskScore < 80: 高分 (80+)
        - HeatScore > 50: 中等分 (50-80)
        - HeatScore < 50: 低分
        
        Args:
            symbol: ETF 代码
            mc_data: MarketChameleon 导入数据
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        score_components = {}
        
        try:
            # 1. 从富途获取 IV 数据
            if self.futu and self.futu.is_connected():
                try:
                    iv_result = self.futu.fetch_iv_terms([symbol])
                    if symbol in iv_result:
                        iv_data = iv_result[symbol]
                        score_components['iv30'] = iv_data.iv30
                        score_components['iv60'] = iv_data.iv60
                        score_components['iv90'] = iv_data.iv90
                        score_components['total_oi'] = iv_data.total_oi
                except Exception as e:
                    logger.warning(f"获取 {symbol} IV 数据失败: {e}")
            
            # 2. 从 MarketChameleon 导入数据获取 HeatScore
            if mc_data:
                score_components['heat_score'] = mc_data.get('heat_score', 50)
                score_components['risk_score'] = mc_data.get('risk_score', 50)
                score_components['ivr'] = mc_data.get('ivr', 50)
                score_components['heat_type'] = mc_data.get('heat_type', 'NORMAL')
            
            # 综合计算
            heat = score_components.get('heat_score', 50)
            risk = score_components.get('risk_score', 50)
            
            # 热度高且风险适中为佳
            if heat > 70 and risk < 80:
                # 高热度 + 适中风险 = 高分
                score = 80 + min(20, (heat - 70) * 0.5)
            elif heat > 50:
                # 中等热度
                score = 50 + (heat - 50) * 0.5
            else:
                # 低热度
                score = heat * 0.5
            
            return {
                'score': min(100, round(score, 2)),
                'data': score_components
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} 期权确认分数失败: {e}")
            return {'score': 50, 'data': None}  # 默认中性分数
    
    def check_thresholds(
        self, 
        rel_mom_data: Dict, 
        trend_data: Dict, 
        breadth_data: Dict
    ) -> Dict:
        """
        检查硬性门槛
        
        门槛:
        1. Price > SMA50 (必须)
        2. RS_20D > 0 (必须)
        3. Breadth > 50% (必须)
        
        Args:
            rel_mom_data: RelMom 评分结果
            trend_data: 趋势质量评分结果
            breadth_data: 广度评分结果
        
        Returns:
            dict: {'all_pass': bool, 'details': dict}
        """
        results = {}
        all_pass = True
        
        # 1. Price > SMA50
        if trend_data and trend_data.get('data'):
            price_above_sma50 = trend_data['data'].get('price_above_sma50', False)
            results['price_above_sma50'] = 'PASS' if price_above_sma50 else 'FAIL'
            if not price_above_sma50:
                all_pass = False
        else:
            results['price_above_sma50'] = 'NO_DATA'
            all_pass = False
        
        # 2. RS_20D > 0
        if rel_mom_data and rel_mom_data.get('data'):
            rs_20d = rel_mom_data['data'].get('RS_20D', 0) or 0
            results['rs_20d_positive'] = 'PASS' if rs_20d > 0 else 'FAIL'
            if rs_20d <= 0:
                all_pass = False
        else:
            results['rs_20d_positive'] = 'NO_DATA'
            all_pass = False
        
        # 3. Breadth > 50%
        if breadth_data and breadth_data.get('data'):
            pct_above_50 = breadth_data['data'].get('pct_above_sma50', 0)
            results['breadth_above_50'] = 'PASS' if pct_above_50 >= 0.5 else 'FAIL'
            if pct_above_50 < 0.5:
                all_pass = False
        else:
            # 如果没有广度数据，不强制失败
            results['breadth_above_50'] = 'NO_DATA'
        
        return {
            'all_pass': all_pass,
            'details': results
        }
    
    def calculate_composite_score(
        self,
        symbol: str,
        benchmark: str = 'SPY',
        holdings_data: List[Dict] = None,
        mc_data: Dict = None
    ) -> Dict:
        """
        计算 ETF 综合评分
        
        整合所有评分模块，返回完整评分结果
        
        Args:
            symbol: ETF 代码
            benchmark: 基准指数 (默认 SPY)
            holdings_data: ETF 持仓的 Finviz 数据
            mc_data: MarketChameleon 期权数据
        
        Returns:
            dict: 完整评分结果
            {
                'symbol': str,
                'total_score': float,
                'thresholds_pass': bool,
                'thresholds': dict,
                'breakdown': dict,
                'weights': dict
            }
        """
        logger.info(f"开始计算 {symbol} 综合评分...")
        
        # 1. 计算各模块分数
        rel_mom = self.calculate_rel_mom_score(symbol, benchmark)
        trend = self.calculate_trend_quality_score(symbol)
        breadth = self.calculate_breadth_score(symbol, holdings_data)
        options = self.calculate_options_confirm_score(symbol, mc_data)
        
        # 2. 检查硬性门槛
        thresholds = self.check_thresholds(rel_mom, trend, breadth)
        
        # 3. 计算综合分
        total_score = (
            self.WEIGHTS['rel_mom'] * rel_mom['score'] +
            self.WEIGHTS['trend_quality'] * trend['score'] +
            self.WEIGHTS['breadth'] * breadth['score'] +
            self.WEIGHTS['options_confirm'] * options['score']
        )
        
        result = {
            'symbol': symbol,
            'total_score': round(total_score, 2),
            'thresholds_pass': thresholds['all_pass'],
            'thresholds': thresholds['details'],
            'breakdown': {
                'rel_mom': rel_mom,
                'trend_quality': trend,
                'breadth': breadth,
                'options_confirm': options
            },
            'weights': self.WEIGHTS
        }
        
        logger.info(
            f"✅ {symbol} 综合评分: {total_score:.2f}, "
            f"门槛通过: {thresholds['all_pass']}"
        )
        
        return result
    
    def batch_calculate_scores(
        self,
        symbols: List[str],
        benchmark: str = 'SPY',
        holdings_map: Dict[str, List[Dict]] = None,
        mc_map: Dict[str, Dict] = None
    ) -> List[Dict]:
        """
        批量计算多个 ETF 的综合评分
        
        Args:
            symbols: ETF 代码列表
            benchmark: 基准指数
            holdings_map: {symbol: [holdings_data]} 映射
            mc_map: {symbol: mc_data} 映射
        
        Returns:
            List[dict]: 评分结果列表，按总分降序排列
        """
        holdings_map = holdings_map or {}
        mc_map = mc_map or {}
        
        results = []
        
        for symbol in symbols:
            try:
                result = self.calculate_composite_score(
                    symbol=symbol,
                    benchmark=benchmark,
                    holdings_data=holdings_map.get(symbol),
                    mc_data=mc_map.get(symbol)
                )
                results.append(result)
            except Exception as e:
                logger.error(f"计算 {symbol} 评分失败: {e}")
                continue
        
        # 按总分降序排列
        results.sort(key=lambda x: x['total_score'], reverse=True)
        
        return results
    
    def get_top_etfs(
        self,
        symbols: List[str],
        top_n: int = 5,
        must_pass_thresholds: bool = True
    ) -> List[Dict]:
        """
        获取评分最高的 Top N ETF
        
        Args:
            symbols: ETF 代码列表
            top_n: 返回数量
            must_pass_thresholds: 是否必须通过门槛
        
        Returns:
            List[dict]: Top N ETF 评分结果
        """
        all_results = self.batch_calculate_scores(symbols)
        
        if must_pass_thresholds:
            # 只保留通过门槛的
            filtered = [r for r in all_results if r['thresholds_pass']]
        else:
            filtered = all_results
        
        return filtered[:top_n]


# 便捷函数
def create_etf_calculator(ibkr, futu=None) -> ETFScoreCalculator:
    """
    创建 ETF 评分计算器的工厂函数
    
    Args:
        ibkr: IBKRConnector 实例
        futu: FutuConnector 实例（可选）
    
    Returns:
        ETFScoreCalculator 实例
    """
    return ETFScoreCalculator(ibkr=ibkr, futu=futu)


# 板块 ETF 列表
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

# 行业 ETF 列表
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
