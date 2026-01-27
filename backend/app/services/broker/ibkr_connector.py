"""
IBKR API 连接器
整合已有实现：ibkr_relative_momentum.py, ibkr_52week_high_demo.py

提供功能：
- 连接管理（connect/disconnect）
- 历史价格数据获取
- 52周高低点计算
- 相对动量(RelMom)计算
- VIX 数据获取

依赖: ib_insync (可选 - 未安装时使用 Stub 模式)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from datetime import datetime
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading
import time

from .base import BrokerConnector, PriceDataMixin
from app.core.timing import timed
import structlog

logger = structlog.get_logger(__name__)

# ==================== 依赖检查 ====================

IB_INSYNC_AVAILABLE = False
NEST_ASYNCIO_AVAILABLE = False
_IB = None
_Stock = None
_Index = None
_util = None

def _is_uvloop() -> bool:
    try:
        loop = asyncio.get_running_loop()
        if loop.__class__.__module__.startswith("uvloop"):
            return True
    except RuntimeError:
        pass
    try:
        policy = asyncio.get_event_loop_policy()
        return policy.__class__.__module__.startswith("uvloop")
    except Exception:
        return False


# 尝试导入 nest_asyncio 解决嵌套事件循环问题
try:
    import nest_asyncio
    if _is_uvloop():
        logger.info("检测到 uvloop，跳过 nest_asyncio.apply (uvloop 不支持 patch)")
    else:
        try:
            nest_asyncio.apply()
            NEST_ASYNCIO_AVAILABLE = True
            logger.info("nest_asyncio 已应用，支持嵌套事件循环")
        except Exception as e:
            logger.warning(f"nest_asyncio apply 失败，将继续不启用嵌套事件循环: {e}")
except ImportError:
    logger.warning(
        "nest_asyncio 未安装，在 FastAPI 环境中可能遇到事件循环冲突。"
        "请运行 'pip install nest_asyncio --break-system-packages' 来安装。"
    )

try:
    from ib_insync import IB, Stock, Index, util
    IB_INSYNC_AVAILABLE = True
    _IB = IB
    _Stock = Stock
    _Index = Index
    _util = util
except ImportError:
    logger.warning(
        "ib_insync 未安装，IBKR 连接器将使用 Stub 模式。"
        "请运行 'pip install ib_insync --break-system-packages' 来安装。"
    )


def is_ibkr_available() -> bool:
    """检查 ib_insync 是否可用"""
    return IB_INSYNC_AVAILABLE


class IBKRConnectorStub(BrokerConnector, PriceDataMixin):
    """
    IBKR 连接器的 Stub 实现
    
    当 ib_insync 未安装时使用此实现
    所有方法返回适当的错误或默认值
    """
    
    def __init__(
        self, 
        host: str = '127.0.0.1', 
        port: int = 4002, 
        client_id: int = 3,
        timeout: int = 30
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self._connected = False
        self._stub_reason = "ib_insync 未安装"
    
    def connect(self) -> bool:
        logger.error(f"IBKR 连接失败: {self._stub_reason}")
        return False
    
    def disconnect(self) -> None:
        pass
    
    def is_connected(self) -> bool:
        return False
    
    def get_stub_reason(self) -> str:
        return self._stub_reason
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def get_price_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        logger.warning(f"无法获取 {symbol} 价格数据: {self._stub_reason}")
        return None
    
    def get_ohlcv_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        logger.warning(f"无法获取 {symbol} OHLCV 数据: {self._stub_reason}")
        return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        return None
    
    def get_52_week_high_low(self, symbol: str) -> Optional[Dict]:
        return None
    
    def analyze_sector_vs_spy(self, sector_symbol: str, benchmark: str = 'SPY') -> Optional[Dict]:
        return None
    
    def batch_calculate_rel_mom(self, symbols: List[str], benchmark: str = 'SPY') -> pd.DataFrame:
        return pd.DataFrame()
    
    def get_vix(self) -> Optional[float]:
        return None
    
    def get_spy_with_sma(self, sma_periods: List[int] = None) -> Optional[Dict[str, Any]]:
        if sma_periods is None:
            sma_periods = [20, 50, 200]
        return None


class IBKRConnectorReal(BrokerConnector, PriceDataMixin):
    """
    IBKR API 连接器 (真实实现)
    
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
        self.ib = None
        self._connected = False
        # Run ib_insync calls on a dedicated thread to avoid event loop conflicts.
        self._worker_thread_id = None
        self._worker_loop = None
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ibkr-worker",
            initializer=self._init_worker_loop,
        )

    def _init_worker_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_loop = loop

    def _run_in_worker(self, func, *args, **kwargs):
        if self._worker_thread_id == threading.get_ident():
            return func(*args, **kwargs)
        future = self._executor.submit(self._run_with_thread_id, func, *args, **kwargs)
        return future.result()

    def _run_with_thread_id(self, func, *args, **kwargs):
        if self._worker_thread_id is None:
            self._worker_thread_id = threading.get_ident()
        return func(*args, **kwargs)
    
    def _init_ib(self):
        """初始化 IB 实例"""
        if self.ib is not None:
            try:
                if self.ib.isConnected():
                    self.ib.disconnect()
            except:
                pass
        self.ib = _IB()
    
    # ==================== 连接管理 ====================
    
    def connect(self) -> bool:
        """
        建立 IBKR 连接
        
        Returns:
            bool: 连接成功返回 True
        """
        return self._run_in_worker(self._connect_impl)

    def _connect_impl(self) -> bool:
        # 如果已连接，先断开
        if self._connected and self.ib and self.ib.isConnected():
            logger.info("IBKR 已连接，跳过重复连接")
            return True
        
        # 重新初始化 IB 实例以避免事件循环问题
        self._init_ib()
        
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
                logger.info(f"✅ IBKR 连接成功: {self.host}:{self.port}")
            return True
        except RuntimeError as e:
            if "event loop" in str(e).lower():
                if _is_uvloop():
                    logger.error(
                        f"IBKR 事件循环冲突: {e}. "
                        "检测到 uvloop，nest_asyncio 与 uvloop 不兼容。"
                        "建议使用 `uvicorn --loop asyncio` 或改用 ib_insync 的异步 API。"
                    )
                else:
                    logger.error(
                        f"IBKR 事件循环冲突: {e}. "
                        "请确保已安装 nest_asyncio: pip install nest_asyncio --break-system-packages"
                    )
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"IBKR 连接失败: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> None:
        """断开 IBKR 连接"""
        self._run_in_worker(self._disconnect_impl)

    def _disconnect_impl(self) -> None:
        if self.ib and self.ib.isConnected():
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
                    logger.info("IBKR 已断开连接")
            except Exception as e:
                logger.warning(f"IBKR 断开连接时出错: {e}")
                self._connected = False
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._run_in_worker(self._is_connected_impl)

    def _is_connected_impl(self) -> bool:
        return self._connected and self.ib is not None and self.ib.isConnected()
    
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
        return self._run_in_worker(self._get_price_data_impl, symbol, duration)

    def _get_price_data_impl(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
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
                stock = _Stock(symbol, 'SMART', 'USD')
                self.ib.qualifyContracts(stock)

                bars = self.ib.reqHistoricalData(
                    stock,
                    endDateTime='',
                    durationStr=duration,
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1,
                    timeout=120  # Increase timeout to 120s for large data requests
                )

                if not bars:
                    details["status"] = "empty"
                    details["bars"] = 0
                    return None

                df = _util.df(bars)
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
        return self._run_in_worker(self._get_ohlcv_data_impl, symbol, duration)

    def _get_ohlcv_data_impl(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
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
                stock = _Stock(symbol, 'SMART', 'USD')
                self.ib.qualifyContracts(stock)

                bars = self.ib.reqHistoricalData(
                    stock,
                    endDateTime='',
                    durationStr=duration,
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1,
                    timeout=120  # Increase timeout to 120s for large data requests
                )

                if not bars:
                    details["status"] = "empty"
                    details["bars"] = 0
                    return None

                df = _util.df(bars)
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
        return self._run_in_worker(self._get_current_price_impl, symbol)

    def _get_current_price_impl(self, symbol: str) -> Optional[float]:
        if not self.is_connected():
            logger.error("IBKR 未连接")
            return None
        
        try:
            stock = _Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            ticker = self.ib.reqMktData(stock, '', snapshot=True)
            self.ib.sleep(2)
            
            price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
            self.ib.cancelMktData(stock)
            
            return price
        except Exception as e:
            logger.error(f"获取 {symbol} 价格失败: {e}")
            return None
    
    # ==================== 52周高低点 ====================
    
    def get_52_week_high_low(self, symbol: str) -> Optional[Dict]:
        """
        获取 52 周最高最低点
        
        复用自: ibkr_52week_high_demo.py
        
        Args:
            symbol: 股票代码
        
        Returns:
            dict: {
                'symbol': str,
                'high_52w': float,
                'low_52w': float,
                'current': float,
                'pct_from_high': float,  # 距离52周高点的跌幅 (%)
                'pct_from_low': float,   # 距离52周低点的涨幅 (%)
            }
        """
        df = self.get_ohlcv_data(symbol, '1 Y')
        
        if df is None or df.empty:
            return None
        
        high_52w = df['high'].max()
        low_52w = df['low'].min()
        current = df['close'].iloc[-1]
        
        return {
            'symbol': symbol,
            'high_52w': high_52w,
            'low_52w': low_52w,
            'current': current,
            'pct_from_high': (current - high_52w) / high_52w * 100,
            'pct_from_low': (current - low_52w) / low_52w * 100,
        }
    
    # ==================== 相对动量计算 ====================
    
    def calculate_relative_strength(
        self, 
        sector_df: pd.DataFrame, 
        spy_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算相对强度 RS
        
        复用自: ibkr_relative_momentum.py -> calculate_relative_strength()
        
        Args:
            sector_df: 行业ETF数据 [date, {sector}]
            spy_df: SPY数据 [date, SPY]
        
        Returns:
            DataFrame 包含 RS 及其变化
        """
        sector_col = sector_df.columns[1]
        spy_col = spy_df.columns[1]
        
        merged = pd.merge(sector_df, spy_df, on='date', how='inner')
        merged['RS'] = merged[sector_col] / merged[spy_col]
        
        merged['RS_5D_change'] = merged['RS'].pct_change(5)
        merged['RS_20D_change'] = merged['RS'].pct_change(20)
        merged['RS_63D_change'] = merged['RS'].pct_change(63)
        
        return merged
    
    def calculate_rel_mom(self, rs_df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 RelMom（相对动量）
        
        复用自: ibkr_relative_momentum.py -> calculate_rel_mom()
        
        公式: RelMom = (RS_5D*3 + RS_20D*2 + RS_63D*1) / 6
        
        Args:
            rs_df: 包含 RS 变化数据的 DataFrame
        
        Returns:
            DataFrame 添加 RelMom 列
        """
        rs_df = rs_df.copy()
        
        rs_5d = rs_df['RS_5D_change'].fillna(0)
        rs_20d = rs_df['RS_20D_change'].fillna(0)
        rs_63d = rs_df['RS_63D_change'].fillna(0)
        
        rs_df['RelMom'] = (rs_5d * 3 + rs_20d * 2 + rs_63d * 1) / 6
        
        return rs_df
    
    def analyze_sector_vs_spy(
        self, 
        sector_symbol: str, 
        benchmark: str = 'SPY'
    ) -> Optional[Dict]:
        """
        分析行业 ETF 相对于 SPY 的相对动量
        
        复用自: ibkr_relative_momentum.py -> analyze_sector_vs_spy()
        
        Args:
            sector_symbol: 行业ETF代码
            benchmark: 基准指数
        
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
        total = len(symbols)
        success = 0
        start_ts = time.time()

        for idx, symbol in enumerate(symbols, start=1):
            result = self.analyze_sector_vs_spy(symbol, benchmark)
            if result:
                results.append(result)
                success += 1

                # 获取计算结果
                relmom = result.get("RelMom")
                rs = result.get("RS")
                rs_5d = result.get("RS_5D")
                rs_20d = result.get("RS_20D")
                rs_63d = result.get("RS_63D")
                high_52w = result.get("high_52w")
                low_52w = result.get("low_52w")
                current_price = result.get("sector_price")

                # 格式化输出值
                relmom_str = f"{relmom:.4f}" if relmom is not None else "N/A"
                rs_str = f"{rs:.4f}" if rs is not None else "N/A"
                rs_5d_str = f"{rs_5d:+.2%}" if rs_5d is not None else "N/A"
                rs_20d_str = f"{rs_20d:+.2%}" if rs_20d is not None else "N/A"
                rs_63d_str = f"{rs_63d:+.2%}" if rs_63d is not None else "N/A"

                # 52周高低点格式化
                if high_52w and low_52w and current_price:
                    week52_str = f"高${high_52w:.2f} 低${low_52w:.2f} 当前${current_price:.2f}"
                else:
                    week52_str = "N/A"

                # IBKR 深度优化格式打印（多行易读）
                ibkr_block = "\n".join([
                    f"IBKR- [{idx}/{total}] {symbol}",
                    " - 历史价格(OHLCV): ✓ 获取成功",
                    f" - 52周高低点: {week52_str}",
                    f" - 相对强度 RS: {rs_str} (5D:{rs_5d_str}, 20D:{rs_20d_str}, 63D:{rs_63d_str})",
                    f" - 相对动量 RelMom: {relmom_str} [{result.get('strength', 'N/A')}]",
                    " - SMA 均线计算: ✓ 完成",
                    "---",
                ])
                logger.info(ibkr_block)
            else:
                logger.warning(f"IBKR - [{idx}/{total}] {symbol}: ✗ 数据获取失败")
            time.sleep(0.5)  # 避免请求过快

        if not results:
            elapsed = (time.time() - start_ts) / 60.0
            logger.info(f"IBKR - 批量计算完成: {success}/{total} 成功, 耗时 {elapsed:.1f}分钟")
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df = df.sort_values('RelMom', ascending=False)
        elapsed = (time.time() - start_ts) / 60.0
        logger.info(f"IBKR - 批量计算完成: {success}/{total} 成功, 耗时 {elapsed:.1f}分钟")
        return df
    
    # ==================== VIX 数据 ====================
    
    def get_vix(self) -> Optional[float]:
        """
        获取 VIX 指数
        
        Returns:
            VIX 值 (float)
        """
        return self._run_in_worker(self._get_vix_impl)

    def _get_vix_impl(self) -> Optional[float]:
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
                # Use historical data to get latest VIX value (more reliable than real-time snapshot)
                vix = _Index('VIX', 'CBOE')
                self.ib.qualifyContracts(vix)

                bars = self.ib.reqHistoricalData(
                    vix,
                    endDateTime='',
                    durationStr='1 D',  # Get last 1 day of data
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1,
                    timeout=30
                )

                if not bars:
                    details["status"] = "empty"
                    logger.warning(
                        "ibkr_vix",
                        broker="ibkr",
                        op="vix",
                        status="no_data",
                        reason="no_historical_bars",
                    )
                    return None

                # Get the most recent close price
                vix_value = bars[-1].close

                if vix_value is None or vix_value <= 0:
                    details["status"] = "empty"
                    logger.warning(
                        "ibkr_vix",
                        broker="ibkr",
                        op="vix",
                        status="invalid_value",
                        value=vix_value,
                    )
                    return None

                details["value"] = float(vix_value)
                details["date"] = _format_date(bars[-1].date)
                return float(vix_value)
        except Exception as e:
            logger.error(
                "ibkr_vix",
                broker="ibkr",
                op="vix",
                status="error",
                error=str(e),
            )
            return None
    
    def get_spy_with_sma(self, sma_periods: List[int] = None) -> Optional[Dict[str, Any]]:
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
        if sma_periods is None:
            sma_periods = [20, 50, 200]
            
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


# ==================== 工厂函数和类型别名 ====================

# 根据依赖可用性选择实现
if IB_INSYNC_AVAILABLE:
    IBKRConnector = IBKRConnectorReal
else:
    IBKRConnector = IBKRConnectorStub


def create_ibkr_connector(
    host: str = '127.0.0.1',
    port: int = 4002,
    client_id: int = 3
) -> BrokerConnector:
    """
    创建 IBKR 连接器的工厂函数
    
    Args:
        host: TWS/Gateway 主机
        port: 端口号
        client_id: 客户端ID
    
    Returns:
        IBKRConnector 实例 (真实或 Stub)
    """
    return IBKRConnector(host=host, port=port, client_id=client_id)


def _format_date(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
