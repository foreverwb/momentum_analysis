"""
Broker 管理 API
Broker Management API Endpoints

提供:
- Broker 连接状态查询
- 连接/断开控制
- 配置管理
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, Optional, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/broker", tags=["Broker"])


# ==================== Pydantic Models ====================

class BrokerStatusResponse(BaseModel):
    """Broker 状态响应"""
    broker: str
    is_connected: bool
    last_connected: Optional[str] = None
    last_error: Optional[str] = None
    config: Dict[str, Any] = {}


class AllBrokerStatusResponse(BaseModel):
    """所有 Broker 状态响应"""
    ibkr: BrokerStatusResponse
    futu: BrokerStatusResponse


class ConnectRequest(BaseModel):
    """连接请求"""
    host: str = Field("127.0.0.1", description="主机地址")
    port: int = Field(..., description="端口号")
    client_id: Optional[int] = Field(None, description="客户端 ID（仅 IBKR）")


class ConnectResponse(BaseModel):
    """连接响应"""
    status: str
    broker: str
    is_connected: bool
    message: str


class DisconnectResponse(BaseModel):
    """断开连接响应"""
    status: str
    broker: str
    message: str


class IBKRConfigRequest(BaseModel):
    """IBKR 配置请求"""
    host: str = Field("127.0.0.1", description="TWS/Gateway 主机地址")
    port: int = Field(4002, description="端口号 (TWS: 7497, Gateway: 4002)")
    client_id: int = Field(1, description="客户端 ID")
    timeout: int = Field(30, description="连接超时（秒）")


class FutuConfigRequest(BaseModel):
    """Futu 配置请求"""
    host: str = Field("127.0.0.1", description="OpenD 主机地址")
    port: int = Field(11111, description="端口号")
    rate_limit: int = Field(10, description="速率限制（请求/分钟）")


# ==================== API Endpoints ====================

@router.get("/status", response_model=AllBrokerStatusResponse)
async def get_all_broker_status():
    """
    获取所有 Broker 连接状态
    
    返回 IBKR 和 Futu 的连接状态
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        status = orchestrator.get_broker_status()
        
        return {
            'ibkr': status.get('ibkr', {
                'broker': 'ibkr',
                'is_connected': False
            }),
            'futu': status.get('futu', {
                'broker': 'futu',
                'is_connected': False
            })
        }
        
    except Exception as e:
        logger.error(f"获取 Broker 状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{broker}", response_model=BrokerStatusResponse)
async def get_broker_status(broker: str):
    """
    获取指定 Broker 连接状态
    
    参数:
    - broker: ibkr 或 futu
    """
    if broker not in ['ibkr', 'futu']:
        raise HTTPException(
            status_code=400, 
            detail="Invalid broker. Use 'ibkr' or 'futu'"
        )
    
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        status = orchestrator.get_broker_status()
        
        broker_status = status.get(broker)
        if not broker_status:
            return {
                'broker': broker,
                'is_connected': False
            }
        
        return broker_status
        
    except Exception as e:
        logger.error(f"获取 {broker} 状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ibkr/connect", response_model=ConnectResponse)
async def connect_ibkr(request: Optional[IBKRConfigRequest] = None):
    """
    连接 IBKR TWS/Gateway
    
    默认配置:
    - host: 127.0.0.1
    - port: 4002 (Gateway) 或 7497 (TWS)
    - client_id: 1
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 使用默认值或请求参数
        host = request.host if request else '127.0.0.1'
        port = request.port if request else 4002
        client_id = request.client_id if request else 1
        
        success = await orchestrator.connect_ibkr(
            host=host,
            port=port,
            client_id=client_id
        )
        
        if success:
            return {
                'status': 'success',
                'broker': 'ibkr',
                'is_connected': True,
                'message': f'Successfully connected to IBKR at {host}:{port}'
            }
        else:
            return {
                'status': 'failed',
                'broker': 'ibkr',
                'is_connected': False,
                'message': f'Failed to connect to IBKR at {host}:{port}'
            }
        
    except Exception as e:
        logger.error(f"IBKR 连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ibkr/disconnect", response_model=DisconnectResponse)
async def disconnect_ibkr():
    """
    断开 IBKR 连接
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        orchestrator.disconnect_ibkr()
        
        return {
            'status': 'success',
            'broker': 'ibkr',
            'message': 'IBKR disconnected'
        }
        
    except Exception as e:
        logger.error(f"IBKR 断开失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/futu/connect", response_model=ConnectResponse)
async def connect_futu(request: Optional[FutuConfigRequest] = None):
    """
    连接 Futu OpenD
    
    默认配置:
    - host: 127.0.0.1
    - port: 11111
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        host = request.host if request else '127.0.0.1'
        port = request.port if request else 11111
        
        success = await orchestrator.connect_futu(
            host=host,
            port=port
        )
        
        if success:
            return {
                'status': 'success',
                'broker': 'futu',
                'is_connected': True,
                'message': f'Successfully connected to Futu OpenD at {host}:{port}'
            }
        else:
            return {
                'status': 'failed',
                'broker': 'futu',
                'is_connected': False,
                'message': f'Failed to connect to Futu OpenD at {host}:{port}'
            }
        
    except Exception as e:
        logger.error(f"Futu 连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/futu/disconnect", response_model=DisconnectResponse)
async def disconnect_futu():
    """
    断开 Futu 连接
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        orchestrator.disconnect_futu()
        
        return {
            'status': 'success',
            'broker': 'futu',
            'message': 'Futu disconnected'
        }
        
    except Exception as e:
        logger.error(f"Futu 断开失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect-all")
async def connect_all_brokers():
    """
    连接所有 Broker
    
    尝试同时连接 IBKR 和 Futu
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        results = await orchestrator.connect_brokers()
        
        return {
            'status': 'success',
            'results': {
                'ibkr': {
                    'connected': results.get('ibkr', False),
                    'message': 'Connected' if results.get('ibkr') else 'Connection failed'
                },
                'futu': {
                    'connected': results.get('futu', False),
                    'message': 'Connected' if results.get('futu') else 'Connection failed'
                }
            }
        }
        
    except Exception as e:
        logger.error(f"连接所有 Broker 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect-all")
async def disconnect_all_brokers():
    """
    断开所有 Broker 连接
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        await orchestrator.disconnect_all()
        
        return {
            'status': 'success',
            'message': 'All brokers disconnected'
        }
        
    except Exception as e:
        logger.error(f"断开所有 Broker 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ibkr/test")
async def test_ibkr_connection():
    """
    测试 IBKR 连接
    
    尝试获取 SPY 数据来验证连接
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 检查连接状态
        status = orchestrator.get_broker_status()
        if not status.get('ibkr', {}).get('is_connected', False):
            return {
                'status': 'not_connected',
                'message': 'IBKR is not connected. Call /api/broker/ibkr/connect first.'
            }
        
        # 尝试获取 SPY 数据
        spy_data = await orchestrator.get_spy_data()
        
        if spy_data:
            return {
                'status': 'success',
                'message': 'IBKR connection is working',
                'test_data': {
                    'symbol': 'SPY',
                    'price': spy_data.get('price'),
                    'sma50': spy_data.get('sma50')
                }
            }
        else:
            return {
                'status': 'warning',
                'message': 'IBKR connected but unable to fetch data'
            }
        
    except Exception as e:
        logger.error(f"IBKR 测试失败: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }


@router.get("/futu/test")
async def test_futu_connection():
    """
    测试 Futu 连接
    
    尝试获取期权数据来验证连接
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 检查连接状态
        status = orchestrator.get_broker_status()
        if not status.get('futu', {}).get('is_connected', False):
            return {
                'status': 'not_connected',
                'message': 'Futu is not connected. Call /api/broker/futu/connect first.'
            }
        
        # 尝试获取 IV 数据
        iv_data = await orchestrator.fetch_iv_data(['SPY'])
        
        if iv_data:
            return {
                'status': 'success',
                'message': 'Futu connection is working',
                'test_data': iv_data
            }
        else:
            return {
                'status': 'warning',
                'message': 'Futu connected but unable to fetch data'
            }
        
    except Exception as e:
        logger.error(f"Futu 测试失败: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }


@router.get("/config/defaults")
async def get_default_config():
    """
    获取默认 Broker 配置
    """
    return {
        'ibkr': {
            'host': '127.0.0.1',
            'port': {
                'gateway': 4002,
                'tws': 7497,
                'gateway_paper': 4002,
                'tws_paper': 7497
            },
            'client_id': 1,
            'timeout': 30,
            'notes': [
                'TWS 或 Gateway 必须运行',
                'API 连接必须在软件中启用',
                'Paper Trading 使用相同端口'
            ]
        },
        'futu': {
            'host': '127.0.0.1',
            'port': 11111,
            'rate_limit': 10,
            'notes': [
                'OpenD 必须运行',
                '需要有效的 Futu 账户',
                '美股期权需要开通权限'
            ]
        }
    }
