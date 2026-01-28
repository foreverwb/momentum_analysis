"""
IBKR API 连接器
整合已有实现：ibkr_relative_momentum.py, ibkr_52week_high_demo.py

提供功能：
- 连接管理（connect/disconnect）
- 历史价格数据获取
- 52周高低点计算
- 相对动量(RelMom)计算
- VIX 数据获取
"""

from ib_insync import IB, Stock, Index, util
import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from datetime import datetime
from time import perf_counter

from .base import BrokerConnector, PriceDataMixin
from app.core.timing import timed
import structlog

logger = structlog.get_logger(__name__)


class IBKRConnector(BrokerConnector, PriceDataMixin):
    """
    IBKR API 连接器
    
    整合自:
    - ibkr_relative_momentum.py: RelMom 计算
    - ibkr_52week_high_demo.py: 52周高低点
    
    使用示例:
    ```python
    ibkr = IBKRConnector()
    if ibkr.connect():
        # 获取价格数据
        df = ibkr.get_price_data('AAPL', '1 Y')
        
        # 计算相对动量
        result = ibkr.analyze_sector_vs_spy('XLK', 'SPY')
        
        # 获取52周高低点
        high_low = ibkr.get_52_week_high_low('NVDA')
        
        ibkr.disconnect()
    ```
    """
    
    def __init__(
        self, 
        host: str = '127.0.0.1', 
        port: int = 4002, 
        client_id: int = 3,
        timeout: int = 30
    ):
        """
        初始化 IBKR 连接器
        
        Args:
            host: TWS/IB Gateway 主机地址
            port: 端口号 (TWS: 7497/7496, Gateway: 4002/4001)
            client_id: 客户端ID (多客户端连接时需要唯一)
            timeout: 连接超时时间（秒）
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self.ib = IB()
        self._connected = False
    
    # ==================== 连接管理 ====================
    
    def connect(self) -> bool:
        """
        建立 IBKR 连接
        
        Returns:
            bool: 连接成功返回 True
        """
        try:
            with timed(
                logger,
                "broker_connect",
                broker="ibkr",
                op="connect",
                host=self.host,
                port=self.port,
                client_id=self.client_id,
            ):
                self.ib.connect(
                    self.host,
                    self.port,
                    clientId=self.client_id,
                    timeout=self.timeout,
                )
                self.ib.reqMarketDataType(3)  # 使用延迟数据 (3=Delayed)
                self._connected = True
            return True
        except Exception:
            self._connected = False
            return False
    
    def disconnect(self) -> None:
        """断开 IBKR 连接"""
        if self.ib.isConnected():
            try:
                with timed(
                    logger,
                    "broker_disconnect",
                    broker="ibkr",
                    op="disconnect",
                    host=self.host,
                    port=self.port,
                    client_id=self.client_id,
                ):
                    self.ib.disconnect()
                    self._connected = False
            except Exception:
                self._connected = False
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._connected and self.ib.isConnected()
    
    def __enter__(self):
        """Context manager 支持"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 支持"""
        self.disconnect()
    
    # ==================== 价格数据 ====================
    
    def get_price_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        """
        获取历史价格数据 (仅收盘价)
        
        复用自: ibkr_relative_momentum.py -> get_price_data()
        
        Args:
            symbol: 股票代码
            duration: 数据长度 (如 '80 D', '1 Y', '2 Y')
        
        Returns:
            DataFrame with columns: [date, {symbol}]
        """
        if not self.is_connected():
            logger.warning(
                "ibkr_hist_close",
                broker="ibkr",
                op="hist_close",
                symbol=symbol,
                duration=duration,
                status="fail",
                reason="not_connected",
            )
            return None

        try:
            with timed(
                logger,
                "ibkr_hist_close",
                broker="ibkr",
                op="hist_close",
                symbol=symbol,
                duration=duration,
            ) as details:
                stock = Stock(symbol, 'SMART', 'USD')
                self.ib.qualifyContracts(stock)

                bars = self.ib.reqHistoricalData(
                    stock,
                    endDateTime='',
                    durationStr=duration,
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1
                )

                if not bars:
                    details["status"] = "empty"
                    details["bars"] = 0
                    return None

                df = util.df(bars)
                df = df[['date', 'close']].copy()
                df.columns = ['date', symbol]
                details["bars"] = len(df)
                details["start"] = _format_date(df['date'].iloc[0])
                details["end"] = _format_date(df['date'].iloc[-1])
                return df
        except Exception:
            return None
    
    def get_ohlcv_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        """
        获取完整 OHLCV 数据
        
        Args:
            symbol: 股票代码
            duration: 数据长度
        
        Returns:
            DataFrame with columns: [date, open, high, low, close, volume]
        """
        if not self.is_connected():
            logger.warning(
                "ibkr_hist_ohlcv",
                broker="ibkr",
                op="hist_ohlcv",
                symbol=symbol,
                duration=duration,
                status="fail",
                reason="not_connected",
            )
            return None

        try:
            with timed(
                logger,
                "ibkr_hist_ohlcv",
                broker="ibkr",
                op="hist_ohlcv",
                symbol=symbol,
                duration=duration,
            ) as details:
                stock = Stock(symbol, 'SMART', 'USD')
                self.ib.qualifyContracts(stock)

                bars = self.ib.reqHistoricalData(
                    stock,
                    endDateTime='',
                    durationStr=duration,
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1
                )

                if not bars:
                    details["status"] = "empty"
                    details["bars"] = 0
                    return None

                df = util.df(bars)
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
                details["bars"] = len(df)
                details["start"] = _format_date(df['date'].iloc[0])
                details["end"] = _format_date(df['date'].iloc[-1])
                return df
        except Exception:
            return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格
        
        Args:
            symbol: 股票代码
        
        Returns:
            当前价格 (float)，获取失败返回 None
        """
        if not self.is_connected():
            logger.error("IBKR 未连接")
            return None
        
        try:
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            ticker = self.ib.reqMktData(stock, '', snapshot=True)
            self.ib.sleep(2)
            price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
            self.ib.cancelMktData(stock)
            
            return price
            
        except Exception as e:
            logger.error(f"❌ 获取 {symbol} 当前价格失败: {e}")
            return None
    
    def batch_get_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """
        批量获取当前价格
        
        Args:
            symbols: 股票代码列表
        
        Returns:
            {symbol: price} 字典
        """
        results = {}
        for symbol in symbols:
            results[symbol] = self.get_current_price(symbol)
            self.ib.sleep(0.3)  # 避免请求过快
        return results
    
    # ==================== 52周高低点 ====================
    
    def get_52_week_high_low(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取 52 周高低点
        
        复用自: ibkr_52week_high_demo.py -> get_52_week_high_low()
        
        Args:
            symbol: 股票代码
        
        Returns:
            dict: {
                'symbol': str,
                'current_price': float,
                '52w_high': float,
                '52w_low': float,
                '52w_high_date': datetime,
                '52w_low_date': datetime,
                'pct_from_52w_high': float,  # 负值表示低于高点
                'pct_from_52w_low': float,   # 正值表示高于低点
                'near_52w_high': bool,       # 距离高点5%以内
                'near_52w_low': bool,        # 距离低点5%以内
            }
        """
        if not self.is_connected():
            logger.error("IBKR 未连接")
            return None
        
        try:
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            # 获取过去1年的日线数据
            bars = self.ib.reqHistoricalData(
                stock,
                endDateTime='',
                durationStr='1 Y',
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True
            )
            
            if not bars:
                logger.warning(f"⚠️ 未获取到 {symbol} 的历史数据")
                return None
            
            df = util.df(bars)
            
            # 计算52周最高和最低
            week_52_high = df['high'].max()
            week_52_low = df['low'].min()
            
            # 获取当前价格
            ticker = self.ib.reqMktData(stock, '', snapshot=True)
            self.ib.sleep(2)
            current_price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
            self.ib.cancelMktData(stock)
            
            if current_price is None or current_price <= 0:
                current_price = df['close'].iloc[-1]
            
            # 计算距离52周高低点的百分比
            pct_from_high = ((current_price - week_52_high) / week_52_high) * 100
            pct_from_low = ((current_price - week_52_low) / week_52_low) * 100
            
            # 找到52周高低点的日期
            high_date = df[df['high'] == week_52_high]['date'].iloc[0]
            low_date = df[df['low'] == week_52_low]['date'].iloc[0]
            
            result = {
                'symbol': symbol,
                'current_price': current_price,
                '52w_high': week_52_high,
                '52w_low': week_52_low,
                '52w_high_date': high_date,
                '52w_low_date': low_date,
                'pct_from_52w_high': pct_from_high,
                'pct_from_52w_low': pct_from_low,
                'near_52w_high': abs(pct_from_high) < 5,  # 距离高点5%以内
                'near_52w_low': abs(pct_from_low) < 5,    # 距离低点5%以内
            }
            
            logger.info(f"✅ {symbol}: 52周高点=${week_52_high:.2f}, 52周低点=${week_52_low:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 获取 {symbol} 52周数据失败: {e}")
            return None
    
    # ==================== 相对动量计算 ====================
    
    def calculate_relative_strength(
        self, 
        sector_df: pd.DataFrame, 
        spy_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算相对强度 RS(t) = Price_sector(t) / Price_spy(t)
        
        复用自: ibkr_relative_momentum.py -> calculate_relative_strength()
        
        Args:
            sector_df: 行业ETF价格数据 DataFrame [date, {symbol}]
            spy_df: SPY价格数据 DataFrame [date, SPY]
        
        Returns:
            DataFrame with RS and RS changes
        """
        sector_symbol = [col for col in sector_df.columns if col != 'date'][0]
        spy_symbol = [col for col in spy_df.columns if col != 'date'][0]
        
        # 合并数据，确保日期对齐
        merged = pd.merge(sector_df, spy_df, on='date', how='inner')
        
        # 计算相对强度 RS(t)
        merged['RS'] = merged[sector_symbol] / merged[spy_symbol]
        
        # 计算不同周期的RS变化
        # RS_5D 变化 = (RS(t) - RS(t-5)) / RS(t-5)
        merged['RS_5D_change'] = merged['RS'].pct_change(5)
        
        # RS_20D 变化
        merged['RS_20D_change'] = merged['RS'].pct_change(20)
        
        # RS_63D 变化 (约3个月)
        merged['RS_63D_change'] = merged['RS'].pct_change(63)
        
        return merged
    
    def calculate_rel_mom(self, rs_df: pd.DataFrame) -> pd.DataFrame:
        """
        计算相对动量 RelMom
        
        公式: RelMom = 0.45 × RS_20D变化 + 0.35 × RS_63D变化 + 0.20 × RS_5D变化
        
        复用自: ibkr_relative_momentum.py -> calculate_rel_mom()
        
        Args:
            rs_df: 包含 RS 变化的 DataFrame
        
        Returns:
            DataFrame with RelMom column added
        """
        rs_df = rs_df.copy()
        rs_df['RelMom'] = (
            0.45 * rs_df['RS_20D_change'] +
            0.35 * rs_df['RS_63D_change'] +
            0.20 * rs_df['RS_5D_change']
        )
        return rs_df
    
    def analyze_sector_vs_spy(
        self, 
        sector_symbol: str, 
        benchmark: str = 'SPY'
    ) -> Optional[Dict[str, Any]]:
        """
        完整分析：计算行业ETF相对SPY的相对动量
        
        Args:
            sector_symbol: 行业ETF代码 (如 'XLK', 'XLF', 'XLE')
            benchmark: 基准指数 (默认 'SPY')
        
        Returns:
            dict: {
                'symbol': str,
                'benchmark': str,
                'date': datetime,
                'sector_price': float,
                'benchmark_price': float,
                'RS': float,
                'RS_5D': float,
                'RS_20D': float,
                'RS_63D': float,
                'RelMom': float,
            }
        """
        logger.info(
            "calc_relmom",
            broker="ibkr",
            op="relmom",
            symbol=sector_symbol,
            benchmark=benchmark,
            stage="start",
            status="start",
        )
        start_ts = perf_counter()
        
        # 获取行业ETF数据 (需要约80天数据来计算63天变化)
        sector_df = self.get_price_data(sector_symbol, '80 D')
        if sector_df is None:
            elapsed_ms = (perf_counter() - start_ts) * 1000
            logger.warning(
                "calc_relmom",
                broker="ibkr",
                op="relmom",
                symbol=sector_symbol,
                benchmark=benchmark,
                stage="done",
                status="empty",
                reason="sector_data_empty",
                elapsed_ms=elapsed_ms,
            )
            return None
        
        # 获取基准数据
        spy_df = self.get_price_data(benchmark, '80 D')
        if spy_df is None:
            elapsed_ms = (perf_counter() - start_ts) * 1000
            logger.warning(
                "calc_relmom",
                broker="ibkr",
                op="relmom",
                symbol=sector_symbol,
                benchmark=benchmark,
                stage="done",
                status="empty",
                reason="benchmark_data_empty",
                elapsed_ms=elapsed_ms,
            )
            return None
        
        # 计算相对强度和相对动量
        rs_df = self.calculate_relative_strength(sector_df, spy_df)
        result_df = self.calculate_rel_mom(rs_df)
        
        # 返回最新结果
        latest = result_df.iloc[-1]
        
        # 安全处理日期格式
        date_val = latest['date']
        if hasattr(date_val, 'strftime'):
            date_str = date_val.strftime('%Y-%m-%d')
        else:
            date_str = str(date_val)
        
        result = {
            'symbol': sector_symbol,
            'benchmark': benchmark,
            'date': date_str,
            'sector_price': float(latest[sector_symbol]),
            'benchmark_price': float(latest[benchmark]),
            'RS': float(latest['RS']),
            'RS_5D': float(latest['RS_5D_change']) if pd.notna(latest['RS_5D_change']) else None,
            'RS_20D': float(latest['RS_20D_change']) if pd.notna(latest['RS_20D_change']) else None,
            'RS_63D': float(latest['RS_63D_change']) if pd.notna(latest['RS_63D_change']) else None,
            'RelMom': float(latest['RelMom']) if pd.notna(latest['RelMom']) else None,
        }
        
        # 评估相对动量强弱
        if result['RelMom'] is not None:
            rel_mom = result['RelMom']
            if rel_mom > 0.05:
                result['strength'] = 'STRONG'
                result['description'] = '强势，显著跑赢大盘'
            elif rel_mom > 0.02:
                result['strength'] = 'MODERATE_STRONG'
                result['description'] = '较强，略微跑赢大盘'
            elif rel_mom > -0.02:
                result['strength'] = 'NEUTRAL'
                result['description'] = '中性，与大盘同步'
            elif rel_mom > -0.05:
                result['strength'] = 'MODERATE_WEAK'
                result['description'] = '较弱，略微跑输大盘'
            else:
                result['strength'] = 'WEAK'
                result['description'] = '弱势，显著跑输大盘'

        elapsed_ms = (perf_counter() - start_ts) * 1000
        relmom = result.get("RelMom")
        relmom_str = f"{relmom:.4f}" if relmom is not None else "N/A"
        logger.info(
            "calc_relmom",
            broker="ibkr",
            op="relmom",
            symbol=sector_symbol,
            benchmark=benchmark,
            stage="done",
            status="ok",
            relmom=relmom,
            relmom_display=relmom_str,
            strength=result.get("strength"),
            elapsed_ms=elapsed_ms,
        )
        return result
    
    def batch_calculate_rel_mom(
        self, 
        symbols: List[str], 
        benchmark: str = 'SPY'
    ) -> pd.DataFrame:
        """
        批量计算多个ETF的相对动量
        
        Args:
            symbols: ETF代码列表
            benchmark: 基准指数
        
        Returns:
            DataFrame 按 RelMom 降序排列
        """
        results = []
        
        for symbol in symbols:
            result = self.analyze_sector_vs_spy(symbol, benchmark)
            if result:
                results.append(result)
            self.ib.sleep(0.5)  # 避免请求过快
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df = df.sort_values('RelMom', ascending=False)
        return df
    
    # ==================== VIX 数据 ====================
    
    def get_vix(self) -> Optional[float]:
        """
        获取 VIX 指数
        
        Returns:
            VIX 值 (float)
        """
        if not self.is_connected():
            logger.warning(
                "ibkr_vix",
                broker="ibkr",
                op="vix",
                status="fail",
                reason="not_connected",
            )
            return None

        try:
            with timed(
                logger,
                "ibkr_vix",
                broker="ibkr",
                op="vix",
                symbol="VIX",
            ) as details:
                vix = Index('VIX', 'CBOE')
                self.ib.qualifyContracts(vix)

                ticker = self.ib.reqMktData(vix, '', snapshot=True)
                self.ib.sleep(2)
                vix_value = ticker.last if ticker.last and ticker.last > 0 else ticker.close
                self.ib.cancelMktData(vix)
                details["value"] = float(vix_value) if vix_value is not None else None
                if vix_value is None:
                    details["status"] = "empty"
                    return None
                return vix_value
        except Exception:
            return None
    
    def get_spy_with_sma(self, sma_periods: List[int] = [20, 50, 200]) -> Optional[Dict[str, Any]]:
        """
        获取 SPY 价格和移动平均线
        
        用于 Regime Gate 计算
        
        Args:
            sma_periods: SMA 周期列表
        
        Returns:
            dict: {
                'price': float,
                'sma20': float,
                'sma50': float,
                'sma200': float,
                'price_above_sma20': bool,
                'price_above_sma50': bool,
                'price_above_sma200': bool,
            }
        """
        df = self.get_ohlcv_data('SPY', '1 Y')
        if df is None:
            return None
        
        result = {
            'price': df['close'].iloc[-1]
        }
        
        for period in sma_periods:
            sma_key = f'sma{period}'
            above_key = f'price_above_sma{period}'
            
            sma = df['close'].rolling(window=period).mean()
            result[sma_key] = sma.iloc[-1] if len(sma) >= period else None
            
            if result[sma_key]:
                result[above_key] = result['price'] > result[sma_key]
            else:
                result[above_key] = None
        
        # 计算 SMA20 斜率
        if len(df) >= 25:
            sma20 = df['close'].rolling(window=20).mean()
            result['sma20_slope'] = (sma20.iloc[-1] - sma20.iloc[-5]) / 5
        else:
            result['sma20_slope'] = None
        
        # 计算 20日收益率
        if len(df) >= 21:
            result['return_20d'] = (df['close'].iloc[-1] - df['close'].iloc[-21]) / df['close'].iloc[-21]
        else:
            result['return_20d'] = None
        
        return result


# 便捷函数
def create_ibkr_connector(
    host: str = '127.0.0.1',
    port: int = 4002,
    client_id: int = 1
) -> IBKRConnector:
    """
    创建 IBKR 连接器的工厂函数
    
    Args:
        host: TWS/Gateway 主机
        port: 端口号
        client_id: 客户端ID
    
    Returns:
        IBKRConnector 实例
    """
    return IBKRConnector(host=host, port=port, client_id=client_id)


def _format_date(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
