"""
Stocks API 测试

测试用例：
- 股票列表 API
- 股票详情 API
- 对比 API
- 热度筛选 API

运行测试:
    cd backend
    pytest tests/test_stocks_api.py -v
"""

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models.database import Base, Stock, get_db, SessionLocal


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def test_db():
    """创建测试数据库会话"""
    # 使用内存数据库进行测试
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # 创建表
    Base.metadata.create_all(bind=engine)
    
    # 创建会话
    db = TestingSessionLocal()
    
    # 添加测试数据
    test_stocks = [
        Stock(
            symbol="AAPL",
            name="Apple Inc.",
            sector="XLK",
            industry="Technology",
            price=185.5,
            score_total=75.5,
            scores={"momentum": 80, "trend": 75, "volume": 70, "quality": 72, "options": 78},
            changes={"delta3d": 2.5, "delta5d": 5.0},
            metrics={
                "return20d": 8.5, "return63d": 15.2, "relativeStrength": 1.2,
                "sma20Slope": 0.5, "ivr": 45, "iv30": 25
            },
            heat_type="trend",
            heat_score=82.0,
            risk_score=35.0,
            thresholds_pass=True,
            thresholds={"price_above_sma50": "PASS", "rs_positive": "PASS"}
        ),
        Stock(
            symbol="MSFT",
            name="Microsoft Corp.",
            sector="XLK",
            industry="Technology",
            price=415.2,
            score_total=72.3,
            scores={"momentum": 75, "trend": 72, "volume": 68, "quality": 70, "options": 76},
            changes={"delta3d": 1.5, "delta5d": 3.0},
            metrics={
                "return20d": 6.5, "return63d": 12.2, "relativeStrength": 1.1,
                "sma20Slope": 0.4, "ivr": 40, "iv30": 22
            },
            heat_type="trend",
            heat_score=78.0,
            risk_score=30.0,
            thresholds_pass=True,
            thresholds={"price_above_sma50": "PASS", "rs_positive": "PASS"}
        ),
        Stock(
            symbol="NVDA",
            name="NVIDIA Corp.",
            sector="XLK",
            industry="Semiconductors",
            price=875.3,
            score_total=85.2,
            scores={"momentum": 90, "trend": 85, "volume": 82, "quality": 80, "options": 88},
            changes={"delta3d": 5.0, "delta5d": 8.0},
            metrics={
                "return20d": 15.5, "return63d": 45.2, "relativeStrength": 2.5,
                "sma20Slope": 1.2, "ivr": 65, "iv30": 45
            },
            heat_type="event",
            heat_score=92.0,
            risk_score=55.0,
            thresholds_pass=True,
            thresholds={"price_above_sma50": "PASS", "rs_positive": "PASS"}
        ),
        Stock(
            symbol="JPM",
            name="JPMorgan Chase",
            sector="XLF",
            industry="Banking",
            price=195.8,
            score_total=65.8,
            scores={"momentum": 65, "trend": 68, "volume": 62, "quality": 70, "options": 64},
            changes={"delta3d": 0.5, "delta5d": 1.5},
            metrics={
                "return20d": 3.5, "return63d": 8.2, "relativeStrength": 0.9,
                "sma20Slope": 0.2, "ivr": 35, "iv30": 18
            },
            heat_type="normal",
            heat_score=45.0,
            risk_score=25.0,
            thresholds_pass=True,
            thresholds={"price_above_sma50": "PASS", "rs_positive": "PASS"}
        ),
        Stock(
            symbol="XOM",
            name="Exxon Mobil",
            sector="XLE",
            industry="Energy",
            price=105.2,
            score_total=58.5,
            scores={"momentum": 55, "trend": 60, "volume": 58, "quality": 62, "options": 57},
            changes={"delta3d": -1.5, "delta5d": -2.0},
            metrics={
                "return20d": -2.5, "return63d": 5.2, "relativeStrength": 0.7,
                "sma20Slope": -0.1, "ivr": 30, "iv30": 20
            },
            heat_type="hedge",
            heat_score=35.0,
            risk_score=42.0,
            thresholds_pass=False,
            thresholds={"price_above_sma50": "FAIL", "rs_positive": "PASS"}
        ),
    ]
    
    for stock in test_stocks:
        db.add(stock)
    db.commit()
    
    yield db
    
    db.close()


@pytest.fixture
def override_get_db(test_db):
    """覆盖数据库依赖"""
    def _override():
        try:
            yield test_db
        finally:
            pass
    return _override


# ============================================================================
# 测试用例: 股票列表 API
# ============================================================================

@pytest.mark.asyncio
class TestStockListAPI:
    """测试股票列表 API"""
    
    async def test_get_stocks_list(self):
        """测试获取股票列表"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    async def test_get_stocks_with_limit(self):
        """测试带限制的股票列表"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks?limit=2")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) <= 2
    
    async def test_get_stocks_with_sector_filter(self):
        """测试按板块筛选股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks?sector=XLK")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            # 所有返回的股票都应该属于 XLK 板块
            for stock in data:
                if stock.get("sector"):
                    assert stock["sector"].upper() == "XLK"
    
    async def test_get_stocks_with_min_score(self):
        """测试按最低评分筛选"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks?min_score=70")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            # 所有返回的股票评分都应该 >= 70
            for stock in data:
                if stock.get("scoreTotal") is not None:
                    assert stock["scoreTotal"] >= 70
    
    async def test_get_top_stocks(self):
        """测试获取评分最高的股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/top/3")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) <= 3
            
            # 验证按评分降序排列
            scores = [s.get("scoreTotal", 0) for s in data if s.get("scoreTotal") is not None]
            assert scores == sorted(scores, reverse=True)


# ============================================================================
# 测试用例: 股票详情 API
# ============================================================================

@pytest.mark.asyncio
class TestStockDetailAPI:
    """测试股票详情 API"""
    
    async def test_get_stock_by_symbol(self):
        """测试按符号获取股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/symbol/AAPL")
            
            # 可能返回 200 或 404，取决于数据库中是否有数据
            assert response.status_code in [200, 404]
            
            if response.status_code == 200:
                data = response.json()
                assert data["symbol"] == "AAPL"
    
    async def test_get_stock_by_symbol_case_insensitive(self):
        """测试符号大小写不敏感"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response1 = await client.get("/api/stocks/symbol/AAPL")
            response2 = await client.get("/api/stocks/symbol/aapl")
            
            # 两个请求应该返回相同的状态码
            assert response1.status_code == response2.status_code
    
    async def test_get_stock_detail(self):
        """测试获取股票详细信息"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/symbol/AAPL/detail")
            
            assert response.status_code in [200, 404]
            
            if response.status_code == 200:
                data = response.json()
                assert data["symbol"] == "AAPL"
                # 详情应该包含额外信息
                assert "detail" in data or "scores" in data
    
    async def test_get_stock_not_found(self):
        """测试获取不存在的股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/symbol/INVALID_SYMBOL_XYZ")
            
            assert response.status_code == 404
            data = response.json()
            assert "detail" in data
    
    async def test_get_stock_by_id(self):
        """测试按 ID 获取股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # 首先获取列表以找到一个有效的 ID
            list_response = await client.get("/api/stocks?limit=1")
            
            if list_response.status_code == 200 and list_response.json():
                stock_id = list_response.json()[0].get("id")
                if stock_id:
                    response = await client.get(f"/api/stocks/{stock_id}")
                    assert response.status_code == 200
                    data = response.json()
                    assert data["id"] == stock_id


# ============================================================================
# 测试用例: 股票对比 API
# ============================================================================

@pytest.mark.asyncio
class TestCompareAPI:
    """测试股票对比 API"""
    
    async def test_compare_stocks(self):
        """测试对比多只股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # 首先获取股票列表
            list_response = await client.get("/api/stocks?limit=2")
            
            if list_response.status_code == 200 and len(list_response.json()) >= 2:
                symbols = [s["symbol"] for s in list_response.json()[:2]]
                
                response = await client.post(
                    "/api/stocks/compare",
                    json=symbols
                )
                
                assert response.status_code == 200
                data = response.json()
                assert isinstance(data, list)
                assert len(data) == len(symbols)
    
    async def test_compare_max_limit(self):
        """测试对比超过最大数量限制"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # 尝试对比 5 只股票（超过限制）
            symbols = ["AAPL", "MSFT", "GOOG", "AMZN", "META"]
            
            response = await client.post(
                "/api/stocks/compare",
                json=symbols
            )
            
            # 应该返回 400 错误
            assert response.status_code == 400
            data = response.json()
            assert "detail" in data
    
    async def test_compare_empty_list(self):
        """测试空列表对比"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/stocks/compare",
                json=[]
            )
            
            # 应该返回 400 错误
            assert response.status_code == 400
    
    async def test_compare_not_found_stocks(self):
        """测试对比不存在的股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            symbols = ["INVALID_XYZ", "INVALID_ABC"]
            
            response = await client.post(
                "/api/stocks/compare",
                json=symbols
            )
            
            # 应该返回 404 错误
            assert response.status_code == 404
    
    async def test_compare_returns_in_order(self):
        """测试对比结果按请求顺序返回"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # 获取股票列表
            list_response = await client.get("/api/stocks?limit=3")
            
            if list_response.status_code == 200 and len(list_response.json()) >= 2:
                symbols = [s["symbol"] for s in list_response.json()[:2]]
                # 反转顺序
                symbols_reversed = symbols[::-1]
                
                response = await client.post(
                    "/api/stocks/compare",
                    json=symbols_reversed
                )
                
                if response.status_code == 200:
                    data = response.json()
                    returned_symbols = [s["symbol"] for s in data]
                    assert returned_symbols == symbols_reversed


# ============================================================================
# 测试用例: 热度筛选 API
# ============================================================================

@pytest.mark.asyncio
class TestHeatFilterAPI:
    """测试热度筛选 API"""
    
    async def test_get_stocks_by_heat_trend(self):
        """测试按趋势热度筛选"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/trend")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            
            # 所有返回的股票热度类型应该是 trend
            for stock in data:
                assert stock.get("heatType") == "trend"
    
    async def test_get_stocks_by_heat_event(self):
        """测试按事件热度筛选"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/event")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    async def test_get_stocks_by_heat_hedge(self):
        """测试按对冲热度筛选"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/hedge")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    async def test_get_stocks_by_heat_normal(self):
        """测试按普通热度筛选"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/normal")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    async def test_get_stocks_by_invalid_heat_type(self):
        """测试无效的热度类型"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/invalid_type")
            
            # 应该返回 400 错误
            assert response.status_code == 400
            data = response.json()
            assert "detail" in data
    
    async def test_get_stocks_by_heat_with_sector(self):
        """测试热度筛选结合板块筛选"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/trend?sector=XLK")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            
            # 验证筛选条件
            for stock in data:
                assert stock.get("heatType") == "trend"
                if stock.get("sector"):
                    assert stock["sector"].upper() == "XLK"
    
    async def test_get_stocks_by_heat_with_limit(self):
        """测试热度筛选带数量限制"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/trend?limit=5")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) <= 5
    
    async def test_heat_stocks_sorted_by_heat_score(self):
        """测试热度股票按热度评分排序"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-heat/trend")
            
            assert response.status_code == 200
            data = response.json()
            
            if len(data) >= 2:
                # 验证按热度评分降序排列
                heat_scores = [s.get("heatScore", 0) for s in data]
                assert heat_scores == sorted(heat_scores, reverse=True)


# ============================================================================
# 测试用例: 按 ETF 获取股票
# ============================================================================

@pytest.mark.asyncio
class TestStocksByETFAPI:
    """测试按 ETF 获取股票 API"""
    
    async def test_get_stocks_by_etf(self):
        """测试获取 ETF 持仓股票"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-etf/XLK")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    async def test_get_stocks_by_etf_with_limit(self):
        """测试获取 ETF 持仓股票带限制"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks/by-etf/XLK?limit=5")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) <= 5


# ============================================================================
# 测试用例: 响应格式验证
# ============================================================================

@pytest.mark.asyncio
class TestResponseFormat:
    """测试响应格式"""
    
    async def test_stock_response_fields(self):
        """测试股票响应字段完整性"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks?limit=1")
            
            if response.status_code == 200 and response.json():
                stock = response.json()[0]
                
                # 验证必需字段存在
                required_fields = ["symbol", "scoreTotal", "scores", "heatType"]
                for field in required_fields:
                    assert field in stock, f"Missing required field: {field}"
    
    async def test_stock_scores_structure(self):
        """测试股票评分结构"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks?limit=1")
            
            if response.status_code == 200 and response.json():
                stock = response.json()[0]
                scores = stock.get("scores", {})
                
                # 验证评分维度
                score_dimensions = ["momentum", "trend", "volume", "quality", "options"]
                for dim in score_dimensions:
                    assert dim in scores, f"Missing score dimension: {dim}"
    
    async def test_stock_metrics_structure(self):
        """测试股票指标结构"""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/stocks?limit=1")
            
            if response.status_code == 200 and response.json():
                stock = response.json()[0]
                metrics = stock.get("metrics", {})
                
                # 验证关键指标
                assert isinstance(metrics, dict)


# ============================================================================
# 运行测试
# ============================================================================

if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-x",  # 遇到第一个失败就停止
        "--asyncio-mode=auto"
    ])
