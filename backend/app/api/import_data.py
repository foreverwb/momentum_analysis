"""
数据导入 API
Data Import API Endpoints

支持:
- Finviz 技术指标数据导入
- MarketChameleon 期权数据导入
- CSV/JSON 批量导入
"""

from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime, date
import json
import csv
import io
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import", tags=["Import"])


# ==================== Pydantic Models ====================

class FinvizImportRequest(BaseModel):
    """Finviz 数据导入请求"""
    etf_symbol: str = Field(..., description="关联的 ETF 代码")
    coverage: str = Field("top20", description="覆盖范围: top10/top15/top20/top25/top30")
    data: List[Dict[str, Any]] = Field(..., description="Finviz 数据列表")


class FinvizImportResponse(BaseModel):
    """Finviz 导入响应"""
    status: str
    etf_symbol: str
    coverage: str
    records_imported: int
    breadth_metrics: Dict[str, Any]
    validation: Dict[str, Any]
    statistics: Optional[Dict[str, Any]] = None


class MCImportRequest(BaseModel):
    """MarketChameleon 数据导入请求"""
    symbols: List[str] = Field(default=[], description="股票代码列表（可选，自动从数据中提取）")
    data: List[Dict[str, Any]] = Field(..., description="MarketChameleon 数据列表")


class MCImportResponse(BaseModel):
    """MarketChameleon 导入响应"""
    status: str
    records_imported: int
    heat_distribution: Dict[str, int]
    data: Optional[List[Dict[str, Any]]] = None


class BulkImportResponse(BaseModel):
    """批量导入响应"""
    status: str
    source: str
    records_imported: int
    errors: List[str]


class HoldingsImportRequest(BaseModel):
    """ETF 持仓导入请求"""
    etf_symbol: str
    holdings: List[Dict[str, Any]]


class HoldingsImportResponse(BaseModel):
    """ETF 持仓导入响应"""
    status: str
    etf_symbol: str
    holdings_count: int
    scored_holdings: Optional[List[Dict[str, Any]]] = None


# ==================== API Endpoints ====================

@router.post("/finviz", response_model=FinvizImportResponse)
async def import_finviz_data(request: FinvizImportRequest):
    """
    导入 Finviz 技术指标数据
    
    数据格式示例:
    ```json
    {
        "etf_symbol": "XLK",
        "coverage": "top20",
        "data": [
            {
                "Ticker": "AAPL",
                "Price": 185.5,
                "Change": 1.23,
                "Volume": 50000000,
                "SMA20": 182.0,
                "SMA50": 178.0,
                "SMA200": 172.0,
                "RSI": 55.5,
                "52W High": 199.0,
                "52W Low": 164.0
            }
        ]
    }
    ```
    
    返回:
    - 导入记录数
    - 广度指标 (% above SMA20/50/200)
    - 数据验证结果
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 处理导入
        result = await orchestrator.process_finviz_import(
            etf_symbol=request.etf_symbol,
            data=request.data,
            coverage=request.coverage
        )
        
        if 'error' in result:
            raise HTTPException(status_code=400, detail=result['error'])
        
        return {
            'status': 'success',
            'etf_symbol': request.etf_symbol,
            'coverage': request.coverage,
            'records_imported': result.get('records_count', 0),
            'breadth_metrics': result.get('breadth_metrics', {}),
            'validation': result.get('validation', {}),
            'statistics': result.get('statistics')
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finviz 数据导入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/marketchameleon", response_model=MCImportResponse)
async def import_mc_data(request: MCImportRequest):
    """
    导入 MarketChameleon 期权数据
    
    数据格式示例:
    ```json
    {
        "data": [
            {
                "symbol": "AAPL",
                "ivr": 45.5,
                "iv_hv_ratio": 1.2,
                "rel_notional": 85.0,
                "rel_vol": 1.8,
                "trade_count": 5000,
                "iv30": 25.5,
                "iv60": 26.0,
                "iv90": 27.0,
                "pct_multi_leg": 30.0,
                "pct_contingent": 15.0
            }
        ]
    }
    ```
    
    返回:
    - 导入记录数
    - 热度类型分布
    - 处理后的数据（包含 HeatScore、RiskScore）
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # 处理导入
        result = await orchestrator.process_mc_import(request.data)
        
        if 'error' in result:
            raise HTTPException(status_code=400, detail=result['error'])
        
        return {
            'status': 'success',
            'records_imported': result.get('records_count', 0),
            'heat_distribution': result.get('heat_distribution', {}),
            'data': result.get('processed_data')
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MarketChameleon 数据导入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finviz/csv")
async def import_finviz_csv(
    file: UploadFile = File(...),
    etf_symbol: str = Form(...),
    coverage: str = Form("top20")
):
    """
    通过 CSV 文件导入 Finviz 数据
    
    CSV 列要求:
    - Ticker: 股票代码
    - Price: 当前价格
    - Change: 涨跌幅
    - Volume: 成交量
    - SMA20, SMA50, SMA200: 均线
    - RSI: RSI 指标
    - 52W High, 52W Low: 52 周高低
    """
    try:
        # 读取 CSV
        content = await file.read()
        text = content.decode('utf-8')
        
        reader = csv.DictReader(io.StringIO(text))
        data = list(reader)
        
        # 转换数值字段
        for row in data:
            for key in ['Price', 'Change', 'Volume', 'SMA20', 'SMA50', 'SMA200', 
                        'RSI', '52W High', '52W Low', 'Rel Volume']:
                if key in row:
                    try:
                        value = row[key].replace(',', '').replace('%', '')
                        row[key] = float(value) if value else None
                    except (ValueError, AttributeError):
                        row[key] = None
        
        # 处理导入
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        result = await orchestrator.process_finviz_import(
            etf_symbol=etf_symbol,
            data=data,
            coverage=coverage
        )
        
        return {
            'status': 'success',
            'etf_symbol': etf_symbol,
            'coverage': coverage,
            'records_imported': result.get('records_count', 0),
            'breadth_metrics': result.get('breadth_metrics', {}),
            'validation': result.get('validation', {})
        }
        
    except Exception as e:
        logger.error(f"CSV 导入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/marketchameleon/csv")
async def import_mc_csv(
    file: UploadFile = File(...)
):
    """
    通过 CSV 文件导入 MarketChameleon 数据
    
    CSV 列要求:
    - symbol: 股票代码
    - ivr: IV Rank
    - iv_hv_ratio: IV/HV 比率
    - rel_notional: 相对名义成交额
    - rel_vol: 相对成交量
    - trade_count: 交易笔数
    - iv30, iv60, iv90: IV 期限结构
    """
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        reader = csv.DictReader(io.StringIO(text))
        data = list(reader)
        
        # 转换数值字段
        numeric_fields = ['ivr', 'iv_hv_ratio', 'rel_notional', 'rel_vol', 
                          'trade_count', 'iv30', 'iv60', 'iv90', 
                          'pct_multi_leg', 'pct_contingent', 'iv_change']
        
        for row in data:
            for key in numeric_fields:
                if key in row:
                    try:
                        value = row[key].replace(',', '').replace('%', '')
                        row[key] = float(value) if value else None
                    except (ValueError, AttributeError):
                        row[key] = None
        
        # 处理导入
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        result = await orchestrator.process_mc_import(data)
        
        return {
            'status': 'success',
            'records_imported': result.get('records_count', 0),
            'heat_distribution': result.get('heat_distribution', {}),
            'data': result.get('processed_data')
        }
        
    except Exception as e:
        logger.error(f"MarketChameleon CSV 导入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/holdings", response_model=HoldingsImportResponse)
async def import_etf_holdings(request: HoldingsImportRequest):
    """
    导入 ETF 持仓数据
    
    数据格式:
    ```json
    {
        "etf_symbol": "XLK",
        "holdings": [
            {"ticker": "AAPL", "weight": 22.5},
            {"ticker": "MSFT", "weight": 21.0},
            {"ticker": "NVDA", "weight": 6.5}
        ]
    }
    ```
    
    返回:
    - 持仓数量
    - 持仓评分（如果 IBKR 已连接）
    """
    try:
        holdings_count = len(request.holdings)
        
        # 提取股票代码
        symbols = [h.get('ticker') or h.get('symbol') for h in request.holdings]
        symbols = [s for s in symbols if s]
        
        scored_holdings = None
        
        # 尝试评分持仓
        try:
            from app.services.orchestrator import get_orchestrator
            
            orchestrator = get_orchestrator()
            broker_status = orchestrator.get_broker_status()
            
            if broker_status.get('ibkr', {}).get('is_connected', False):
                scored_holdings = await orchestrator.score_etf_holdings(
                    etf_symbol=request.etf_symbol,
                    holdings=symbols,
                    top_n=20
                )
        except Exception as e:
            logger.warning(f"持仓评分失败: {e}")
        
        return {
            'status': 'success',
            'etf_symbol': request.etf_symbol,
            'holdings_count': holdings_count,
            'scored_holdings': scored_holdings
        }
        
    except Exception as e:
        logger.error(f"ETF 持仓导入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates/finviz")
async def get_finviz_template():
    """
    获取 Finviz 数据导入模板
    """
    template = {
        'description': 'Finviz 数据导入模板',
        'required_fields': ['Ticker'],
        'recommended_fields': [
            'Price', 'Change', 'Volume', 
            'SMA20', 'SMA50', 'SMA200',
            'RSI', '52W High', '52W Low', 'Rel Volume'
        ],
        'sample_data': [
            {
                'Ticker': 'AAPL',
                'Price': 185.50,
                'Change': 1.23,
                'Volume': 50000000,
                'SMA20': 182.0,
                'SMA50': 178.0,
                'SMA200': 172.0,
                'RSI': 55.5,
                '52W High': 199.0,
                '52W Low': 164.0,
                'Rel Volume': 1.2
            }
        ],
        'notes': [
            '从 Finviz Screener 导出数据',
            'Ticker 字段必填',
            '价格和均线字段用于计算广度指标'
        ]
    }
    return template


@router.get("/templates/marketchameleon")
async def get_mc_template():
    """
    获取 MarketChameleon 数据导入模板
    """
    template = {
        'description': 'MarketChameleon 期权数据导入模板',
        'required_fields': ['symbol'],
        'recommended_fields': [
            'ivr', 'iv_hv_ratio',
            'rel_notional', 'rel_vol', 'trade_count',
            'iv30', 'iv60', 'iv90',
            'pct_multi_leg', 'pct_contingent', 'iv_change'
        ],
        'sample_data': [
            {
                'symbol': 'AAPL',
                'ivr': 45.5,
                'iv_hv_ratio': 1.2,
                'rel_notional': 85.0,
                'rel_vol': 1.8,
                'trade_count': 5000,
                'iv30': 25.5,
                'iv60': 26.0,
                'iv90': 27.0,
                'pct_multi_leg': 30.0,
                'pct_contingent': 15.0,
                'iv_change': 2.5
            }
        ],
        'calculated_fields': [
            'heat_score: 基于 rel_notional, rel_vol, trade_count 计算',
            'risk_score: 基于 ivr, iv_hv_ratio, iv_change 计算',
            'confidence_penalty: 基于 pct_multi_leg, pct_contingent 计算',
            'term_score: 基于 iv30, iv60, iv90 斜率计算',
            'heat_type: 热度类型分类'
        ]
    }
    return template


@router.delete("/cache")
async def clear_import_cache():
    """
    清除导入数据缓存
    """
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        orchestrator.clear_cache()
        
        return {
            'status': 'success',
            'message': 'Import cache cleared'
        }
        
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
