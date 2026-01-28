"""
富途 API 连接器
整合已有实现：futu_iv.py, futu_oi.py

提供功能：
- 连接管理（connect/disconnect）
- IV 期限结构获取 (IV7/IV30/IV60/IV90)
- OI 数据和 ΔOI 计算
- 期权链数据获取
"""

from futu import OpenQuoteContext, OptionType, RET_OK
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any, Iterable
from datetime import datetime, timedelta
from collections import defaultdict, deque
import os
import time
import json
import threading
import structlog

from .base import BrokerConnector
from app.core.timing import timed

logger = structlog.get_logger(__name__)


@dataclass
class IVTermResult:
    """IV 期限结构结果"""
    iv7: Optional[float] = None
    iv30: Optional[float] = None
    iv60: Optional[float] = None
    iv90: Optional[float] = None
    total_oi: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def is_valid(self) -> bool:
        """检查是否有有效数据"""
        return any([
            self.iv7 is not None,
            self.iv30 is not None,
            self.iv60 is not None,
            self.iv90 is not None
        ])


@dataclass
class OptionContract:
    """期权合约信息"""
    code: str
    option_type: OptionType


class RateLimiter:
    """
    API 速率限制器
    
    用于控制 API 请求频率，避免触发富途 API 的频率限制
    """
    
    def __init__(self, max_calls: int, period_seconds: int):
        """
        Args:
            max_calls: 周期内最大调用次数
            period_seconds: 周期长度（秒）
        """
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.calls: deque = deque()
    
    def acquire(self) -> None:
        """获取调用许可，如果超过限制则等待"""
        now = time.time()
        
        # 清理过期的调用记录
        while self.calls and now - self.calls[0] >= self.period_seconds:
            self.calls.popleft()
        
        # 如果达到限制，等待
        if len(self.calls) >= self.max_calls:
            sleep_seconds = self.period_seconds - (now - self.calls[0]) + 0.01
            if sleep_seconds > 0:
                logger.debug(f"Rate limit reached, sleeping for {sleep_seconds:.2f}s")
                time.sleep(sleep_seconds)
        
        self.calls.append(time.time())


class FutuConnector(BrokerConnector):
    """
    富途 API 连接器
    
    整合自:
    - futu_iv.py: IV 期限结构计算
    - futu_oi.py: OI 缓存和 ΔOI 计算
    
    使用示例:
    ```python
    futu = FutuConnector()
    if futu.connect():
        # 获取 IV 数据
        iv_results = futu.fetch_iv_terms(['AAPL', 'NVDA', 'MSFT'])
        
        # 计算 ΔOI
        oi_map = {'AAPL': 100000, 'NVDA': 200000}
        delta_results = futu.batch_compute_delta_oi(oi_map)
        
        futu.disconnect()
    ```
    """
    
    OI_CACHE_FILE = "oi_cache.json"
    CACHE_LOCK = threading.Lock()
    
    def __init__(
        self, 
        host: str = '127.0.0.1', 
        port: int = 11111, 
        market: str = 'US'
    ):
        """
        初始化 Futu 连接器
        
        Args:
            host: FutuOpenD 主机地址
            port: FutuOpenD 端口号 (默认 11111)
            market: 市场代码 ('US', 'HK', 'CN')
        """
        self.host = os.getenv("FUTU_HOST", host)
        self.port = int(os.getenv("FUTU_PORT", str(port)))
        self.market = os.getenv("FUTU_MARKET", market)
        
        self.quote_ctx: Optional[OpenQuoteContext] = None
        self._connected = False
        
        # 速率限制器
        # get_option_chain: 10次/30秒
        # get_market_snapshot: 60次/30秒
        self.chain_limiter = RateLimiter(max_calls=10, period_seconds=30)
        self.snapshot_limiter = RateLimiter(max_calls=60, period_seconds=30)
    
    # ==================== 连接管理 ====================
    
    def connect(self) -> bool:
        """
        建立 Futu 连接
        
        Returns:
            bool: 连接成功返回 True
        """
        try:
            self.quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
            self._connected = True
            logger.info(f"✅ 已连接到 Futu: {self.host}:{self.port} (市场: {self.market})")
            return True
        except Exception as e:
            logger.error(f"❌ Futu 连接失败: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> None:
        """断开 Futu 连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
            self.quote_ctx = None
            self._connected = False
            logger.info("已断开 Futu 连接")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._connected and self.quote_ctx is not None
    
    def __enter__(self):
        """Context manager 支持"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 支持"""
        self.disconnect()
    
    # ==================== 基础方法（实现 BrokerConnector 接口）====================
    
    def get_price_data(self, symbol: str, duration: str = '1 Y') -> Optional[Any]:
        """
        获取历史价格数据
        
        注意：Futu 主要用于期权数据，价格数据建议使用 IBKR
        """
        logger.warning("Futu connector 主要用于期权数据，建议使用 IBKR 获取价格数据")
        return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格
        
        注意：Futu 主要用于期权数据
        """
        if not self.is_connected():
            return None
        
        try:
            code = self._format_code(symbol)
            ret, data = self.quote_ctx.get_market_snapshot([code])
            
            if ret == RET_OK and hasattr(data, 'to_dict'):
                records = data.to_dict('records')
                if records:
                    return float(records[0].get('last_price', 0))
            return None
        except Exception as e:
            logger.error(f"获取 {symbol} 价格失败: {e}")
            return None
    
    # ==================== IV 期限结构 ====================
    
    def fetch_iv_terms(
        self, 
        symbols: Iterable[str], 
        max_days: int = 120,
        max_retries: int = 2
    ) -> Dict[str, IVTermResult]:
        """
        批量获取 IV7/IV30/IV60/IV90
        
        复用自: futu_iv.py -> fetch_iv_terms()
        
        Args:
            symbols: 股票代码列表
            max_days: 最大到期天数
            max_retries: 失败重试次数
        
        Returns:
            {symbol: IVTermResult} 字典
        """
        if not self.is_connected():
            self.connect()
        
        results: Dict[str, IVTermResult] = {}
        symbols_list = list(symbols)
        total = len(symbols_list)
        start_ts = time.time()
        
        for idx, symbol in enumerate(symbols_list, start=1):
            try:
                result = self._fetch_symbol_iv_terms_with_retry(
                    symbol=symbol,
                    max_days=max_days,
                    max_retries=max_retries
                )
                results[symbol] = result
                
                progress = f"[{idx}/{total}]"
                logger.info(
                    f"✓ {progress} {symbol}: "
                    f"IV7={self._fmt_iv(result.iv7)} "
                    f"IV30={self._fmt_iv(result.iv30)} "
                    f"IV60={self._fmt_iv(result.iv60)} "
                    f"IV90={self._fmt_iv(result.iv90)}"
                )
            except Exception as exc:
                logger.error(f"✗ {symbol}: IV 计算失败: {exc}")
                results[symbol] = IVTermResult()
        
        elapsed = time.time() - start_ts
        success = sum(1 for v in results.values() if v.is_valid())
        logger.info(f"✓ {success}/{total} successful in {elapsed/60:.1f}m")
        
        return results
    
    def _fetch_symbol_iv_terms_with_retry(
        self,
        symbol: str,
        max_days: int,
        max_retries: int
    ) -> IVTermResult:
        """带重试的单标的 IV 获取"""
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                return self._fetch_symbol_iv_terms(symbol, max_days)
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    sleep_seconds = min(30.0, 2 ** attempt)
                    logger.warning(f"{symbol}: 重试 ({attempt + 1}/{max_retries}), 等待 {sleep_seconds}s")
                    time.sleep(sleep_seconds)
                else:
                    raise
        
        raise RuntimeError(f"{symbol}: IV fetch failed: {last_error}")
    
    def _fetch_symbol_iv_terms(self, symbol: str, max_days: int = 120) -> IVTermResult:
        """获取单个标的的 IV 期限结构"""
        with timed(
            logger,
            "futu_iv_fetch",
            broker="futu",
            op="iv_terms",
            symbol=symbol,
        ) as details:
            code = self._format_code(symbol)
            today = datetime.now().date()
            end_date = today + timedelta(days=max_days)

            # 收集到期日和期权合约
            expirations = self._collect_expirations(code, today, end_date)

            if not expirations:
                details["status"] = "empty"
                details["reason"] = "no_expirations"
                details["expirations"] = 0
                return IVTermResult()

            contracts_count = sum(len(contracts) for contracts in expirations.values())
            details["expirations"] = len(expirations)
            details["contracts"] = contracts_count

            # 获取快照数据
            snapshot_map = self._fetch_snapshot_map(expirations)
            details["snapshots"] = len(snapshot_map)

            # 构建 DTE 点
            dte_points = self._build_dte_points(today, expirations, snapshot_map)
            details["points"] = len(dte_points)

            # 计算总 OI
            total_oi = self._sum_open_interest(snapshot_map)

            # 插值计算各期限 IV
            iv7 = self._interpolate_iv(dte_points, 7)
            iv30 = self._interpolate_iv(dte_points, 30)
            iv60 = self._interpolate_iv(dte_points, 60)
            iv90 = self._interpolate_iv(dte_points, 90)

            details["iv7"] = iv7
            details["iv30"] = iv30
            details["iv60"] = iv60
            details["iv90"] = iv90
            details["total_oi"] = total_oi

            if not any([iv7, iv30, iv60, iv90]):
                details["status"] = "empty"
                details["reason"] = "no_iv_points"

            return IVTermResult(
                iv7=iv7,
                iv30=iv30,
                iv60=iv60,
                iv90=iv90,
                total_oi=total_oi,
            )
    
    def _collect_expirations(
        self, 
        code: str, 
        start_date: datetime.date, 
        end_date: datetime.date
    ) -> Dict[str, List[OptionContract]]:
        """收集期权到期日"""
        expirations: Dict[str, List[OptionContract]] = defaultdict(list)
        window_days = 30
        window_start = start_date
        
        while window_start <= end_date:
            window_end = min(window_start + timedelta(days=window_days), end_date)
            
            for option_type in [OptionType.CALL, OptionType.PUT]:
                self.chain_limiter.acquire()
                
                try:
                    ret, data = self._get_option_chain_safe(
                        code=code,
                        start_date=window_start.strftime("%Y-%m-%d"),
                        end_date=window_end.strftime("%Y-%m-%d"),
                        option_type=option_type
                    )
                    
                    if ret == RET_OK:
                        records = self._dataframe_to_records(data)
                        for record in records:
                            expiry = self._get_expiry_date(record)
                            option_code = self._get_option_code(record)
                            if expiry and option_code:
                                expirations[expiry].append(
                                    OptionContract(option_code, option_type)
                                )
                    else:
                        logger.warning(f"⚠ get_option_chain 失败: {data}")
                        
                except Exception as e:
                    logger.warning(f"⚠ get_option_chain 异常: {e}")
            
            window_start = window_end + timedelta(days=1)
        
        return expirations
    
    def _get_option_chain_safe(
        self,
        code: str,
        start_date: str,
        end_date: str,
        option_type: OptionType
    ) -> Tuple[int, Any]:
        """安全调用 get_option_chain（兼容不同版本参数）"""
        variants = [
            {"start": start_date, "end": end_date},
            {"begin_time": start_date, "end_time": end_date},
            {"start_time": start_date, "end_time": end_date},
            {"start_date": start_date, "end_date": end_date},
        ]
        
        for variant in variants:
            try:
                kwargs = {"option_type": option_type, **variant}
                ret, data = self.quote_ctx.get_option_chain(code, **kwargs)
                return ret, data
            except TypeError:
                continue
        
        # 尝试无日期参数
        try:
            ret, data = self.quote_ctx.get_option_chain(code, option_type=option_type)
            return ret, data
        except Exception as e:
            return -1, str(e)
    
    def _fetch_snapshot_map(
        self, 
        expirations: Dict[str, List[OptionContract]]
    ) -> Dict[str, Dict]:
        """获取期权快照数据"""
        codes = []
        for contracts in expirations.values():
            codes.extend(contract.code for contract in contracts)
        
        snapshot_map: Dict[str, Dict] = {}
        chunk_size = 400  # Futu API 限制
        
        for i in range(0, len(codes), chunk_size):
            batch = codes[i:i + chunk_size]
            self.snapshot_limiter.acquire()
            
            ret, data = self.quote_ctx.get_market_snapshot(batch)
            
            if ret == RET_OK:
                records = self._dataframe_to_records(data)
                for rec in records:
                    code = rec.get('code') or rec.get('option_code')
                    if code:
                        snapshot_map[code] = rec
            else:
                logger.warning(f"⚠ 快照获取失败: {data}")
        
        return snapshot_map
    
    def _build_dte_points(
        self,
        today: datetime.date,
        expirations: Dict[str, List[OptionContract]],
        snapshot_map: Dict[str, Dict]
    ) -> List[Tuple[int, float]]:
        """构建 DTE -> IV 点"""
        points = []
        
        for expiry, contracts in expirations.items():
            exp_date = self._parse_date(expiry)
            if not exp_date:
                continue
            
            dte = (exp_date - today).days
            if dte <= 0:
                continue
            
            # 选择 ATM Call 的 IV (delta 最接近 0.5)
            chosen_iv = self._pick_atm_iv(contracts, snapshot_map)
            if chosen_iv is not None:
                points.append((dte, chosen_iv))
        
        points.sort(key=lambda x: x[0])
        return points
    
    def _pick_atm_iv(
        self, 
        contracts: List[OptionContract], 
        snapshot_map: Dict[str, Dict]
    ) -> Optional[float]:
        """选择 ATM (delta ≈ 0.5) 的 IV"""
        best_iv = None
        best_diff = None
        
        for contract in contracts:
            if contract.option_type != OptionType.CALL:
                continue
            
            snapshot = snapshot_map.get(contract.code)
            if not snapshot:
                continue
            
            delta = self._get_snapshot_value(snapshot, ['option_delta', 'delta'])
            iv = self._get_snapshot_value(snapshot, ['option_implied_volatility', 'implied_volatility', 'iv'])
            
            if delta is None or iv is None:
                continue
            
            diff = abs(delta - 0.5)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_iv = self._normalize_iv(iv)
        
        return best_iv
    
    def _sum_open_interest(self, snapshot_map: Dict[str, Dict]) -> Optional[int]:
        """计算总 OI"""
        total = 0
        found = False
        
        for snapshot in snapshot_map.values():
            oi = self._get_snapshot_value(snapshot, ['option_open_interest', 'open_interest', 'oi'])
            if oi is not None:
                found = True
                total += int(oi)
        
        return total if found else None
    
    def _interpolate_iv(
        self, 
        points: List[Tuple[int, float]], 
        target_day: int
    ) -> Optional[float]:
        """插值计算目标天数的 IV (使用方差插值)"""
        if not points:
            return None
        if len(points) == 1:
            return points[0][1]
        
        lower = None
        upper = None
        
        for dte, iv in points:
            if dte == target_day:
                return iv
            if dte < target_day:
                lower = (dte, iv)
            if dte > target_day and upper is None:
                upper = (dte, iv)
                break
        
        if lower and upper:
            # 方差插值
            d1, iv1 = lower
            d2, iv2 = upper
            if d2 == d1:
                return iv1
            var1 = (iv1 / 100.0) ** 2
            var2 = (iv2 / 100.0) ** 2
            weight = (target_day - d1) / (d2 - d1)
            var_t = var1 + (var2 - var1) * weight
            return (var_t ** 0.5) * 100.0
        
        if lower:
            return lower[1]
        if upper:
            return upper[1]
        return None
    
    # ==================== OI 与 ΔOI ====================
    
    def batch_compute_delta_oi(
        self, 
        symbol_to_oi: Dict[str, Optional[int]]
    ) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        """
        批量计算 ΔOI_1D（基于 Futu OI）
        
        复用自: futu_oi.py -> batch_compute_delta_oi()
        
        Args:
            symbol_to_oi: {symbol: current_oi} 字典
        
        Returns:
            {symbol: (current_oi, delta_oi_1d)} 字典
        """
        cache = self._load_oi_cache()
        today = datetime.now().strftime('%Y-%m-%d')
        cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        results: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        
        for symbol, current_oi in symbol_to_oi.items():
            if current_oi is None:
                results[symbol] = (None, None)
                continue
            
            symbol_cache = cache.get(symbol, {})
            yesterday_oi = None
            
            # 查找最近的历史 OI (最多向前查7天)
            for days_ago in range(1, 8):
                past_date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
                if past_date in symbol_cache:
                    yesterday_oi = symbol_cache[past_date]
                    break
            
            # 计算 ΔOI
            delta_oi = current_oi - yesterday_oi if yesterday_oi is not None else None
            
            # 更新缓存
            if symbol not in cache:
                cache[symbol] = {}
            cache[symbol][today] = current_oi
            
            # 清理过期缓存
            cache[symbol] = {
                date: oi for date, oi in cache[symbol].items()
                if date >= cutoff
            }
            
            results[symbol] = (current_oi, delta_oi)
        
        self._save_oi_cache(cache)
        return results
    
    def _load_oi_cache(self) -> dict:
        """加载 OI 缓存（线程安全）"""
        with self.CACHE_LOCK:
            if not os.path.exists(self.OI_CACHE_FILE):
                return {}
            try:
                with open(self.OI_CACHE_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
    
    def _save_oi_cache(self, cache: dict) -> None:
        """保存 OI 缓存（线程安全）"""
        with self.CACHE_LOCK:
            with open(self.OI_CACHE_FILE, 'w') as f:
                json.dump(cache, f, indent=2)
    
    # ==================== 辅助方法 ====================
    
    def _format_code(self, symbol: str) -> str:
        """格式化代码（添加市场前缀）"""
        if "." in symbol:
            return symbol
        return f"{self.market}.{symbol.upper()}"
    
    @staticmethod
    def _dataframe_to_records(data) -> List[Dict]:
        """将 DataFrame 转换为记录列表"""
        if hasattr(data, "to_dict"):
            return data.to_dict("records")
        if isinstance(data, list):
            return data
        return []
    
    @staticmethod
    def _get_expiry_date(record: Dict) -> Optional[str]:
        """从记录中提取到期日"""
        for key in ("expiry_date", "expire_date", "expiration_date", "expiry", "strike_time", "strike_date"):
            value = record.get(key)
            if value:
                return str(value).split(" ")[0]
        return None
    
    @staticmethod
    def _get_option_code(record: Dict) -> Optional[str]:
        """从记录中提取期权代码"""
        for key in ("code", "option_code", "contract_code", "security_code"):
            value = record.get(key)
            if value:
                return str(value)
        return None
    
    @staticmethod
    def _get_snapshot_value(snapshot: Dict, keys: List[str]) -> Optional[float]:
        """从快照中获取值（尝试多个可能的键）"""
        for key in keys:
            if key in snapshot and snapshot[key] is not None:
                try:
                    return float(snapshot[key])
                except (ValueError, TypeError):
                    return None
        return None
    
    @staticmethod
    def _normalize_iv(iv_value: float) -> float:
        """标准化 IV 值（确保是百分比形式）"""
        iv = float(iv_value)
        if iv <= 1.5:  # 可能是小数形式
            return iv * 100.0
        return iv
    
    @staticmethod
    def _parse_date(value: str) -> Optional[datetime.date]:
        """解析日期字符串"""
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                continue
        return None
    
    @staticmethod
    def _fmt_iv(value: Optional[float]) -> str:
        """格式化 IV 值用于显示"""
        if value is None:
            return "N/A"
        return f"{value:.2f}%"


def estimate_iv_fetch_time(
    symbol_count: int,
    windows_per_symbol: int = 4,
    option_type_count: int = 2
) -> float:
    """
    估算 IV 获取耗时
    
    Args:
        symbol_count: 标的数量
        windows_per_symbol: 每个标的的时间窗口数
        option_type_count: 期权类型数 (Call + Put = 2)
    
    Returns:
        预估耗时（秒）
    """
    option_chain_calls = symbol_count * windows_per_symbol * option_type_count
    snapshot_calls = symbol_count  # 近似按每个标的 1 次快照
    
    chain_batches = (option_chain_calls + 9) // 10
    snapshot_batches = (snapshot_calls + 59) // 60
    
    return max(chain_batches, snapshot_batches) * 30.0


# 便捷函数
def create_futu_connector(
    host: str = '127.0.0.1',
    port: int = 11111,
    market: str = 'US'
) -> FutuConnector:
    """
    创建 Futu 连接器的工厂函数
    
    Args:
        host: FutuOpenD 主机
        port: 端口号
        market: 市场代码
    
    Returns:
        FutuConnector 实例
    """
    return FutuConnector(host=host, port=port, market=market)
