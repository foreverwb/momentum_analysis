"""
数据编排服务
Orchestrator Service for Momentum Radar

负责协调多数据源的数据获取、处理和评分计算

功能:
1. 协调 IBKR/Futu 数据获取
2. 处理 Finviz/MarketChameleon 导入数据
3. 触发评分计算和 Regime Gate 判断
4. 管理数据缓存和状态同步
5. 提供高级工作流程编排
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from enum import Enum
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from time import perf_counter

import pandas as pd
import structlog

from ..core.broker_config import BrokerConfig, broker_defaults, load_broker_config

logger = structlog.get_logger(__name__)


# ==================== 枚举和数据类 ====================

class DataSource(Enum):
    """数据源枚举"""
    IBKR = "ibkr"
    FUTU = "futu"
    FINVIZ = "finviz"
    MARKET_CHAMELEON = "marketchameleon"
    LOCAL = "local"


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BrokerConnectionStatus:
    """Broker 连接状态"""
    broker: str
    is_connected: bool
    last_connected: Optional[datetime] = None
    last_error: Optional[str] = None
    config: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'broker': self.broker,
            'is_connected': self.is_connected,
            'last_connected': self.last_connected.isoformat() if self.last_connected else None,
            'last_error': self.last_error,
            'config': self.config
        }


@dataclass
class OrchestratorTask:
    """编排任务"""
    task_id: str
    task_type: str
    status: TaskStatus
    symbols: List[str]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    result: Optional[Dict] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'task_id': self.task_id,
            'task_type': self.task_type,
            'status': self.status.value,
            'symbols': self.symbols,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'progress': self.progress,
            'result': self.result,
            'error': self.error
        }


@dataclass
class MarketSnapshot:
    """市场快照"""
    timestamp: datetime
    regime: Dict
    spy_data: Dict
    vix: Optional[float]
    etf_rankings: List[Dict]
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'regime': self.regime,
            'spy_data': self.spy_data,
            'vix': self.vix,
            'etf_rankings': self.etf_rankings
        }


class _IBKRProviderAdapter:
    """
    Compatibility adapter to keep existing calculators working while
    orchestrator uses new provider-based IBKR stack.
    """

    def __init__(self, connection: Any, price_provider: Any, momentum_calculator_cls: Any):
        self._connection = connection
        self._price_provider = price_provider
        self._momentum_calculator_cls = momentum_calculator_cls

    def connect(self) -> bool:
        return bool(self._connection.connect())

    def disconnect(self) -> None:
        self._connection.disconnect()

    def is_connected(self) -> bool:
        try:
            return bool(self._connection.is_connected())
        except Exception:
            return False

    def get_price_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        return self._price_provider.get_close_prices(symbol=symbol, duration=duration)

    def get_ohlcv_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        return self._price_provider.get_ohlcv(symbol=symbol, duration=duration, bar_size='1 day')

    def get_current_price(self, symbol: str) -> Optional[float]:
        return self._price_provider.get_current_price(symbol=symbol)

    def get_vix(self) -> Optional[float]:
        return self._price_provider.get_vix()

    def get_last_error(self, max_age_seconds: float = 15.0) -> Optional[Dict[str, Any]]:
        getter = getattr(self._connection, "get_last_error", None)
        if not callable(getter):
            return None
        try:
            return getter(max_age_seconds=max_age_seconds)
        except Exception:
            return None

    def analyze_sector_vs_spy(self, sector_symbol: str, benchmark: str = 'SPY') -> Optional[Dict[str, Any]]:
        sector_df = self.get_price_data(sector_symbol, duration='80 D')
        benchmark_df = self.get_price_data(benchmark, duration='80 D')
        if sector_df is None or benchmark_df is None:
            return None

        result = self._momentum_calculator_cls.calculate_relative_momentum(sector_df, benchmark_df)
        if result is None:
            return None

        rel_mom = result.get('RelMom')
        strength = 'NEUTRAL'
        description = '中性,与大盘同步'
        if rel_mom is not None:
            if rel_mom > 0.05:
                strength = 'STRONG'
                description = '强势，显著跑赢大盘'
            elif rel_mom > 0.02:
                strength = 'MODERATE_STRONG'
                description = '较强,略微跑赢大盘'
            elif rel_mom > -0.02:
                strength = 'NEUTRAL'
                description = '中性,与大盘同步'
            elif rel_mom > -0.05:
                strength = 'MODERATE_WEAK'
                description = '较弱,略微跑输大盘'
            else:
                strength = 'WEAK'
                description = '弱势,显著跑输大盘'

        return {
            'symbol': sector_symbol,
            'benchmark': benchmark,
            'date': result.get('date'),
            'sector_price': result.get('sector_price'),
            'benchmark_price': result.get('benchmark_price'),
            'RS': result.get('RS'),
            'RS_5D': result.get('RS_5D'),
            'RS_20D': result.get('RS_20D'),
            'RS_63D': result.get('RS_63D'),
            'RelMom': rel_mom,
            'strength': strength,
            'description': description,
        }

    def batch_calculate_rel_mom(self, symbols: List[str], benchmark: str = 'SPY') -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for symbol in symbols:
            result = self.analyze_sector_vs_spy(symbol, benchmark=benchmark)
            if result is not None:
                rows.append(result)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        if 'RelMom' in df.columns:
            df = df.sort_values('RelMom', ascending=False, na_position='last').reset_index(drop=True)
        return df

    def get_spy_with_sma(
        self,
        symbol: str = 'SPY',
        sma_periods: Optional[List[int]] = None
    ) -> Optional[Dict[str, Any]]:
        from .calculators.technical import calculate_returns, calculate_sma, calculate_sma_slope

        normalized_symbol = symbol.upper().strip()
        if not normalized_symbol:
            return None

        if sma_periods is None:
            sma_periods = [20, 50, 200]
        if not sma_periods:
            sma_periods = [20, 50]

        max_period = max(sma_periods)
        duration = f"{max(120, max_period + 30)} D"
        df = self.get_price_data(normalized_symbol, duration=duration)
        if df is None or df.empty or normalized_symbol not in df.columns:
            return None

        prices = pd.to_numeric(df[normalized_symbol], errors='coerce').dropna()
        if len(prices) < max_period:
            return None

        latest_price = float(prices.iloc[-1])
        latest_date = df['date'].iloc[-1]
        latest_date_str = latest_date.strftime('%Y-%m-%d') if hasattr(latest_date, 'strftime') else str(latest_date)

        result: Dict[str, Any] = {
            'symbol': normalized_symbol,
            'price': latest_price,
            'date': latest_date_str,
            'return_20d': float(calculate_returns(prices, 20)) if len(prices) >= 21 else None,
        }

        for period in sma_periods:
            sma_series = calculate_sma(prices, period)
            value = sma_series.iloc[-1] if len(sma_series) > 0 else None
            result[f'sma{period}'] = float(value) if value is not None and pd.notna(value) else None

        sma20_value = result.get('sma20')
        sma50_value = result.get('sma50')
        if sma20_value is not None:
            result['sma20_slope'] = float(calculate_sma_slope(calculate_sma(prices, 20), period=5))
            result['dist_to_sma20'] = (latest_price - sma20_value) / sma20_value if sma20_value != 0 else None
        else:
            result['sma20_slope'] = None
            result['dist_to_sma20'] = None

        if sma50_value is not None:
            result['dist_to_sma50'] = (latest_price - sma50_value) / sma50_value if sma50_value != 0 else None
        else:
            result['dist_to_sma50'] = None

        return result


# ==================== 编排服务主类 ====================

class DataOrchestrator:
    """
    数据编排服务
    
    负责协调所有数据源和计算服务，提供统一的数据管理接口
    
    使用示例:
    ```python
    orchestrator = DataOrchestrator()
    
    # 连接 Broker
    await orchestrator.connect_brokers()
    
    # 获取市场快照
    snapshot = await orchestrator.get_market_snapshot()
    
    # 计算 ETF 评分
    rankings = await orchestrator.calculate_etf_rankings(['XLK', 'XLF', 'XLE'])
    
    # 断开连接
    await orchestrator.disconnect_all()
    ```
    """
    
    # 板块 ETF 列表
    SECTOR_ETFS = [
        'XLK', 'XLF', 'XLE', 'XLV', 'XLI', 
        'XLY', 'XLP', 'XLU', 'XLB', 'XLRE', 'XLC'
    ]
    
    # 行业 ETF 列表
    INDUSTRY_ETFS = [
        'SOXX', 'IGV', 'SMH', 'XBI', 'KBE',
        'XOP', 'OIH', 'ITA', 'XRT', 'XHB', 'IBB'
    ]
    
    def __init__(self):
        """初始化编排服务"""
        self._ibkr = None
        self._ibkr_connection = None
        self._price_provider = None
        self._technical_provider = None
        self._momentum_calculator_cls = None
        self._futu = None
        self._broker_config: BrokerConfig = load_broker_config()
        self._broker_status: Dict[str, BrokerConnectionStatus] = {}
        self._tasks: Dict[str, OrchestratorTask] = {}
        self._cache: Dict[str, Any] = {}
        self._cache_expiry: Dict[str, datetime] = {}

        defaults = broker_defaults(self._broker_config)
        
        # 初始化状态
        self._broker_status['ibkr'] = BrokerConnectionStatus(
            broker='ibkr',
            is_connected=False,
            config=dict(defaults['ibkr']),
        )
        self._broker_status['futu'] = BrokerConnectionStatus(
            broker='futu', 
            is_connected=False,
            config=dict(defaults['futu']),
        )
        
        logger.info("DataOrchestrator 初始化完成")
    
    # ==================== Broker 连接管理 ====================
    
    async def connect_ibkr(
        self, 
        host: Optional[str] = None, 
        port: Optional[int] = None, 
        client_id: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> bool:
        """
        连接 IBKR
        
        Args:
            host: IBKR 主机地址
            port: 端口号
            client_id: 客户端 ID
            timeout: 连接超时（秒）
        
        Returns:
            bool: 是否连接成功
        """
        defaults = self._broker_config.ibkr
        resolved_host = host.strip() if isinstance(host, str) and host.strip() else defaults.host
        resolved_port = port if isinstance(port, int) and port > 0 else defaults.port
        resolved_client_id = (
            client_id if isinstance(client_id, int) and client_id > 0 else defaults.client_id
        )
        resolved_timeout = timeout if isinstance(timeout, int) and timeout > 0 else defaults.timeout

        try:
            try:
                from .broker.ibkr.connection import IBKRConnection
                from .broker.ibkr.historical_data import IBKRHistoricalDataFetcher
                from .broker.ibkr.market_data import IBKRMarketDataFetcher
            except Exception as import_error:
                logger.warning(f"常规导入 broker.ibkr 失败，启用 fallback: {import_error}")

                services_dir = Path(__file__).resolve().parent
                broker_dir = services_dir / 'broker'
                ibkr_dir = broker_dir / 'ibkr'

                broker_pkg_name = 'app.services.broker'
                ibkr_pkg_name = 'app.services.broker.ibkr'

                broker_pkg = sys.modules.get(broker_pkg_name)
                if broker_pkg is None:
                    broker_pkg = types.ModuleType(broker_pkg_name)
                    broker_pkg.__path__ = [str(broker_dir)]
                    sys.modules[broker_pkg_name] = broker_pkg
                elif not hasattr(broker_pkg, '__path__'):
                    broker_pkg.__path__ = [str(broker_dir)]

                ibkr_pkg = sys.modules.get(ibkr_pkg_name)
                if ibkr_pkg is None:
                    ibkr_pkg = types.ModuleType(ibkr_pkg_name)
                    ibkr_pkg.__path__ = [str(ibkr_dir)]
                    sys.modules[ibkr_pkg_name] = ibkr_pkg
                elif not hasattr(ibkr_pkg, '__path__'):
                    ibkr_pkg.__path__ = [str(ibkr_dir)]

                def _load_module(module_name: str, file_path: Path):
                    if module_name in sys.modules:
                        return sys.modules[module_name]
                    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
                    if spec is None or spec.loader is None:
                        raise ImportError(f'Unable to load spec: {module_name}')
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    return module

                _load_module('app.services.broker.ibkr.utils', ibkr_dir / 'utils.py')
                connection_mod = _load_module('app.services.broker.ibkr.connection', ibkr_dir / 'connection.py')
                historical_mod = _load_module('app.services.broker.ibkr.historical_data', ibkr_dir / 'historical_data.py')
                market_mod = _load_module('app.services.broker.ibkr.market_data', ibkr_dir / 'market_data.py')

                IBKRConnection = connection_mod.IBKRConnection
                IBKRHistoricalDataFetcher = historical_mod.IBKRHistoricalDataFetcher
                IBKRMarketDataFetcher = market_mod.IBKRMarketDataFetcher

            from .data_providers.price_provider import PriceDataProvider
            from .data_providers.technical_provider import TechnicalDataProvider
            from .calculators.momentum import MomentumCalculator

            connection = IBKRConnection(
                host=resolved_host,
                port=resolved_port,
                client_id=resolved_client_id,
                timeout=resolved_timeout,
            )
            success = bool(await asyncio.to_thread(connection.connect))

            if success:
                historical_fetcher = IBKRHistoricalDataFetcher(connection)
                market_fetcher = IBKRMarketDataFetcher(connection)

                price_provider = PriceDataProvider(
                    ibkr_connection=connection,
                    historical_fetcher=historical_fetcher,
                    market_fetcher=market_fetcher,
                )
                technical_provider = TechnicalDataProvider(price_provider)

                self._ibkr_connection = connection
                self._price_provider = price_provider
                self._technical_provider = technical_provider
                self._momentum_calculator_cls = MomentumCalculator
                self._ibkr = _IBKRProviderAdapter(connection, price_provider, MomentumCalculator)
            else:
                try:
                    await asyncio.to_thread(connection.disconnect)
                except Exception:
                    pass
                self._ibkr_connection = None
                self._price_provider = None
                self._technical_provider = None
                self._momentum_calculator_cls = None
                self._ibkr = None
            
            self._broker_status['ibkr'] = BrokerConnectionStatus(
                broker='ibkr',
                is_connected=success,
                last_connected=datetime.now() if success else None,
                last_error=None if success else "Connection failed",
                config={
                    'host': resolved_host,
                    'port': resolved_port,
                    'client_id': resolved_client_id,
                    'timeout': resolved_timeout,
                }
            )
            
            if success:
                logger.info(f"✅ IBKR 连接成功: {resolved_host}:{resolved_port}")
            else:
                logger.error(f"❌ IBKR 连接失败: {resolved_host}:{resolved_port}")
            
            return success
            
        except Exception as e:
            logger.error(f"IBKR 连接异常: {e}")
            self._ibkr_connection = None
            self._price_provider = None
            self._technical_provider = None
            self._momentum_calculator_cls = None
            self._ibkr = None
            self._broker_status['ibkr'] = BrokerConnectionStatus(
                broker='ibkr',
                is_connected=False,
                last_error=str(e)
            )
            return False
    
    async def connect_futu(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        market: Optional[str] = None,
    ) -> bool:
        """
        连接富途 OpenD
        
        Args:
            host: OpenD 主机地址
            port: 端口号
            market: 市场代码（如 US/HK）
        
        Returns:
            bool: 是否连接成功
        """
        defaults = self._broker_config.futu
        resolved_host = host.strip() if isinstance(host, str) and host.strip() else defaults.host
        resolved_port = port if isinstance(port, int) and port > 0 else defaults.port
        resolved_market = market.strip() if isinstance(market, str) and market.strip() else defaults.market

        try:
            from .broker import create_futu_connector

            self._futu = create_futu_connector(
                host=resolved_host,
                port=resolved_port,
                market=resolved_market,
            )
            success = self._futu.connect()
            
            self._broker_status['futu'] = BrokerConnectionStatus(
                broker='futu',
                is_connected=success,
                last_connected=datetime.now() if success else None,
                last_error=None if success else "Connection failed",
                config={'host': resolved_host, 'port': resolved_port, 'market': resolved_market}
            )
            
            if success:
                logger.info(f"✅ Futu 连接成功: {resolved_host}:{resolved_port}")
            else:
                logger.error(f"❌ Futu 连接失败: {resolved_host}:{resolved_port}")
            
            return success
            
        except Exception as e:
            logger.error(f"Futu 连接异常: {e}")
            self._broker_status['futu'] = BrokerConnectionStatus(
                broker='futu',
                is_connected=False,
                last_error=str(e)
            )
            return False

    def get_broker_defaults(self) -> Dict[str, Dict[str, Any]]:
        """获取当前生效的 Broker 连接默认配置。"""
        return broker_defaults(self._broker_config)
    
    async def connect_brokers(self) -> Dict[str, bool]:
        """
        连接所有 Broker
        
        Returns:
            Dict[str, bool]: 各 Broker 连接状态
        """
        results = {}
        
        # 并行连接
        ibkr_task = asyncio.create_task(self.connect_ibkr())
        futu_task = asyncio.create_task(self.connect_futu())
        
        results['ibkr'] = await ibkr_task
        results['futu'] = await futu_task
        
        return results
    
    def disconnect_ibkr(self):
        """断开 IBKR 连接"""
        disconnected = False
        try:
            if self._ibkr_connection:
                self._ibkr_connection.disconnect()
                disconnected = True
            elif self._ibkr:
                self._ibkr.disconnect()
                disconnected = True
        except Exception as e:
            logger.warning(f"IBKR 断开连接时异常: {e}")
        finally:
            self._ibkr = None
            self._ibkr_connection = None
            self._price_provider = None
            self._technical_provider = None
            self._momentum_calculator_cls = None
            self._broker_status['ibkr'].is_connected = False
            if disconnected:
                logger.info("IBKR 已断开")
    
    def disconnect_futu(self):
        """断开 Futu 连接"""
        if self._futu:
            self._futu.disconnect()
            self._broker_status['futu'].is_connected = False
            logger.info("Futu 已断开")
    
    async def disconnect_all(self):
        """断开所有连接"""
        self.disconnect_ibkr()
        self.disconnect_futu()
        logger.info("所有 Broker 连接已断开")
    
    def get_broker_status(self) -> Dict[str, Dict]:
        """
        获取所有 Broker 连接状态
        
        Returns:
            Dict: Broker 状态字典
        """
        # 避免返回“状态缓存已连接，但运行时已断开”的陈旧结果
        self._sync_ibkr_runtime_status()
        return {
            broker: status.to_dict() 
            for broker, status in self._broker_status.items()
        }
    
    # ==================== 市场数据获取 ====================

    def _sync_ibkr_runtime_status(self) -> bool:
        """
        同步 IBKR 运行时连接状态到 broker_status，防止状态缓存陈旧。

        Returns:
            bool: 运行时是否可用
        """
        status = self._broker_status.get('ibkr')
        if status is None:
            return False

        runtime_connected = False
        runtime_error: Optional[str] = None

        if self._ibkr_connection is not None:
            try:
                runtime_connected = bool(self._ibkr_connection.is_connected())
            except Exception as exc:
                runtime_error = str(exc)
                runtime_connected = False
        elif self._ibkr is not None:
            try:
                runtime_connected = bool(self._ibkr.is_connected())
            except Exception as exc:
                runtime_error = str(exc)
                runtime_connected = False

        if runtime_connected:
            was_connected = status.is_connected
            status.is_connected = True
            status.last_error = None
            if status.last_connected is None or not was_connected:
                status.last_connected = datetime.now()
            return True

        was_connected = status.is_connected
        status.is_connected = False
        if runtime_error:
            status.last_error = runtime_error
        elif was_connected:
            status.last_error = "Connection lost"
        elif status.last_error is None:
            status.last_error = "Disconnected"

        if was_connected:
            if runtime_error:
                logger.warning("ibkr_runtime_disconnected", error=runtime_error)
            else:
                logger.warning("ibkr_runtime_disconnected")
        return False

    def _ibkr_ready(self) -> bool:
        """检查 IBKR 是否就绪（已连接且 provider 可用）。"""
        if not self._sync_ibkr_runtime_status():
            return False
        return self._ibkr is not None or self._price_provider is not None
    
    async def get_market_regime(self) -> Dict:
        """
        获取市场环境 (Regime Gate)
        
        Returns:
            Dict: Regime 信息
        """
        if self._ibkr is None or not self._ibkr_ready():
            return {
                'error': 'IBKR not connected',
                'status': 'UNKNOWN',
                'regime': 'UNKNOWN',
                'fire_power': '未知'
            }
        
        try:
            from .calculators.regime_gate import RegimeGateCalculator
            
            calc = RegimeGateCalculator(self._ibkr)
            # Regime 计算会触发阻塞式 IBKR 调用，放到线程避免卡住事件循环。
            result = await asyncio.to_thread(calc.calculate_regime)
            
            return result
            
        except Exception as e:
            logger.error(f"获取市场环境失败: {e}")
            return {
                'error': str(e),
                'status': 'ERROR',
                'regime': 'ERROR'
            }
    
    async def get_regime_summary(self) -> Dict:
        """
        获取 Regime 摘要（前端显示用）
        
        Returns:
            Dict: Regime 摘要
        """
        if self._ibkr is None or not self._ibkr_ready():
            return {
                'status': 'DISCONNECTED',
                'regime_text': '未连接',
                'spy': None,
                'vix': None,
                'indicators': {}
            }
        
        try:
            from .calculators.regime_gate import RegimeGateCalculator
            
            calc = RegimeGateCalculator(self._ibkr)
            # Regime 汇总同样可能包含阻塞 I/O，避免阻塞 async 接口。
            return await asyncio.to_thread(calc.get_regime_summary)
            
        except Exception as e:
            logger.error(f"获取 Regime 摘要失败: {e}")
            return {
                'status': 'ERROR',
                'error': str(e)
            }
    
    async def get_spy_data(self, symbol: str = 'SPY') -> Optional[Dict]:
        """
        获取指数数据（默认 SPY）
        
        Returns:
            Dict: 指数价格和均线数据
        """
        if not self._ibkr_ready():
            return None
        
        try:
            if self._ibkr is not None:
                return await asyncio.to_thread(self._ibkr.get_spy_with_sma, symbol.upper())
            return None
        except Exception as e:
            logger.error(f"获取 {symbol} 数据失败: {e}")
            return None

    async def get_ohlcv_data(
        self,
        symbol: str,
        duration: str = '1 Y',
        bar_size: str = '1 day',
    ) -> Optional[pd.DataFrame]:
        """
        通过 PriceDataProvider 获取 OHLCV 数据。
        """
        if not self._ibkr_ready() or self._price_provider is None:
            return None
        try:
            return await asyncio.to_thread(
                self._price_provider.get_ohlcv,
                symbol=symbol,
                duration=duration,
                bar_size=bar_size,
            )
        except Exception as e:
            logger.error(f"获取 {symbol} OHLCV 失败: {e}")
            return None

    async def get_price_data(
        self,
        symbol: str,
        duration: str = '1 Y',
    ) -> Optional[pd.DataFrame]:
        """
        通过 PriceDataProvider 获取收盘价序列（date + symbol）。
        """
        if not self._ibkr_ready() or self._price_provider is None:
            return None
        try:
            return await asyncio.to_thread(
                self._price_provider.get_close_prices,
                symbol=symbol,
                duration=duration,
            )
        except Exception as e:
            logger.error(f"获取 {symbol} 收盘价失败: {e}")
            return None
    
    async def get_vix(self) -> Optional[float]:
        """
        获取 VIX 指数
        
        Returns:
            float: VIX 值
        """
        if not self._ibkr_ready():
            return None
        
        try:
            if self._price_provider is not None:
                return await asyncio.to_thread(self._price_provider.get_vix)
            if self._ibkr is not None:
                return await asyncio.to_thread(self._ibkr.get_vix)
            return None
        except Exception as e:
            logger.error(f"获取 VIX 失败: {e}")
            return None

    async def calculate_relative_momentum(
        self,
        symbol: str,
        benchmark: str = 'SPY',
        duration: str = '80 D',
    ) -> Optional[Dict[str, Any]]:
        """
        计算 symbol 相对 benchmark 的相对动量。

        使用 PriceDataProvider 拉取收盘价数据，再调用 MomentumCalculator 纯计算。
        """
        if not self._ibkr_ready() or self._price_provider is None:
            return {
                'symbol': symbol,
                'benchmark': benchmark,
                'error': 'IBKR not connected',
            }

        try:
            from .calculators.momentum import MomentumCalculator

            symbol_df = await asyncio.to_thread(
                self._price_provider.get_close_prices,
                symbol=symbol,
                duration=duration,
            )
            benchmark_df = await asyncio.to_thread(
                self._price_provider.get_close_prices,
                symbol=benchmark,
                duration=duration,
            )

            if symbol_df is None or benchmark_df is None:
                return {
                    'symbol': symbol,
                    'benchmark': benchmark,
                    'error': 'price data unavailable',
                }

            result = await asyncio.to_thread(
                MomentumCalculator.calculate_relative_momentum,
                symbol_df,
                benchmark_df,
            )
            if result is None:
                return {
                    'symbol': symbol,
                    'benchmark': benchmark,
                    'error': 'relative momentum calculation failed',
                }

            result['symbol'] = symbol
            result['benchmark'] = benchmark
            return result
        except Exception as e:
            logger.error(f"计算相对动量失败: symbol={symbol}, benchmark={benchmark}, error={e}")
            return {
                'symbol': symbol,
                'benchmark': benchmark,
                'error': str(e),
            }

    async def calculate_momentum_pool_score(
        self,
        symbol: str,
        sector_etf: Optional[str] = None,
        finviz_data: Optional[Dict[str, Any]] = None,
        mc_data: Optional[Dict[str, Any]] = None,
        iv_data: Optional[Dict[str, Any]] = None,
        duration: str = '1 Y',
    ) -> Optional[Dict[str, Any]]:
        """
        动能股池评分官方入口。

        使用 PriceDataProvider 拉取数据，统一由 calculate_momentum_pool_result 计算。
        """
        empty_result = {
            'symbol': symbol,
            'sector_etf': sector_etf,
            'total_score': None,
            'scores': {},
            'metrics': {},
        }

        if not self._ibkr_ready() or self._price_provider is None:
            result = dict(empty_result)
            result['error'] = 'IBKR not connected'
            return result

        try:
            from .calculators.momentum_pool import calculate_momentum_pool_result

            price_df = await asyncio.to_thread(
                self._price_provider.get_ohlcv,
                symbol=symbol,
                duration=duration,
                bar_size='1 day',
            )
            if price_df is None:
                result = dict(empty_result)
                result['error'] = 'symbol price data unavailable'
                return result

            sector_df = None
            if sector_etf:
                sector_df = await asyncio.to_thread(
                    self._price_provider.get_ohlcv,
                    symbol=sector_etf,
                    duration=duration,
                    bar_size='1 day',
                )

            pool_result = await asyncio.to_thread(
                calculate_momentum_pool_result,
                price_df=price_df,
                sector_df=sector_df,
                finviz_data=finviz_data,
                mc_data=mc_data,
                iv_data=iv_data,
            )

            if pool_result is None:
                result = dict(empty_result)
                result['error'] = 'momentum pool calculation failed'
                return result

            payload = asdict(pool_result)
            payload['symbol'] = symbol
            payload['sector_etf'] = sector_etf
            payload['scores'] = payload.get('scores') or {}
            payload['metrics'] = payload.get('metrics') or {}
            return payload
        except Exception as e:
            logger.error(f"计算动能股池评分失败: symbol={symbol}, error={e}")
            result = dict(empty_result)
            result['error'] = str(e)
            return result
    
    # ==================== ETF 评分计算 ====================
    
    async def calculate_etf_score(
        self,
        symbol: str,
        benchmark: str = 'SPY',
        holdings_data: List[Dict] = None,
        mc_data: Dict = None
    ) -> Dict:
        """
        计算单个 ETF 的综合评分
        
        Args:
            symbol: ETF 代码
            benchmark: 基准指数
            holdings_data: Finviz 持仓数据
            mc_data: MarketChameleon 数据
        
        Returns:
            Dict: 评分结果
        """
        if self._ibkr is None or not self._ibkr_ready():
            return {
                'symbol': symbol,
                'error': 'IBKR not connected',
                'total_score': 0
            }
        
        try:
            from .calculators.etf_score import ETFScoreCalculator
            
            calc = ETFScoreCalculator(self._ibkr, self._futu)
            result = calc.calculate_composite_score(
                symbol=symbol,
                benchmark=benchmark,
                holdings_data=holdings_data,
                mc_data=mc_data
            )
            
            return result
            
        except Exception as e:
            logger.error(f"计算 {symbol} 评分失败: {e}")
            return {
                'symbol': symbol,
                'error': str(e),
                'total_score': 0
            }
    
    async def calculate_etf_rankings(
        self,
        symbols: List[str] = None,
        etf_type: str = 'sector',
        benchmark: str = 'SPY',
        holdings_map: Dict[str, List[Dict]] = None,
        mc_map: Dict[str, Dict] = None
    ) -> List[Dict]:
        """
        计算 ETF 排名
        
        Args:
            symbols: ETF 代码列表（如为空则使用默认列表）
            etf_type: 'sector' 或 'industry'
            benchmark: 基准指数
            holdings_map: Finviz 数据映射
            mc_map: MarketChameleon 数据映射
        
        Returns:
            List[Dict]: ETF 评分排名列表
        """
        if symbols is None:
            symbols = self.SECTOR_ETFS if etf_type == 'sector' else self.INDUSTRY_ETFS
        
        if self._ibkr is None or not self._ibkr_ready():
            return [{
                'symbol': s,
                'error': 'IBKR not connected',
                'total_score': 0
            } for s in symbols]
        
        try:
            from .calculators.etf_score import ETFScoreCalculator
            
            calc = ETFScoreCalculator(self._ibkr, self._futu)
            results = calc.batch_calculate_scores(
                symbols=symbols,
                benchmark=benchmark,
                holdings_map=holdings_map or {},
                mc_map=mc_map or {}
            )
            
            # 添加排名
            for i, result in enumerate(results, 1):
                result['rank'] = i
                result['type'] = etf_type
            
            return results
            
        except Exception as e:
            logger.error(f"计算 ETF 排名失败: {e}")
            return []
    
    # ==================== 个股评分计算 ====================
    
    async def calculate_stock_score(
        self,
        symbol: str,
        finviz_data: Dict = None,
        mc_data: Dict = None
    ) -> Dict:
        """
        计算单个股票的综合评分
        
        Args:
            symbol: 股票代码
            finviz_data: Finviz 技术数据
            mc_data: MarketChameleon 期权数据
        
        Returns:
            Dict: 评分结果
        """
        if self._ibkr is None or not self._ibkr_ready():
            return {
                'symbol': symbol,
                'error': 'IBKR not connected',
                'total_score': 0
            }
        
        try:
            from .calculators.stock_score import StockScoreCalculator
            
            calc = StockScoreCalculator(self._ibkr)
            result = calc.calculate_composite_score(
                symbol=symbol,
                finviz_data=finviz_data,
                mc_data=mc_data
            )
            
            return result
            
        except Exception as e:
            logger.error(f"计算 {symbol} 个股评分失败: {e}")
            return {
                'symbol': symbol,
                'error': str(e),
                'total_score': 0
            }
    
    async def score_etf_holdings(
        self,
        etf_symbol: str,
        holdings: List[str],
        finviz_map: Dict[str, Dict] = None,
        mc_map: Dict[str, Dict] = None,
        top_n: int = 20
    ) -> List[Dict]:
        """
        评分 ETF 持仓股票
        
        Args:
            etf_symbol: ETF 代码
            holdings: 持仓股票代码列表
            finviz_map: Finviz 数据映射
            mc_map: MarketChameleon 数据映射
            top_n: 返回 Top N
        
        Returns:
            List[Dict]: 持仓评分排名
        """
        if self._ibkr is None or not self._ibkr_ready():
            return []
        
        try:
            from .calculators.stock_score import StockScoreCalculator
            
            calc = StockScoreCalculator(self._ibkr)
            results = calc.score_etf_holdings(
                symbols=holdings,
                finviz_map=finviz_map or {},
                mc_map=mc_map or {}
            )
            
            return results[:top_n]
            
        except Exception as e:
            logger.error(f"评分 {etf_symbol} 持仓失败: {e}")
            return []
    
    # ==================== 数据导入处理 ====================
    
    async def process_finviz_import(
        self,
        etf_symbol: str,
        data: List[Dict],
        coverage: str = 'top20'
    ) -> Dict:
        """
        处理 Finviz 数据导入
        
        Args:
            etf_symbol: 关联的 ETF 代码
            data: Finviz 原始数据列表
            coverage: 覆盖范围 ('top10', 'top15', 'top20', 'top25', 'top30')
        
        Returns:
            Dict: 处理结果
        """
        try:
            from .parsers.finviz_parser import (
                parse_finviz_json,
                validate_finviz_data,
                calculate_breadth_metrics,
                get_summary_statistics
            )
            from app.models import get_db, ETF
            
            # 解析数据
            parsed = parse_finviz_json(data)
            
            # 验证数据
            validation = validate_finviz_data(parsed)
            
            # 计算广度指标
            breadth = calculate_breadth_metrics(parsed)
            
            # 获取统计摘要
            stats = get_summary_statistics(parsed)
            
            # 更新 ETF 的 coverage_ranges
            db = next(get_db())
            try:
                etf = db.query(ETF).filter(ETF.symbol == etf_symbol.upper()).first()
                if etf:
                    existing_ranges = getattr(etf, 'coverage_ranges', None) or []
                    if coverage not in existing_ranges:
                        existing_ranges.append(coverage)
                        etf.coverage_ranges = existing_ranges
                        db.commit()
                        logger.info(f"已更新 {etf_symbol} 的 coverage_ranges: {existing_ranges}")
            except Exception as e:
                logger.warning(f"更新 coverage_ranges 失败 (可能数据库列不存在): {e}")
                db.rollback()
            finally:
                db.close()
            
            result = {
                'etf_symbol': etf_symbol,
                'coverage': coverage,
                'records_count': len(parsed),
                'validation': validation,
                'breadth_metrics': breadth,
                'statistics': stats,
                'parsed_data': parsed
            }
            
            logger.info(f"✅ Finviz 数据导入成功: {etf_symbol}, {len(parsed)} 条记录")
            
            return result
            
        except Exception as e:
            logger.error(f"Finviz 数据导入失败: {e}")
            return {
                'error': str(e),
                'etf_symbol': etf_symbol,
                'records_count': 0
            }
    
    async def process_mc_import(
        self,
        data: List[Dict]
    ) -> Dict:
        """
        处理 MarketChameleon 数据导入
        
        Args:
            data: MarketChameleon 原始数据列表
        
        Returns:
            Dict: 处理结果
        """
        try:
            from .parsers.mc_parser import process_mc_data, classify_heat_type
            
            # 处理数据
            processed = process_mc_data(data)
            
            # 分类热度类型
            heat_distribution = {}
            for item in processed:
                heat_type = item.get('heat_type', 'NORMAL')
                heat_distribution[heat_type] = heat_distribution.get(heat_type, 0) + 1
            
            result = {
                'records_count': len(processed),
                'heat_distribution': heat_distribution,
                'processed_data': processed
            }
            
            logger.info(f"✅ MarketChameleon 数据导入成功: {len(processed)} 条记录")
            
            return result
            
        except Exception as e:
            logger.error(f"MarketChameleon 数据导入失败: {e}")
            return {
                'error': str(e),
                'records_count': 0
            }
    
    # ==================== IV 数据获取 ====================
    
    async def fetch_iv_data(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        从富途获取 IV 数据
        
        Args:
            symbols: 股票代码列表
        
        Returns:
            Dict[str, Dict]: {symbol: iv_data}
        """
        if not self._futu or not self._broker_status['futu'].is_connected:
            return {}
        
        try:
            result = self._futu.fetch_iv_terms(symbols)
            return {
                symbol: {
                    'iv7': data.iv7,
                    'iv30': data.iv30,
                    'iv60': data.iv60,
                    'iv90': data.iv90,
                    'total_oi': data.total_oi
                }
                for symbol, data in result.items()
            }
        except Exception as e:
            logger.error(f"获取 IV 数据失败: {e}")
            return {}
    
    # ==================== 市场快照 ====================
    
    async def get_market_snapshot(self) -> Dict:
        """
        获取完整市场快照
        
        包含:
        - Regime Gate 状态
        - SPY 数据
        - VIX
        - ETF 排名
        
        Returns:
            Dict: 市场快照
        """
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'broker_status': self.get_broker_status()
        }
        
        # 获取 Regime
        regime = await self.get_regime_summary()
        snapshot['regime'] = regime
        
        # 获取 SPY 数据
        spy_data = await self.get_spy_data()
        snapshot['spy'] = spy_data
        
        # 获取 VIX
        vix = await self.get_vix()
        snapshot['vix'] = vix
        
        # 计算 ETF 排名（仅在 IBKR 连接时）
        if self._ibkr is not None and self._ibkr_ready():
            try:
                sector_rankings = await self.calculate_etf_rankings(
                    etf_type='sector',
                    benchmark='SPY'
                )
                snapshot['sector_etf_rankings'] = sector_rankings[:5]  # Top 5
            except Exception as e:
                logger.warning(f"获取 ETF 排名失败: {e}")
                snapshot['sector_etf_rankings'] = []
        else:
            snapshot['sector_etf_rankings'] = []
        
        return snapshot
    
    # ==================== 数据同步任务 ====================
    
    async def sync_price_data(
        self,
        symbols: List[str],
        duration: str = '1 Y'
    ) -> Dict:
        """
        同步价格数据
        
        Args:
            symbols: 股票代码列表
            duration: 数据时长
        
        Returns:
            Dict: 同步结果
        """
        if self._ibkr is None or not self._ibkr_ready():
            return {
                'error': 'IBKR not connected',
                'synced': []
            }
        
        synced = []
        failed = []
        ok = 0
        fail = 0
        total = len(symbols)
        start_ts = perf_counter()
        log = logger.bind(broker="ibkr", op="sync_price", duration=duration)
        log.info(
            "sync_price",
            stage="start",
            total=total,
            status="start",
        )
        
        for idx, symbol in enumerate(symbols, start=1):
            try:
                df = self._ibkr.get_ohlcv_data(symbol, duration)
                if df is not None and not df.empty:
                    synced.append(symbol)
                    ok += 1
                else:
                    failed.append(symbol)
                    fail += 1
                    logger.warning(
                        "sync_price_item",
                        broker="ibkr",
                        op="sync_price",
                        symbol=symbol,
                        status="empty",
                        reason="no_data",
                    )
            except Exception as e:
                failed.append(symbol)
                fail += 1
                logger.exception(
                    "sync_price_item",
                    broker="ibkr",
                    op="sync_price",
                    symbol=symbol,
                    status="fail",
                    err=str(e),
                )
            if idx % 10 == 0 or idx == total:
                log.info(
                    "sync_price",
                    stage="progress",
                    total=total,
                    done=idx,
                    ok=ok,
                    fail=fail,
                    status="progress",
                )

        elapsed_ms = (perf_counter() - start_ts) * 1000
        status = "ok" if fail == 0 else "partial"
        log.info(
            "sync_price",
            stage="done",
            total=total,
            ok=ok,
            fail=fail,
            status=status,
            elapsed_ms=elapsed_ms,
        )
        
        return {
            'synced': synced,
            'failed': failed,
            'total': len(symbols),
            'success_count': len(synced)
        }
    
    async def sync_iv_data(self, symbols: List[str]) -> Dict:
        """
        同步 IV 数据
        
        Args:
            symbols: 股票代码列表
        
        Returns:
            Dict: 同步结果
        """
        if not self._futu or not self._broker_status['futu'].is_connected:
            return {
                'error': 'Futu not connected',
                'synced': []
            }
        
        total = len(symbols)
        start_ts = perf_counter()
        log = logger.bind(broker="futu", op="sync_iv")
        log.info(
            "sync_iv",
            stage="start",
            total=total,
            status="start",
        )

        try:
            iv_results = self._futu.fetch_iv_terms(symbols)
        except Exception as e:
            elapsed_ms = (perf_counter() - start_ts) * 1000
            log.exception(
                "sync_iv",
                stage="done",
                total=total,
                ok=0,
                fail=total,
                status="fail",
                elapsed_ms=elapsed_ms,
                err=str(e),
            )
            return {
                'error': str(e),
                'synced': []
            }

        ok = 0
        fail = 0
        for idx, symbol in enumerate(symbols, start=1):
            data = iv_results.get(symbol)
            if data and data.is_valid():
                ok += 1
            else:
                fail += 1
                logger.warning(
                    "sync_iv_item",
                    broker="futu",
                    op="sync_iv",
                    symbol=symbol,
                    status="empty",
                    reason="no_iv_data",
                )
            if idx % 10 == 0 or idx == total:
                log.info(
                    "sync_iv",
                    stage="progress",
                    total=total,
                    done=idx,
                    ok=ok,
                    fail=fail,
                    status="progress",
                )

        iv_data = {
            symbol: {
                'iv7': data.iv7,
                'iv30': data.iv30,
                'iv60': data.iv60,
                'iv90': data.iv90,
                'total_oi': data.total_oi
            }
            for symbol, data in iv_results.items()
        }

        elapsed_ms = (perf_counter() - start_ts) * 1000
        status = "ok" if fail == 0 else "partial"
        log.info(
            "sync_iv",
            stage="done",
            total=total,
            ok=ok,
            fail=fail,
            status=status,
            elapsed_ms=elapsed_ms,
        )

        return {
            'synced': list(iv_data.keys()),
            'data': iv_data,
            'success_count': len(iv_data)
        }
    
    # ==================== 缓存管理 ====================
    
    def _set_cache(
        self, 
        key: str, 
        value: Any, 
        ttl_seconds: int = 300
    ):
        """设置缓存"""
        from datetime import timedelta
        
        self._cache[key] = value
        self._cache_expiry[key] = datetime.now() + timedelta(seconds=ttl_seconds)
    
    def _get_cache(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key not in self._cache:
            return None
        
        if datetime.now() > self._cache_expiry.get(key, datetime.min):
            # 缓存已过期
            del self._cache[key]
            del self._cache_expiry[key]
            return None
        
        return self._cache[key]
    
    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()
        self._cache_expiry.clear()
        logger.info("缓存已清除")


# ==================== 全局单例 ====================

_orchestrator_instance: Optional[DataOrchestrator] = None


def get_orchestrator() -> DataOrchestrator:
    """
    获取全局 DataOrchestrator 单例
    
    Returns:
        DataOrchestrator 实例
    """
    global _orchestrator_instance
    
    if _orchestrator_instance is None:
        _orchestrator_instance = DataOrchestrator()
    
    return _orchestrator_instance


def reset_orchestrator():
    """重置全局 DataOrchestrator（用于测试）"""
    global _orchestrator_instance
    
    if _orchestrator_instance:
        # 断开所有连接
        _orchestrator_instance.disconnect_ibkr()
        _orchestrator_instance.disconnect_futu()
    
    _orchestrator_instance = None
