"""
个股评分计算器
针对 ETF 持仓个股的多维度评分系统

评分维度:
- 技术评分 (Technical): 40%
- 动量评分 (Momentum): 30%
- 成交量评分 (Volume): 20%
- 期权评分 (Options): 10%

硬性门槛:
- Price > SMA50
- RS > 0 (相对板块ETF)

数据源:
- IBKR: 价格、技术指标
- Finviz: 基础技术数据
- MarketChameleon: 期权数据
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class StockScoreResult:
    """个股评分结果"""
    symbol: str
    total_score: float
    thresholds_pass: bool
    thresholds: Dict[str, str]
    breakdown: Dict[str, Any]
    weights: Dict[str, float]
    rank: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class StockScoreCalculator:
    """
    个股综合评分计算器
    
    评分体系:
    1. 技术评分 (40%) - 均线、RSI、趋势
    2. 动量评分 (30%) - 多周期收益率、RS
    3. 成交量评分 (20%) - 相对成交量、OBV
    4. 期权评分 (10%) - HeatScore、IV
    
    使用示例:
    ```python
    ibkr = IBKRConnector()
    ibkr.connect()
    
    calc = StockScoreCalculator(ibkr)
    
    # 单个股票评分
    result = calc.calculate_composite_score('AAPL', sector_etf='XLK')
    
    # 批量评分（带Finviz数据）
    finviz_data = [{'symbol': 'AAPL', ...}, {'symbol': 'MSFT', ...}]
    results = calc.batch_calculate_scores(['AAPL', 'MSFT'], finviz_data=finviz_data)
    
    ibkr.disconnect()
    ```
    """
    
    # 权重配置
    WEIGHTS = {
        'technical': 0.40,   # 技术评分
        'momentum': 0.30,    # 动量评分
        'volume': 0.20,      # 成交量评分
        'options': 0.10      # 期权评分
    }
    
    # 硬性门槛
    THRESHOLDS = {
        'price_above_sma50': True,
        'rs_positive': True
    }
    
    def __init__(self, ibkr, futu=None):
        """
        初始化个股评分计算器
        
        Args:
            ibkr: IBKRConnector 实例
            futu: FutuConnector 实例（可选）
        """
        self.ibkr = ibkr
        self.futu = futu
    
    def calculate_technical_score(
        self, 
        symbol: str, 
        finviz_data: Dict = None
    ) -> Dict:
        """
        计算技术评分 (权重: 40%)
        
        评分项 (各20分，满分100):
        1. Price > SMA50 (+20)
        2. Price > SMA200 (+20)
        3. SMA20 > SMA50 (+20)
        4. RSI 40-70 区间 (+20)
        5. 距离52周高点 < 15% (+20)
        
        Args:
            symbol: 股票代码
            finviz_data: Finviz 解析后的数据（可选）
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        from .technical import (
            calculate_sma, 
            calculate_rsi,
            calculate_distance_from_52w_high
        )
        
        try:
            # 优先使用 Finviz 数据（如果有）
            if finviz_data:
                return self._calculate_technical_from_finviz(finviz_data)
            
            # 否则从 IBKR 获取
            ohlcv = self.ibkr.get_ohlcv_data(symbol, '1 Y')
            
            if ohlcv is None or len(ohlcv) < 50:
                logger.warning(f"数据不足，无法计算 {symbol} 技术评分")
                return {'score': 0, 'data': None}
            
            prices = ohlcv['close']
            
            # 计算技术指标
            sma20 = calculate_sma(prices, 20)
            sma50 = calculate_sma(prices, 50)
            sma200 = calculate_sma(prices, 200) if len(prices) >= 200 else None
            rsi = calculate_rsi(prices, 14)
            
            current_price = prices.iloc[-1]
            current_sma20 = sma20.iloc[-1]
            current_sma50 = sma50.iloc[-1]
            current_sma200 = sma200.iloc[-1] if sma200 is not None else None
            current_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
            
            # 52周高点
            high_52w = ohlcv['high'].iloc[-252:].max() if len(ohlcv) >= 252 else ohlcv['high'].max()
            dist_from_high = calculate_distance_from_52w_high(current_price, high_52w)
            
            # 计算分数
            score = 0
            score_breakdown = {}
            
            # 1. Price > SMA50
            price_above_sma50 = current_price > current_sma50
            if price_above_sma50:
                score += 20
                score_breakdown['price_above_sma50'] = 20
            else:
                score_breakdown['price_above_sma50'] = 0
            
            # 2. Price > SMA200
            if current_sma200 is not None:
                price_above_sma200 = current_price > current_sma200
                if price_above_sma200:
                    score += 20
                    score_breakdown['price_above_sma200'] = 20
                else:
                    score_breakdown['price_above_sma200'] = 0
            else:
                score_breakdown['price_above_sma200'] = 10  # 数据不足，给半分
                score += 10
            
            # 3. SMA20 > SMA50
            sma20_above_sma50 = current_sma20 > current_sma50
            if sma20_above_sma50:
                score += 20
                score_breakdown['sma20_above_sma50'] = 20
            else:
                score_breakdown['sma20_above_sma50'] = 0
            
            # 4. RSI 40-70 区间（健康趋势区间）
            rsi_in_range = 40 <= current_rsi <= 70
            if rsi_in_range:
                score += 20
                score_breakdown['rsi_healthy'] = 20
            elif 30 <= current_rsi <= 80:
                score += 10  # 半分
                score_breakdown['rsi_healthy'] = 10
            else:
                score_breakdown['rsi_healthy'] = 0
            
            # 5. 距离52周高点 < 15%
            near_52w_high = dist_from_high > -0.15  # 距高点不超过15%
            if near_52w_high:
                score += 20
                score_breakdown['near_52w_high'] = 20
            elif dist_from_high > -0.25:
                score += 10  # 半分
                score_breakdown['near_52w_high'] = 10
            else:
                score_breakdown['near_52w_high'] = 0
            
            return {
                'score': score,
                'data': {
                    'price': round(current_price, 2),
                    'sma20': round(current_sma20, 2),
                    'sma50': round(current_sma50, 2),
                    'sma200': round(current_sma200, 2) if current_sma200 else None,
                    'rsi': round(current_rsi, 2),
                    'dist_from_52w_high': round(dist_from_high, 4),
                    'price_above_sma50': price_above_sma50,
                    'score_breakdown': score_breakdown
                }
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} 技术评分失败: {e}")
            return {'score': 0, 'data': None}
    
    def _calculate_technical_from_finviz(self, finviz_data: Dict) -> Dict:
        """
        从 Finviz 数据计算技术评分
        
        Args:
            finviz_data: Finviz 解析后的数据字典
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        try:
            price = finviz_data.get('price', 0)
            sma20 = finviz_data.get('sma20', 0)
            sma50 = finviz_data.get('sma50', 0)
            sma200 = finviz_data.get('sma200', 0)
            rsi = finviz_data.get('rsi', 50)
            high_52w = finviz_data.get('week52_high', 0)
            
            score = 0
            score_breakdown = {}
            
            # 1. Price > SMA50
            if price and sma50 and price > sma50:
                score += 20
                score_breakdown['price_above_sma50'] = 20
            else:
                score_breakdown['price_above_sma50'] = 0
            
            # 2. Price > SMA200
            if price and sma200 and price > sma200:
                score += 20
                score_breakdown['price_above_sma200'] = 20
            else:
                score_breakdown['price_above_sma200'] = 0
            
            # 3. SMA20 > SMA50
            if sma20 and sma50 and sma20 > sma50:
                score += 20
                score_breakdown['sma20_above_sma50'] = 20
            else:
                score_breakdown['sma20_above_sma50'] = 0
            
            # 4. RSI 40-70
            if rsi and 40 <= rsi <= 70:
                score += 20
                score_breakdown['rsi_healthy'] = 20
            elif rsi and 30 <= rsi <= 80:
                score += 10
                score_breakdown['rsi_healthy'] = 10
            else:
                score_breakdown['rsi_healthy'] = 0
            
            # 5. 距离52周高点
            if price and high_52w:
                dist = (price - high_52w) / high_52w
                if dist > -0.15:
                    score += 20
                    score_breakdown['near_52w_high'] = 20
                elif dist > -0.25:
                    score += 10
                    score_breakdown['near_52w_high'] = 10
                else:
                    score_breakdown['near_52w_high'] = 0
            else:
                score_breakdown['near_52w_high'] = 0
            
            return {
                'score': score,
                'data': {
                    'price': price,
                    'sma20': sma20,
                    'sma50': sma50,
                    'sma200': sma200,
                    'rsi': rsi,
                    'week52_high': high_52w,
                    'price_above_sma50': price > sma50 if price and sma50 else False,
                    'score_breakdown': score_breakdown,
                    'source': 'finviz'
                }
            }
            
        except Exception as e:
            logger.error(f"从 Finviz 计算技术评分失败: {e}")
            return {'score': 0, 'data': None}
    
    def calculate_momentum_score(
        self, 
        symbol: str, 
        sector_etf: str = None,
        finviz_data: Dict = None
    ) -> Dict:
        """
        计算动量评分 (权重: 30%)
        
        评分项:
        1. 5日收益率 > 0 (+25)
        2. 20日收益率 > 0 (+25)
        3. 相对强度 RS > 0 (+25)
        4. 63日收益率 > 0 (+25)
        
        Args:
            symbol: 股票代码
            sector_etf: 所属板块ETF（用于计算RS）
            finviz_data: Finviz 数据（可选）
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        from .technical import calculate_returns
        
        try:
            score = 0
            score_breakdown = {}
            data = {}
            
            # 优先使用 Finviz 的表现数据
            if finviz_data:
                perf_week = finviz_data.get('perf_week', 0) or 0
                perf_month = finviz_data.get('perf_month', 0) or 0
                perf_quarter = finviz_data.get('perf_quarter', 0) or 0
                
                # 1. 周表现 > 0
                if perf_week > 0:
                    score += 25
                    score_breakdown['return_5d_positive'] = 25
                else:
                    score_breakdown['return_5d_positive'] = 0
                
                # 2. 月表现 > 0
                if perf_month > 0:
                    score += 25
                    score_breakdown['return_20d_positive'] = 25
                else:
                    score_breakdown['return_20d_positive'] = 0
                
                # 3. 季度表现 > 0
                if perf_quarter > 0:
                    score += 25
                    score_breakdown['return_63d_positive'] = 25
                else:
                    score_breakdown['return_63d_positive'] = 0
                
                data = {
                    'return_5d': perf_week,
                    'return_20d': perf_month,
                    'return_63d': perf_quarter,
                    'source': 'finviz'
                }
                
            else:
                # 从 IBKR 获取数据
                price_df = self.ibkr.get_price_data(symbol, '80 D')
                
                if price_df is None or len(price_df) < 20:
                    return {'score': 0, 'data': None}
                
                prices = price_df[symbol]
                
                return_5d = calculate_returns(prices, 5)
                return_20d = calculate_returns(prices, 20)
                return_63d = calculate_returns(prices, 63) if len(prices) >= 64 else 0
                
                # 评分
                if return_5d > 0:
                    score += 25
                    score_breakdown['return_5d_positive'] = 25
                else:
                    score_breakdown['return_5d_positive'] = 0
                
                if return_20d > 0:
                    score += 25
                    score_breakdown['return_20d_positive'] = 25
                else:
                    score_breakdown['return_20d_positive'] = 0
                
                if return_63d > 0:
                    score += 25
                    score_breakdown['return_63d_positive'] = 25
                else:
                    score_breakdown['return_63d_positive'] = 0
                
                data = {
                    'return_5d': round(return_5d, 4),
                    'return_20d': round(return_20d, 4),
                    'return_63d': round(return_63d, 4),
                    'source': 'ibkr'
                }
            
            # 4. 相对强度（相对板块ETF）
            if sector_etf:
                try:
                    rs_result = self.ibkr.analyze_sector_vs_spy(symbol, sector_etf)
                    if rs_result and rs_result.get('RS_20D', 0) and rs_result['RS_20D'] > 0:
                        score += 25
                        score_breakdown['rs_positive'] = 25
                        data['rs_20d'] = rs_result['RS_20D']
                    else:
                        score_breakdown['rs_positive'] = 0
                        data['rs_20d'] = rs_result.get('RS_20D') if rs_result else None
                except Exception as e:
                    logger.warning(f"计算 {symbol} RS 失败: {e}")
                    score_breakdown['rs_positive'] = 0
            else:
                # 没有板块ETF参考，给默认半分
                score += 12.5
                score_breakdown['rs_positive'] = 12.5
            
            data['score_breakdown'] = score_breakdown
            
            return {
                'score': score,
                'data': data
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} 动量评分失败: {e}")
            return {'score': 0, 'data': None}
    
    def calculate_volume_score(
        self, 
        symbol: str,
        finviz_data: Dict = None
    ) -> Dict:
        """
        计算成交量评分 (权重: 20%)
        
        评分项:
        1. 相对成交量 > 1.0 (+50) - 放量
        2. 成交量趋势 OBV 上升 (+50)
        
        Args:
            symbol: 股票代码
            finviz_data: Finviz 数据（可选）
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        from .technical import calculate_obv, calculate_obv_trend, calculate_relative_volume
        
        try:
            score = 0
            score_breakdown = {}
            data = {}
            
            # 1. 相对成交量
            if finviz_data and finviz_data.get('rel_volume'):
                rel_vol = finviz_data['rel_volume']
                data['rel_volume'] = rel_vol
                data['source'] = 'finviz'
                
                if rel_vol > 1.5:
                    score += 50
                    score_breakdown['rel_volume'] = 50
                elif rel_vol > 1.0:
                    score += 25
                    score_breakdown['rel_volume'] = 25
                else:
                    score_breakdown['rel_volume'] = 0
            else:
                # 从 IBKR 获取
                ohlcv = self.ibkr.get_ohlcv_data(symbol, '30 D')
                
                if ohlcv is not None and len(ohlcv) >= 20:
                    volumes = ohlcv['volume']
                    rel_vol = calculate_relative_volume(volumes)
                    data['rel_volume'] = round(rel_vol, 2)
                    data['source'] = 'ibkr'
                    
                    if rel_vol > 1.5:
                        score += 50
                        score_breakdown['rel_volume'] = 50
                    elif rel_vol > 1.0:
                        score += 25
                        score_breakdown['rel_volume'] = 25
                    else:
                        score_breakdown['rel_volume'] = 0
                else:
                    score_breakdown['rel_volume'] = 0
            
            # 2. OBV 趋势
            ohlcv = self.ibkr.get_ohlcv_data(symbol, '30 D')
            
            if ohlcv is not None and len(ohlcv) >= 20:
                prices = ohlcv['close']
                volumes = ohlcv['volume']
                
                obv = calculate_obv(prices, volumes)
                obv_trend = calculate_obv_trend(obv)
                
                data['obv_trend'] = obv_trend
                
                if obv_trend == 'Strong':
                    score += 50
                    score_breakdown['obv_trend'] = 50
                elif obv_trend == 'Neutral':
                    score += 25
                    score_breakdown['obv_trend'] = 25
                else:
                    score_breakdown['obv_trend'] = 0
            else:
                score_breakdown['obv_trend'] = 0
            
            data['score_breakdown'] = score_breakdown
            
            return {
                'score': score,
                'data': data
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} 成交量评分失败: {e}")
            return {'score': 0, 'data': None}
    
    def calculate_options_score(
        self, 
        symbol: str,
        mc_data: Dict = None
    ) -> Dict:
        """
        计算期权评分 (权重: 10%)
        
        数据源: MarketChameleon
        
        评分逻辑:
        - 基于 HeatScore
        - HeatScore > 70: 高分
        - HeatScore 50-70: 中等
        - HeatScore < 50: 低分
        
        Args:
            symbol: 股票代码
            mc_data: MarketChameleon 数据
        
        Returns:
            dict: {'score': float, 'data': dict}
        """
        try:
            if not mc_data:
                return {'score': 50, 'data': {'source': 'default'}}
            
            heat_score = mc_data.get('heat_score', 50)
            risk_score = mc_data.get('risk_score', 50)
            heat_type = mc_data.get('heat_type', 'NORMAL')
            
            # 基于 HeatScore 和 RiskScore 综合评分
            if heat_type == 'TREND_HEAT':
                # 趋势热：热度高+风险适中
                score = 80 + min(20, (heat_score - 70) * 0.5)
            elif heat_score > 70:
                if risk_score < 80:
                    score = 80 + min(20, (heat_score - 70) * 0.5)
                else:
                    # 高热度但高风险（可能有事件）
                    score = 60
            elif heat_score > 50:
                score = 50 + (heat_score - 50)
            else:
                score = heat_score
            
            return {
                'score': min(100, round(score, 2)),
                'data': {
                    'heat_score': heat_score,
                    'risk_score': risk_score,
                    'heat_type': heat_type,
                    'ivr': mc_data.get('ivr'),
                    'source': 'marketchameleon'
                }
            }
            
        except Exception as e:
            logger.error(f"计算 {symbol} 期权评分失败: {e}")
            return {'score': 50, 'data': None}
    
    def check_thresholds(
        self, 
        technical_data: Dict, 
        momentum_data: Dict
    ) -> Dict:
        """
        检查硬性门槛
        
        门槛:
        1. Price > SMA50
        2. RS > 0 (如果有)
        
        Args:
            technical_data: 技术评分结果
            momentum_data: 动量评分结果
        
        Returns:
            dict: {'all_pass': bool, 'details': dict}
        """
        results = {}
        all_pass = True
        
        # 1. Price > SMA50
        if technical_data and technical_data.get('data'):
            price_above_sma50 = technical_data['data'].get('price_above_sma50', False)
            results['price_above_sma50'] = 'PASS' if price_above_sma50 else 'FAIL'
            if not price_above_sma50:
                all_pass = False
        else:
            results['price_above_sma50'] = 'NO_DATA'
            all_pass = False
        
        # 2. RS > 0 (软门槛，有数据时检查)
        if momentum_data and momentum_data.get('data'):
            rs_20d = momentum_data['data'].get('rs_20d')
            if rs_20d is not None:
                results['rs_positive'] = 'PASS' if rs_20d > 0 else 'FAIL'
                # RS 是软门槛，不强制失败
            else:
                results['rs_positive'] = 'NO_DATA'
        else:
            results['rs_positive'] = 'NO_DATA'
        
        return {
            'all_pass': all_pass,
            'details': results
        }
    
    def calculate_composite_score(
        self,
        symbol: str,
        sector_etf: str = None,
        finviz_data: Dict = None,
        mc_data: Dict = None
    ) -> Dict:
        """
        计算个股综合评分
        
        Args:
            symbol: 股票代码
            sector_etf: 所属板块ETF
            finviz_data: Finviz 解析后的数据
            mc_data: MarketChameleon 数据
        
        Returns:
            dict: 完整评分结果
        """
        logger.info(f"开始计算 {symbol} 综合评分...")
        
        # 1. 计算各维度分数
        technical = self.calculate_technical_score(symbol, finviz_data)
        momentum = self.calculate_momentum_score(symbol, sector_etf, finviz_data)
        volume = self.calculate_volume_score(symbol, finviz_data)
        options = self.calculate_options_score(symbol, mc_data)
        
        # 2. 检查门槛
        thresholds = self.check_thresholds(technical, momentum)
        
        # 3. 计算综合分
        total_score = (
            self.WEIGHTS['technical'] * technical['score'] +
            self.WEIGHTS['momentum'] * momentum['score'] +
            self.WEIGHTS['volume'] * volume['score'] +
            self.WEIGHTS['options'] * options['score']
        )
        
        result = {
            'symbol': symbol,
            'sector_etf': sector_etf,
            'total_score': round(total_score, 2),
            'thresholds_pass': thresholds['all_pass'],
            'thresholds': thresholds['details'],
            'breakdown': {
                'technical': technical,
                'momentum': momentum,
                'volume': volume,
                'options': options
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
        sector_etf: str = None,
        finviz_data: List[Dict] = None,
        mc_data_map: Dict[str, Dict] = None
    ) -> List[Dict]:
        """
        批量计算多个股票的综合评分
        
        Args:
            symbols: 股票代码列表
            sector_etf: 所属板块ETF
            finviz_data: Finviz 数据列表
            mc_data_map: {symbol: mc_data} 映射
        
        Returns:
            List[dict]: 评分结果列表，按总分降序排列
        """
        # 构建 finviz 数据映射
        finviz_map = {}
        if finviz_data:
            for item in finviz_data:
                if item.get('symbol'):
                    finviz_map[item['symbol']] = item
        
        mc_data_map = mc_data_map or {}
        
        results = []
        
        for symbol in symbols:
            try:
                result = self.calculate_composite_score(
                    symbol=symbol,
                    sector_etf=sector_etf,
                    finviz_data=finviz_map.get(symbol),
                    mc_data=mc_data_map.get(symbol)
                )
                results.append(result)
            except Exception as e:
                logger.error(f"计算 {symbol} 评分失败: {e}")
                continue
        
        # 按总分降序排列并添加排名
        results.sort(key=lambda x: x['total_score'], reverse=True)
        for i, result in enumerate(results):
            result['rank'] = i + 1
        
        return results
    
    def get_top_stocks(
        self,
        symbols: List[str],
        sector_etf: str = None,
        finviz_data: List[Dict] = None,
        top_n: int = 10,
        must_pass_thresholds: bool = True
    ) -> List[Dict]:
        """
        获取评分最高的 Top N 股票
        
        Args:
            symbols: 股票代码列表
            sector_etf: 所属板块ETF
            finviz_data: Finviz 数据
            top_n: 返回数量
            must_pass_thresholds: 是否必须通过门槛
        
        Returns:
            List[dict]: Top N 股票评分结果
        """
        all_results = self.batch_calculate_scores(
            symbols=symbols,
            sector_etf=sector_etf,
            finviz_data=finviz_data
        )
        
        if must_pass_thresholds:
            filtered = [r for r in all_results if r['thresholds_pass']]
        else:
            filtered = all_results
        
        return filtered[:top_n]
    
    def score_etf_holdings(
        self,
        etf_symbol: str,
        holdings_data: List[Dict]
    ) -> Dict:
        """
        对 ETF 的持仓进行评分
        
        Args:
            etf_symbol: ETF 代码
            holdings_data: ETF 持仓的 Finviz 数据
        
        Returns:
            dict: {
                'etf': str,
                'total_holdings': int,
                'scored_holdings': int,
                'pass_rate': float,
                'average_score': float,
                'top_10': List[dict],
                'all_scores': List[dict]
            }
        """
        symbols = [h['symbol'] for h in holdings_data if h.get('symbol')]
        
        # 批量评分
        all_scores = self.batch_calculate_scores(
            symbols=symbols,
            sector_etf=etf_symbol,
            finviz_data=holdings_data
        )
        
        # 统计
        passed = [s for s in all_scores if s['thresholds_pass']]
        pass_rate = len(passed) / len(all_scores) if all_scores else 0
        avg_score = sum(s['total_score'] for s in all_scores) / len(all_scores) if all_scores else 0
        
        return {
            'etf': etf_symbol,
            'total_holdings': len(holdings_data),
            'scored_holdings': len(all_scores),
            'passed_holdings': len(passed),
            'pass_rate': round(pass_rate, 4),
            'average_score': round(avg_score, 2),
            'top_10': all_scores[:10],
            'all_scores': all_scores
        }


# 便捷函数
def create_stock_calculator(ibkr, futu=None) -> StockScoreCalculator:
    """
    创建个股评分计算器的工厂函数
    
    Args:
        ibkr: IBKRConnector 实例
        futu: FutuConnector 实例（可选）
    
    Returns:
        StockScoreCalculator 实例
    """
    return StockScoreCalculator(ibkr=ibkr, futu=futu)
