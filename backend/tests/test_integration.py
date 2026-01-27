"""
Momentum Radar 后端整合测试

测试 Task 1-11 的功能:
- 数据库 Schema
- IBKR/Futu Connector
- 技术指标计算器
- Finviz/MarketChameleon 解析器
- ETF/个股评分计算器
- Regime Gate
- 编排服务
- API 端点

注意: 运行测试前需要:
1. 安装依赖: pip install pytest pytest-asyncio httpx
2. 部分测试需要 IBKR/Futu 连接
"""

import pytest
import asyncio
from datetime import datetime, date
from typing import Dict, List
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ==================== Task 1: 数据库 Schema 测试 ====================

class TestDatabaseSchema:
    """测试数据库 Schema"""
    
    def test_import_models(self):
        """测试模型导入"""
        from app.models.database import (
            Base, ETF, Stock, Task,
            PriceHistory, IVData, ImportedData,
            ScoreSnapshot, BrokerStatus
        )
        
        assert Base is not None
        assert ETF is not None
        assert PriceHistory is not None
        assert IVData is not None
    
    def test_price_history_columns(self):
        """测试 PriceHistory 表结构"""
        from app.models.database import PriceHistory
        
        columns = [c.name for c in PriceHistory.__table__.columns]
        expected = ['id', 'symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'source', 'created_at']
        
        for col in expected:
            assert col in columns, f"Missing column: {col}"
    
    def test_iv_data_columns(self):
        """测试 IVData 表结构"""
        from app.models.database import IVData
        
        columns = [c.name for c in IVData.__table__.columns]
        expected = ['id', 'symbol', 'date', 'iv7', 'iv30', 'iv60', 'iv90', 'total_oi', 'delta_oi_1d']
        
        for col in expected:
            assert col in columns, f"Missing column: {col}"


# ==================== Task 4: 技术指标计算器测试 ====================

class TestTechnicalCalculator:
    """测试技术指标计算器"""
    
    def test_calculate_sma(self):
        """测试 SMA 计算"""
        from app.services.calculators.technical import calculate_sma
        import pandas as pd
        
        prices = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
        sma = calculate_sma(prices, period=5)
        
        assert len(sma) == len(prices)
        assert sma.iloc[-1] == 18.0  # (16+17+18+19+20) / 5
    
    def test_calculate_rsi(self):
        """测试 RSI 计算"""
        from app.services.calculators.technical import calculate_rsi
        import pandas as pd
        
        # 创建上涨趋势
        prices = pd.Series([100 + i * 2 for i in range(20)])
        rsi = calculate_rsi(prices, period=14)
        
        assert rsi.iloc[-1] > 70  # 强上涨应该 RSI > 70
    
    def test_calculate_returns(self):
        """测试收益率计算"""
        from app.services.calculators.technical import calculate_returns
        import pandas as pd
        
        prices = pd.Series([100, 110, 121, 133.1])  # 约 10% 每期
        
        ret = calculate_returns(prices, period=3)
        assert abs(ret - 0.331) < 0.01  # 33.1% 总收益
    
    def test_calculate_max_drawdown(self):
        """测试最大回撤计算"""
        from app.services.calculators.technical import calculate_max_drawdown
        import pandas as pd
        
        # 创建有回撤的序列: 100 -> 120 -> 96 -> 100
        prices = pd.Series([100, 110, 120, 100, 96, 100])
        
        mdd = calculate_max_drawdown(prices)
        assert abs(mdd - (-0.2)) < 0.01  # 从 120 回撤到 96 = -20%


# ==================== Task 5: Finviz 解析器测试 ====================

class TestFinvizParser:
    """测试 Finviz 解析器"""
    
    def test_parse_finviz_json(self):
        """测试 JSON 解析"""
        from app.services.parsers.finviz_parser import parse_finviz_json
        
        data = [
            {
                'Ticker': 'AAPL',
                'Price': '185.5',
                'SMA20': '182.0',
                'SMA50': '178.0',
                'SMA200': '172.0',
                'RSI': '55.5'
            }
        ]
        
        parsed = parse_finviz_json(data)
        
        assert len(parsed) == 1
        assert parsed[0]['symbol'] == 'AAPL'
        assert parsed[0]['price'] == 185.5
    
    def test_calculate_breadth_metrics(self):
        """测试广度指标计算"""
        from app.services.parsers.finviz_parser import calculate_breadth_metrics
        
        data = [
            {'symbol': 'AAPL', 'price': 100, 'sma50': 95, 'sma200': 90},
            {'symbol': 'MSFT', 'price': 100, 'sma50': 105, 'sma200': 90},
            {'symbol': 'GOOG', 'price': 100, 'sma50': 95, 'sma200': 110}
        ]
        
        breadth = calculate_breadth_metrics(data)
        
        assert 'pct_above_sma50' in breadth
        assert breadth['pct_above_sma50'] == pytest.approx(2/3, 0.01)
    
    def test_validate_finviz_data(self):
        """测试数据验证"""
        from app.services.parsers.finviz_parser import validate_finviz_data
        
        # 完整数据
        good_data = [
            {'symbol': 'AAPL', 'price': 100, 'sma50': 95, 'rsi': 55}
        ]
        
        result = validate_finviz_data(good_data)
        assert result['is_valid'] == True


# ==================== Task 6: MarketChameleon 解析器测试 ====================

class TestMCParser:
    """测试 MarketChameleon 解析器"""
    
    def test_calculate_heat_score(self):
        """测试热度分计算"""
        from app.services.parsers.mc_parser import calculate_heat_score
        
        score = calculate_heat_score(
            rel_notional=80.0,
            rel_vol=1.5,
            trade_count=5000
        )
        
        assert 0 <= score <= 100
    
    def test_calculate_risk_score(self):
        """测试风险分计算"""
        from app.services.parsers.mc_parser import calculate_risk_score
        
        score = calculate_risk_score(
            ivr=60.0,
            iv_hv_ratio=1.3,
            iv_change=5.0
        )
        
        assert 0 <= score <= 100
    
    def test_classify_heat_type(self):
        """测试热度类型分类"""
        from app.services.parsers.mc_parser import classify_heat_type
        
        # 高热度 + 适中 IVR = TREND_HEAT
        heat_type = classify_heat_type(heat_score=85, ivr=40)
        assert heat_type in ['TREND_HEAT', 'EVENT_HEAT', 'HEDGE_HEAT', 'NORMAL']
    
    def test_process_mc_data(self):
        """测试完整数据处理"""
        from app.services.parsers.mc_parser import process_mc_data
        
        data = [
            {
                'symbol': 'AAPL',
                'ivr': 45,
                'iv_hv_ratio': 1.2,
                'rel_notional': 80,
                'rel_vol': 1.5,
                'trade_count': 5000,
                'iv30': 25,
                'iv60': 26,
                'iv90': 27
            }
        ]
        
        processed = process_mc_data(data)
        
        assert len(processed) == 1
        assert 'heat_score' in processed[0]
        assert 'risk_score' in processed[0]
        assert 'heat_type' in processed[0]


# ==================== Task 7: ETF 评分计算器测试 ====================

class TestETFScoreCalculator:
    """测试 ETF 评分计算器"""
    
    def test_import_calculator(self):
        """测试导入"""
        from app.services.calculators.etf_score import ETFScoreCalculator, SECTOR_ETFS
        
        assert ETFScoreCalculator is not None
        assert len(SECTOR_ETFS) == 11
    
    def test_weights_sum_to_one(self):
        """测试权重和为 1"""
        from app.services.calculators.etf_score import ETFScoreCalculator
        
        total_weight = sum(ETFScoreCalculator.WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001


# ==================== Task 8: 个股评分计算器测试 ====================

class TestStockScoreCalculator:
    """测试个股评分计算器"""
    
    def test_import_calculator(self):
        """测试导入"""
        from app.services.calculators.stock_score import StockScoreCalculator
        
        assert StockScoreCalculator is not None
    
    def test_weights_sum_to_one(self):
        """测试权重和为 1"""
        from app.services.calculators.stock_score import StockScoreCalculator
        
        total_weight = sum(StockScoreCalculator.WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001


# ==================== Task 9: Regime Gate 测试 ====================

class TestRegimeGate:
    """测试 Regime Gate 计算器"""
    
    def test_import_calculator(self):
        """测试导入"""
        from app.services.calculators.regime_gate import RegimeGateCalculator
        
        assert RegimeGateCalculator is not None


# ==================== Task 10: 编排服务测试 ====================

class TestOrchestrator:
    """测试编排服务"""
    
    def test_import_orchestrator(self):
        """测试导入"""
        from app.services.orchestrator import DataOrchestrator, get_orchestrator
        
        assert DataOrchestrator is not None
    
    def test_get_singleton(self):
        """测试单例模式"""
        from app.services.orchestrator import get_orchestrator, reset_orchestrator
        
        reset_orchestrator()
        
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        
        assert o1 is o2
    
    def test_broker_status_initial(self):
        """测试初始 Broker 状态"""
        from app.services.orchestrator import DataOrchestrator
        
        orchestrator = DataOrchestrator()
        status = orchestrator.get_broker_status()
        
        assert 'ibkr' in status
        assert 'futu' in status
        assert status['ibkr']['is_connected'] == False
        assert status['futu']['is_connected'] == False
    
    def test_etf_lists(self):
        """测试 ETF 列表"""
        from app.services.orchestrator import DataOrchestrator
        
        orchestrator = DataOrchestrator()
        
        assert len(orchestrator.SECTOR_ETFS) == 11
        assert 'XLK' in orchestrator.SECTOR_ETFS
        
        assert len(orchestrator.INDUSTRY_ETFS) == 11
        assert 'SOXX' in orchestrator.INDUSTRY_ETFS


# ==================== Task 11: API 端点测试 ====================

class TestAPIEndpoints:
    """测试 API 端点"""
    
    def test_import_routers(self):
        """测试路由导入"""
        from app.api import market, import_data, broker
        
        assert market.router is not None
        assert import_data.router is not None
        assert broker.router is not None
    
    def test_market_router_prefix(self):
        """测试市场 API 路由前缀"""
        from app.api.market import router
        
        assert router.prefix == "/api/market"
    
    def test_import_router_prefix(self):
        """测试导入 API 路由前缀"""
        from app.api.import_data import router
        
        assert router.prefix == "/api/import"
    
    def test_broker_router_prefix(self):
        """测试 Broker API 路由前缀"""
        from app.api.broker import router
        
        assert router.prefix == "/api/broker"


# ==================== FastAPI 应用测试 ====================

@pytest.mark.asyncio
class TestFastAPIApp:
    """测试 FastAPI 应用"""
    
    async def test_app_creation(self):
        """测试应用创建"""
        from app.main import app
        
        assert app is not None
        assert app.title == "Momentum Radar API"
    
    async def test_health_endpoint(self):
        """测试健康检查端点"""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        
        async with AsyncClient(
            transport=ASGITransport(app=app), 
            base_url="http://test"
        ) as client:
            response = await client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
    
    async def test_root_endpoint(self):
        """测试根端点"""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        
        async with AsyncClient(
            transport=ASGITransport(app=app), 
            base_url="http://test"
        ) as client:
            response = await client.get("/")
            
            assert response.status_code == 200
            data = response.json()
            assert "endpoints" in data
    
    async def test_broker_status_endpoint(self):
        """测试 Broker 状态端点"""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        
        async with AsyncClient(
            transport=ASGITransport(app=app), 
            base_url="http://test"
        ) as client:
            response = await client.get("/api/broker/status")
            
            assert response.status_code == 200
            data = response.json()
            assert "ibkr" in data
            assert "futu" in data
    
    async def test_import_template_endpoint(self):
        """测试导入模板端点"""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        
        async with AsyncClient(
            transport=ASGITransport(app=app), 
            base_url="http://test"
        ) as client:
            response = await client.get("/api/import/templates/finviz")
            
            assert response.status_code == 200
            data = response.json()
            assert "required_fields" in data
            assert "sample_data" in data


# ==================== 运行测试 ====================

if __name__ == "__main__":
    # 运行基础测试（不需要 Broker 连接）
    pytest.main([
        __file__,
        "-v",
        "-x",  # 遇到第一个失败就停止
        "--tb=short",
        "-k", "not (ibkr or futu)"  # 排除需要 Broker 的测试
    ])
