from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.api import stocks, etfs, tasks
from app.api import market, import_data, broker
from app.core.logging_config import configure_logging
from app.models.database import engine, Base, init_db, init_default_sector_etfs

configure_logging()
logger = structlog.get_logger(__name__)

# 初始化数据库表
init_db()

# 初始化默认板块 ETF
try:
    init_default_sector_etfs()
    logger.info("默认板块 ETF 初始化完成")
except Exception as e:
    logger.exception("默认板块 ETF 初始化失败", err=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Momentum Radar API 启动中...")
    yield
    # 关闭时
    logger.info("Momentum Radar API 关闭中...")
    # 断开所有 Broker 连接
    try:
        from app.services.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        await orchestrator.disconnect_all()
    except Exception as e:
        logger.exception("关闭 Broker 连接时出错", err=str(e))


app = FastAPI(
    title="Momentum Radar API",
    description="""
    趋势动能监控系统 API
    
    ## 功能模块
    
    * **Market** - 市场数据和 Regime Gate
    * **ETFs** - ETF 评分和排名
    * **Stocks** - 个股评分
    * **Import** - 数据导入 (Finviz/MarketChameleon)
    * **Broker** - Broker 连接管理 (IBKR/Futu)
    * **Tasks** - 任务管理
    """,
    version="0.2.0",
    lifespan=lifespan
)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    bind_contextvars(
        request_id=request_id,
        path=request.url.path,
        method=request.method
    )
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        clear_contextvars()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 注册路由 ====================

# 原有路由
app.include_router(stocks.router, prefix="/api/stocks", tags=["Stocks"])
app.include_router(etfs.router, prefix="/api/etfs", tags=["ETFs"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])

# Task 11: 新增路由
app.include_router(market.router, tags=["Market"])
app.include_router(import_data.router, tags=["Import"])
app.include_router(broker.router, tags=["Broker"])


# ==================== 基础端点 ====================

@app.get("/")
async def root():
    """API 根端点"""
    return {
        "message": "Welcome to Momentum Radar API",
        "version": "0.2.0",
        "docs": "/docs",
        "endpoints": {
            "market": "/api/market",
            "etfs": "/api/etfs",
            "stocks": "/api/stocks",
            "import": "/api/import",
            "broker": "/api/broker",
            "tasks": "/api/tasks"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查端点"""
    health = {
        "status": "healthy",
        "api_version": "0.2.0"
    }
    
    # 检查 Broker 状态
    try:
        from app.services.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        broker_status = orchestrator.get_broker_status()
        health["brokers"] = {
            "ibkr": broker_status.get("ibkr", {}).get("is_connected", False),
            "futu": broker_status.get("futu", {}).get("is_connected", False)
        }
    except Exception:
        health["brokers"] = {"ibkr": False, "futu": False}
    
    return health


@app.get("/api/status")
async def get_api_status():
    """
    获取 API 状态概览
    
    包含:
    - API 版本
    - Broker 连接状态
    - 可用端点列表
    """
    try:
        from app.services.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        broker_status = orchestrator.get_broker_status()
    except Exception:
        broker_status = {}
    
    return {
        "api_version": "0.2.0",
        "status": "running",
        "broker_status": broker_status,
        "available_endpoints": {
            "market": [
                "GET /api/market/regime",
                "GET /api/market/etf-rankings",
                "GET /api/market/snapshot",
                "GET /api/market/spy",
                "GET /api/market/vix",
                "GET /api/market/etf/{symbol}/detail",
                "POST /api/market/sync"
            ],
            "etfs": [
                "GET /api/etfs",
                "GET /api/etfs/{etf_id}"
            ],
            "stocks": [
                "GET /api/stocks",
                "GET /api/stocks/{stock_id}"
            ],
            "import": [
                "POST /api/import/finviz",
                "POST /api/import/marketchameleon",
                "POST /api/import/finviz/csv",
                "POST /api/import/marketchameleon/csv",
                "POST /api/import/holdings",
                "GET /api/import/templates/finviz",
                "GET /api/import/templates/marketchameleon"
            ],
            "broker": [
                "GET /api/broker/status",
                "GET /api/broker/status/{broker}",
                "POST /api/broker/ibkr/connect",
                "POST /api/broker/ibkr/disconnect",
                "POST /api/broker/futu/connect",
                "POST /api/broker/futu/disconnect",
                "POST /api/broker/connect-all",
                "POST /api/broker/disconnect-all",
                "GET /api/broker/ibkr/test",
                "GET /api/broker/futu/test",
                "GET /api/broker/config/defaults"
            ],
            "tasks": [
                "GET /api/tasks",
                "GET /api/tasks/{task_id}",
                "POST /api/tasks"
            ]
        }
    }
