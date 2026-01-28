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
from time import perf_counter

import structlog

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
        self._futu = None
        self._broker_status: Dict[str, BrokerConnectionStatus] = {}
        self._tasks: Dict[str, OrchestratorTask] = {}
        self._cache: Dict[str, Any] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        
        # 初始化状态
        self._broker_status['ibkr'] = BrokerConnectionStatus(
            broker='ibkr',
            is_connected=False
        )
        self._broker_status['futu'] = BrokerConnectionStatus(
            broker='futu', 
            is_connected=False
        )
        
        logger.info("DataOrchestrator 初始化完成")
    
    # ==================== Broker 连接管理 ====================
    
    async def connect_ibkr(
        self, 
        host: str = '127.0.0.1', 
        port: int = 4002, 
        client_id: int = 1
    ) -> bool:
        """
        连接 IBKR
        
        Args:
            host: IBKR 主机地址
            port: 端口号
            client_id: 客户端 ID
        
        Returns:
            bool: 是否连接成功
        """
        try:
            from .broker.ibkr_connector import IBKRConnector
            
            self._ibkr = IBKRConnector(host=host, port=port, client_id=client_id)
            success = self._ibkr.connect()
            
            self._broker_status['ibkr'] = BrokerConnectionStatus(
                broker='ibkr',
                is_connected=success,
                last_connected=datetime.now() if success else None,
                last_error=None if success else "Connection failed",
                config={'host': host, 'port': port, 'client_id': client_id}
            )
            
            if success:
                logger.info(f"✅ IBKR 连接成功: {host}:{port}")
            else:
                logger.error(f"❌ IBKR 连接失败: {host}:{port}")
            
            return success
            
        except Exception as e:
            logger.error(f"IBKR 连接异常: {e}")
            self._broker_status['ibkr'] = BrokerConnectionStatus(
                broker='ibkr',
                is_connected=False,
                last_error=str(e)
            )
            return False
    
    async def connect_futu(
        self,
        host: str = '127.0.0.1',
        port: int = 11111
    ) -> bool:
        """
        连接富途 OpenD
        
        Args:
            host: OpenD 主机地址
            port: 端口号
        
        Returns:
            bool: 是否连接成功
        """
        try:
            from .broker.futu_connector import FutuConnector
            
            self._futu = FutuConnector(host=host, port=port)
            success = self._futu.connect()
            
            self._broker_status['futu'] = BrokerConnectionStatus(
                broker='futu',
                is_connected=success,
                last_connected=datetime.now() if success else None,
                last_error=None if success else "Connection failed",
                config={'host': host, 'port': port}
            )
            
            if success:
                logger.info(f"✅ Futu 连接成功: {host}:{port}")
            else:
                logger.error(f"❌ Futu 连接失败: {host}:{port}")
            
            return success
            
        except Exception as e:
            logger.error(f"Futu 连接异常: {e}")
            self._broker_status['futu'] = BrokerConnectionStatus(
                broker='futu',
                is_connected=False,
                last_error=str(e)
            )
            return False
    
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
        if self._ibkr:
            self._ibkr.disconnect()
            self._broker_status['ibkr'].is_connected = False
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
        return {
            broker: status.to_dict() 
            for broker, status in self._broker_status.items()
        }
    
    # ==================== 市场数据获取 ====================
    
    async def get_market_regime(self) -> Dict:
        """
        获取市场环境 (Regime Gate)
        
        Returns:
            Dict: Regime 信息
        """
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
            return {
                'error': 'IBKR not connected',
                'status': 'UNKNOWN',
                'regime': 'UNKNOWN',
                'fire_power': '未知'
            }
        
        try:
            from .calculators.regime_gate import RegimeGateCalculator
            
            calc = RegimeGateCalculator(self._ibkr)
            result = calc.calculate_regime()
            
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
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
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
            return calc.get_regime_summary()
            
        except Exception as e:
            logger.error(f"获取 Regime 摘要失败: {e}")
            return {
                'status': 'ERROR',
                'error': str(e)
            }
    
    async def get_spy_data(self) -> Optional[Dict]:
        """
        获取 SPY 数据
        
        Returns:
            Dict: SPY 价格和均线数据
        """
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
            return None
        
        try:
            result = self._ibkr.get_spy_with_sma()
            return result
        except Exception as e:
            logger.error(f"获取 SPY 数据失败: {e}")
            return None
    
    async def get_vix(self) -> Optional[float]:
        """
        获取 VIX 指数
        
        Returns:
            float: VIX 值
        """
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
            return None
        
        try:
            return self._ibkr.get_vix()
        except Exception as e:
            logger.error(f"获取 VIX 失败: {e}")
            return None
    
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
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
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
        
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
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
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
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
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
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
            
            # 解析数据
            parsed = parse_finviz_json(data)
            
            # 验证数据
            validation = validate_finviz_data(parsed)
            
            # 计算广度指标
            breadth = calculate_breadth_metrics(parsed)
            
            # 获取统计摘要
            stats = get_summary_statistics(parsed)
            
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
        if self._broker_status['ibkr'].is_connected:
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
        if not self._ibkr or not self._broker_status['ibkr'].is_connected:
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
