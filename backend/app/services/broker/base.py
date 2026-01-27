"""
Broker Connector 抽象基类
定义所有 Broker 连接器需要实现的接口
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
import pandas as pd


class BrokerConnector(ABC):
    """
    Broker 连接器抽象基类
    
    所有具体的 Broker 连接器 (IBKR, Futu 等) 都需要继承此类
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        建立与 Broker 的连接
        
        Returns:
            bool: 连接成功返回 True, 否则返回 False
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开与 Broker 的连接"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """
        检查当前连接状态
        
        Returns:
            bool: 已连接返回 True, 否则返回 False
        """
        pass
    
    @abstractmethod
    def get_price_data(self, symbol: str, duration: str = '1 Y') -> Optional[pd.DataFrame]:
        """
        获取历史价格数据
        
        Args:
            symbol: 股票代码
            duration: 数据长度 (如 '80 D', '1 Y')
        
        Returns:
            DataFrame with price data, or None if failed
        """
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格
        
        Args:
            symbol: 股票代码
        
        Returns:
            当前价格，获取失败返回 None
        """
        pass


class PriceDataMixin:
    """
    价格数据处理的 Mixin 类
    提供通用的价格数据处理方法
    """
    
    @staticmethod
    def validate_ohlcv(df: pd.DataFrame) -> bool:
        """验证 OHLCV 数据的完整性"""
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        return all(col in df.columns for col in required_columns)
    
    @staticmethod
    def fill_missing_dates(df: pd.DataFrame, method: str = 'ffill') -> pd.DataFrame:
        """填充缺失的交易日"""
        if df.empty:
            return df
        
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df = df.resample('D').asfreq()
        df = df.fillna(method=method)
        df = df.reset_index()
        return df