"""
数据导入 API
Data Import API Endpoints

支持:
- Finviz 技术指标数据导入
- MarketChameleon 期权数据导入
- CSV/JSON 批量导入
- ETF Holdings xlsx 文件上传
"""

from fastapi import APIRouter, HTTPException, File, UploadFile, Form, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Optional, Any
from datetime import datetime, date
import json
import csv
import io
import logging

from app.models import (
    get_db, ETF, ETFHolding, HoldingsUploadLog,
    is_valid_ticker, is_valid_sector_symbol, VALID_SECTOR_SYMBOLS
)

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


class HoldingsUploadResponse(BaseModel):
    """Holdings xlsx 上传响应"""
    status: str
    etf_symbol: str
    etf_type: str
    data_date: str
    records_imported: int
    records_skipped: int
    skipped_details: Optional[List[Dict[str, str]]] = None


# ==================== 辅助函数 ====================

def parse_xlsx_holdings(file_content: bytes) -> List[Dict[str, Any]]:
    """
    解析 xlsx 文件，提取 Ticker 和 Weight 列
    
    支持的表头格式:
    | Name | Ticker | Identifier | SEDOL | Weight | Sector | Shares Held | Local Currency |
    """
    try:
        import openpyxl
        from io import BytesIO
        import re
        
        workbook = openpyxl.load_workbook(BytesIO(file_content), read_only=False, data_only=True)
        
        def normalize_header(value) -> str:
            if value is None:
                return ""
            text = str(value).strip().lower().replace("\u00a0", " ")
            text = re.sub(r"\s+", " ", text)
            return re.sub(r"[^a-z0-9]", "", text)
        
        def find_header_in_sheet(sheet, max_rows: int = 50):
            for row_idx, row in enumerate(
                sheet.iter_rows(min_row=1, max_row=max_rows, max_col=sheet.max_column, values_only=True), start=1
            ):
                row_ticker = None
                row_weight = None
                for idx, cell in enumerate(row):
                    header_key = normalize_header(cell)
                    if not header_key:
                        continue
                    if row_ticker is None and ("ticker" in header_key or header_key == "symbol"):
                        row_ticker = idx
                    if row_weight is None and "weight" in header_key:
                        row_weight = idx
                if row_ticker is not None and row_weight is not None:
                    return row_idx, row_ticker, row_weight
            return None, None, None

        header_row = None
        ticker_idx = None
        weight_idx = None
        target_sheet = None
        for sheet in workbook.worksheets:
            header_row, ticker_idx, weight_idx = find_header_in_sheet(sheet)
            if header_row is not None:
                target_sheet = sheet
                break

        if header_row is None or target_sheet is None:
            raise ValueError("未找到包含 Ticker 和 Weight 的表头行")
        
        # 解析数据行
        holdings = []
        for row_idx, row in enumerate(
            target_sheet.iter_rows(
                min_row=header_row + 1,
                max_row=target_sheet.max_row,
                max_col=target_sheet.max_column,
                values_only=True
            ),
            start=header_row + 1
        ):
            if len(row) > max(ticker_idx, weight_idx):
                ticker = row[ticker_idx]
                weight = row[weight_idx]
                
                if ticker and weight is not None:
                    holdings.append({
                        "row": row_idx,
                        "ticker": str(ticker).strip(),
                        "weight": weight
                    })
        
        return holdings
        
    except ImportError:
        raise HTTPException(
            status_code=500, 
            detail="需要安装 openpyxl 库: pip install openpyxl"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析 xlsx 文件失败: {str(e)}")


def validate_and_filter_holdings(holdings: List[Dict[str, Any]]) -> tuple:
    """
    验证并过滤持仓数据
    返回: (有效持仓列表, 跳过的记录详情)
    """
    valid_holdings = []
    skipped = []
    
    for h in holdings:
        ticker = h.get("ticker", "")
        weight = h.get("weight")
        row = h.get("row", "unknown")
        
        # 验证 Ticker
        if not is_valid_ticker(ticker):
            skipped.append({
                "row": str(row),
                "ticker": ticker,
                "reason": "Ticker 为空或不是有效的英文字符"
            })
            continue
        
        # 验证 Weight
        try:
            weight_float = float(weight)
            if weight_float <= 0:
                skipped.append({
                    "row": str(row),
                    "ticker": ticker,
                    "reason": f"Weight 值无效: {weight}"
                })
                continue
        except (ValueError, TypeError):
            skipped.append({
                "row": str(row),
                "ticker": ticker,
                "reason": f"Weight 无法转换为数字: {weight}"
            })
            continue
        
        valid_holdings.append({
            "ticker": ticker.upper(),
            "weight": weight_float
        })
    
    return valid_holdings, skipped


# ==================== API Endpoints ====================

@router.post("/holdings/xlsx", response_model=HoldingsUploadResponse)
async def upload_holdings_xlsx(
    file: UploadFile = File(..., description="xlsx 文件"),
    etf_type: str = Form(..., description="ETF 类型: sector 或 industry"),
    etf_symbol: str = Form(..., description="ETF 符号"),
    data_date: str = Form(..., description="数据日期 (YYYY-MM-DD)"),
    parent_sector: Optional[str] = Form(None, description="父板块符号（仅 industry 类型需要）"),
    db: Session = Depends(get_db)
):
    """
    上传 ETF Holdings xlsx 文件
    
    - 板块 ETF: etf_type=sector, etf_symbol 必须是 11 个默认板块之一
    - 行业 ETF: etf_type=industry, 需要提供 parent_sector（所属板块）
    
    xlsx 文件格式:
    | Name | Ticker | Identifier | SEDOL | Weight | Sector | Shares Held | Local Currency |
    
    只会提取 Ticker 和 Weight 列
    """
    # 验证 etf_type
    if etf_type not in ["sector", "industry"]:
        raise HTTPException(status_code=400, detail="etf_type 必须是 'sector' 或 'industry'")
    
    etf_symbol = etf_symbol.upper()
    
    # 板块 ETF 验证
    if etf_type == "sector":
        if not is_valid_sector_symbol(etf_symbol):
            raise HTTPException(
                status_code=400, 
                detail=f"无效的板块 ETF 符号。有效值: {', '.join(VALID_SECTOR_SYMBOLS)}"
            )
    
    # 行业 ETF 验证
    if etf_type == "industry":
        if parent_sector:
            parent_sector = parent_sector.upper()
            if not is_valid_sector_symbol(parent_sector):
                raise HTTPException(
                    status_code=400,
                    detail=f"无效的父板块符号。有效值: {', '.join(VALID_SECTOR_SYMBOLS)}"
                )
    
    # 验证日期格式
    try:
        parsed_date = datetime.strptime(data_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式无效，请使用 YYYY-MM-DD 格式")
    
    # 验证文件类型
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 xlsx 或 xls 文件格式")
    
    try:
        # 读取文件内容
        file_content = await file.read()
        
        # 解析 xlsx
        raw_holdings = parse_xlsx_holdings(file_content)
        
        if not raw_holdings:
            raise HTTPException(status_code=400, detail="xlsx 文件中没有找到有效的持仓数据")
        
        # 验证和过滤数据
        valid_holdings, skipped = validate_and_filter_holdings(raw_holdings)
        
        if not valid_holdings:
            raise HTTPException(
                status_code=400, 
                detail=f"所有持仓数据都无效。跳过 {len(skipped)} 条记录"
            )
        
        # 查找或创建 ETF
        etf = db.query(ETF).filter(ETF.symbol == etf_symbol).first()
        
        if not etf:
            # 创建新的 ETF 记录
            etf = ETF(
                symbol=etf_symbol,
                name=etf_symbol,
                type=etf_type,
                parent_sector=parent_sector if etf_type == "industry" else None,
                score=0.0,
                rank=0,
                delta={"delta3d": None, "delta5d": None},
                completeness=0.0,
                holdings_count=0
            )
            db.add(etf)
            db.flush()
            logger.info(f"创建新的 ETF 记录: {etf_symbol}")
        
        # 删除该 ETF 在指定日期的旧持仓数据
        db.query(ETFHolding).filter(
            ETFHolding.etf_id == etf.id,
            ETFHolding.data_date == parsed_date
        ).delete()
        
        # 插入新的持仓数据
        for h in valid_holdings:
            holding = ETFHolding(
                etf_id=etf.id,
                etf_symbol=etf_symbol,
                ticker=h["ticker"],
                weight=h["weight"],
                data_date=parsed_date
            )
            db.add(holding)
        
        # 更新 ETF 的持仓数量
        etf.holdings_count = len(valid_holdings)
        etf.updated_at = datetime.utcnow()
        
        # 记录上传日志
        upload_log = HoldingsUploadLog(
            etf_symbol=etf_symbol,
            etf_type=etf_type,
            data_date=parsed_date,
            file_name=file.filename,
            records_count=len(valid_holdings),
            skipped_count=len(skipped),
            status="success"
        )
        db.add(upload_log)
        
        db.commit()
        
        logger.info(f"成功上传 {etf_symbol} 的持仓数据: {len(valid_holdings)} 条记录, 跳过 {len(skipped)} 条")
        
        return HoldingsUploadResponse(
            status="success",
            etf_symbol=etf_symbol,
            etf_type=etf_type,
            data_date=data_date,
            records_imported=len(valid_holdings),
            records_skipped=len(skipped),
            skipped_details=skipped[:20] if skipped else None  # 最多返回前 20 条跳过记录
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        try:
            upload_log = HoldingsUploadLog(
                etf_symbol=etf_symbol,
                etf_type=etf_type,
                data_date=parsed_date,
                file_name=file.filename if file else None,
                records_count=0,
                skipped_count=0,
                status="error",
                error_message=str(e)
            )
            db.add(upload_log)
            db.commit()
        except:
            db.rollback()
        
        logger.error(f"上传 Holdings 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/holdings/logs", response_model=List[dict])
async def get_holdings_upload_logs(
    etf_symbol: Optional[str] = Query(None, description="ETF 符号"),
    limit: int = Query(50, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """
    获取 Holdings 上传日志
    """
    query = db.query(HoldingsUploadLog)
    
    if etf_symbol:
        query = query.filter(HoldingsUploadLog.etf_symbol == etf_symbol.upper())
    
    logs = query.order_by(HoldingsUploadLog.created_at.desc()).limit(limit).all()
    
    return [
        {
            "id": log.id,
            "etfSymbol": log.etf_symbol,
            "etfType": log.etf_type,
            "dataDate": log.data_date.isoformat() if log.data_date else None,
            "fileName": log.file_name,
            "recordsCount": log.records_count,
            "skippedCount": log.skipped_count,
            "status": log.status,
            "errorMessage": log.error_message,
            "createdAt": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]


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


@router.get("/templates/holdings")
async def get_holdings_template():
    """
    获取 ETF Holdings xlsx 导入模板
    """
    template = {
        'description': 'ETF Holdings 数据导入模板',
        'file_format': 'xlsx',
        'required_columns': ['Ticker', 'Weight'],
        'all_columns': [
            'Name', 'Ticker', 'Identifier', 'SEDOL', 
            'Weight', 'Sector', 'Shares Held', 'Local Currency'
        ],
        'sample_data': [
            {'Name': 'Apple Inc.', 'Ticker': 'AAPL', 'Weight': 22.5},
            {'Name': 'Microsoft Corp', 'Ticker': 'MSFT', 'Weight': 21.0},
            {'Name': 'NVIDIA Corp', 'Ticker': 'NVDA', 'Weight': 6.5}
        ],
        'validation_rules': [
            'Ticker 必须是有效的英文字符（以字母开头，可包含数字、点号、短横线）',
            'Ticker 为空或无效时，该行会被忽略',
            'Weight 必须是正数'
        ],
        'valid_sector_etfs': VALID_SECTOR_SYMBOLS,
        'upload_commands': {
            'sector_etf': 'uploads -d YYYY-MM-DD -t sector -a ETF_SYMBOL',
            'industry_etf': 'uploads -d YYYY-MM-DD -t industry -s PARENT_SECTOR -a ETF_SYMBOL'
        }
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
