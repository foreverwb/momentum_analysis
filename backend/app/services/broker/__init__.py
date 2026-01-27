"""
Broker Connectors Package
整合 IBKR 和 Futu API 连接器

使用示例:
```python
from app.services.broker import IBKRConnector, FutuConnector, is_ibkr_available, is_futu_available

# 检查依赖是否可用
if is_ibkr_available():
    ibkr = IBKRConnector()
    if ibkr.connect():
        # 使用 IBKR
        pass

if is_futu_available():
    futu = FutuConnector()
    if futu.connect():
        # 使用 Futu
        pass
```
"""

from .base import BrokerConnector
from .ibkr_connector import IBKRConnector, is_ibkr_available, create_ibkr_connector
from .futu_connector import FutuConnector, is_futu_available, create_futu_connector

__all__ = [
    'BrokerConnector',
    'IBKRConnector',
    'FutuConnector',
    'is_ibkr_available',
    'is_futu_available',
    'create_ibkr_connector',
    'create_futu_connector',
]