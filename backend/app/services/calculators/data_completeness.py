"""
数据完整度评估模块
评估每只持仓股票及覆盖范围的数据完整度

数据源权重:
- 市场数据 (IBKR 价格/成交量): 40%
- 期权数据 (Futu IV): 30%
- Finviz 数据: 20%
- MarketChameleon 数据: 10%

状态判定:
- 完整 (Complete): >= 80%
- 待更新 (Pending): 50-79%
- 缺失 (Missing): < 50%
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


@dataclass
class DataSourceStatus:
    """数据源状态"""
    finviz: bool = False                  # Finviz 数据
    market_chameleon: bool = False        # MarketChameleon 数据
    market_data: bool = False             # 市场数据 (IBKR)
    options_data: bool = False            # 期权数据 (Futu)


@dataclass
class HoldingDataStatus:
    """单只持仓数据完整度"""
    ticker: str
    completeness_score: float             # 0-100
    status: str                           # 'complete' | 'pending' | 'missing'
    data_sources: Dict[str, bool]         # 各数据源可用性
    missing_sources: List[str]            # 缺失的数据源
    last_updated: Optional[str] = None    # 最后更新时间

    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'completeness_score': round(self.completeness_score, 2),
            'status': self.status,
            'data_sources': {key: bool(value) for key, value in self.data_sources.items()},
            'missing_sources': self.missing_sources,
            'last_updated': self.last_updated
        }


@dataclass
class CoverageRangeCompleteness:
    """覆盖范围完整度"""
    coverage: str                         # 'top10', 'weight70' 等
    total_stocks: int
    complete_count: int                   # 完整的股票数
    pending_count: int                    # 待更新的股票数
    missing_count: int                    # 缺失的股票数
    average_completeness: float           # 平均完整度 0-100
    holdings_status: List[HoldingDataStatus]

    def to_dict(self) -> Dict:
        return {
            'coverage': self.coverage,
            'total_stocks': self.total_stocks,
            'complete_count': self.complete_count,
            'pending_count': self.pending_count,
            'missing_count': self.missing_count,
            'average_completeness': round(self.average_completeness, 2),
            'holdings_status': [h.to_dict() for h in self.holdings_status]
        }


class DataCompletenessCalculator:
    """
    数据完整度计算器

    评估持仓及覆盖范围的数据完整度
    """

    # 权重配置
    DATA_SOURCE_WEIGHTS = {
        'finviz': 0.20,
        'market_chameleon': 0.10,
        'market_data': 0.40,
        'options_data': 0.30
    }

    # 完整度阈值
    THRESHOLDS = {
        'complete': 80,      # >= 80: 完整
        'pending': 50,       # 50-79: 待更新
        'missing': 0         # < 50: 缺失
    }

    def __init__(self, db: Optional[Session] = None):
        """
        初始化计算器

        Args:
            db: SQLAlchemy 数据库会话
        """
        self.db = db

    def calculate_holding_data_completeness(
        self,
        ticker: str,
        holding_data: Dict[str, Any]
    ) -> HoldingDataStatus:
        """
        计算单只持仓的数据完整度

        Args:
            ticker: 股票代码
            holding_data: 持仓数据，包含各数据源信息
                {
                    'price_data': <float>,           # 价格
                    'volume': <float>,               # 成交量
                    'change_1d': <float>,            # 日涨跌
                    'iv30': <float>,                 # IV30
                    'finviz_metrics': <dict>,        # Finviz 指标
                    'mc_heat_score': <float>,        # MarketChameleon 热度
                    'data_sources': [<str>],         # 已有数据源列表
                    'updated_at': <str>              # 更新时间
                }

        Returns:
            HoldingDataStatus: 完整度评估结果
        """
        data_sources = {
            'finviz': False,
            'market_chameleon': False,
            'market_data': False,
            'options_data': False
        }

        # 检查市场数据 (IBKR)
        if (holding_data.get('price_data') is not None and
            holding_data.get('volume') is not None):
            data_sources['market_data'] = True
        elif 'ibkr' in holding_data.get('data_sources', []):
            data_sources['market_data'] = True

        # 检查期权数据 (Futu)
        if holding_data.get('iv30') is not None:
            data_sources['options_data'] = True
        elif 'futu' in holding_data.get('data_sources', []):
            data_sources['options_data'] = True

        # 检查 Finviz 数据
        if holding_data.get('finviz_metrics') is not None:
            data_sources['finviz'] = True
        elif 'finviz' in holding_data.get('data_sources', []):
            data_sources['finviz'] = True

        # 检查 MarketChameleon 数据
        if holding_data.get('mc_heat_score') is not None:
            data_sources['market_chameleon'] = True
        elif 'mc' in holding_data.get('data_sources', []):
            data_sources['market_chameleon'] = True

        # 计算完整度分数
        completeness_score = 0.0
        for source, weight in self.DATA_SOURCE_WEIGHTS.items():
            if data_sources[source]:
                completeness_score += weight * 100

        # 确定状态
        status = self._get_status(completeness_score)

        # 收集缺失的数据源
        missing_sources = [
            source for source, available in data_sources.items()
            if not available
        ]

        # 获取更新时间
        updated_at = holding_data.get('updated_at')
        if updated_at and not isinstance(updated_at, str):
            updated_at = updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at)

        return HoldingDataStatus(
            ticker=ticker,
            completeness_score=completeness_score,
            status=status,
            data_sources=data_sources,
            missing_sources=missing_sources,
            last_updated=updated_at
        )

    def assess_coverage_range_completeness(
        self,
        etf_symbol: str,
        coverage_type: str,
        coverage_value: int,
        holdings_with_data: List[Dict[str, Any]]
    ) -> CoverageRangeCompleteness:
        """
        评估覆盖范围的整体完整度

        Args:
            etf_symbol: ETF 代码
            coverage_type: 覆盖范围类型 ('top' 或 'weight')
            coverage_value: 覆盖范围值 (10, 15, 60 等)
            holdings_with_data: 持仓数据列表，每项包含:
                {
                    'ticker': 'MSFT',
                    'weight': 5.2,
                    'price_data': <float>,
                    'iv30': <float>,
                    'finviz_metrics': <dict>,
                    'mc_heat_score': <float>,
                    'updated_at': <str>,
                    'data_sources': [<str>]
                }

        Returns:
            CoverageRangeCompleteness: 覆盖范围完整度评估
        """
        if not holdings_with_data:
            return CoverageRangeCompleteness(
                coverage=self._format_coverage_label(coverage_type, coverage_value),
                total_stocks=0,
                complete_count=0,
                pending_count=0,
                missing_count=0,
                average_completeness=0.0,
                holdings_status=[]
            )

        # 计算每只持仓的完整度
        holdings_status = []
        completeness_scores = []

        for holding in holdings_with_data:
            ticker = holding.get('ticker')
            if not ticker:
                continue

            # 计算单只持仓完整度
            status = self.calculate_holding_data_completeness(ticker, holding)
            holdings_status.append(status)
            completeness_scores.append(status.completeness_score)

        # 统计各状态的持仓数
        complete_count = sum(1 for s in holdings_status if s.status == 'complete')
        pending_count = sum(1 for s in holdings_status if s.status == 'pending')
        missing_count = sum(1 for s in holdings_status if s.status == 'missing')

        # 计算平均完整度
        avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0.0

        coverage_label = self._format_coverage_label(coverage_type, coverage_value)

        return CoverageRangeCompleteness(
            coverage=coverage_label,
            total_stocks=len(holdings_status),
            complete_count=complete_count,
            pending_count=pending_count,
            missing_count=missing_count,
            average_completeness=avg_completeness,
            holdings_status=holdings_status
        )

    def _get_status(self, completeness_score: float) -> str:
        """
        根据完整度分数确定状态

        Args:
            completeness_score: 完整度分数 (0-100)

        Returns:
            状态字符串: 'complete' | 'pending' | 'missing'
        """
        if completeness_score >= self.THRESHOLDS['complete']:
            return 'complete'
        elif completeness_score >= self.THRESHOLDS['pending']:
            return 'pending'
        else:
            return 'missing'

    def _format_coverage_label(self, coverage_type: str, coverage_value: int) -> str:
        """
        格式化覆盖范围标签

        Args:
            coverage_type: 'top' 或 'weight'
            coverage_value: 数值

        Returns:
            格式化的标签，如 'top10' 或 'weight70'
        """
        if coverage_type == 'top':
            return f'top{coverage_value}'
        elif coverage_type == 'weight':
            return f'weight{coverage_value}'
        else:
            return f'{coverage_type}{coverage_value}'

    def get_overall_status(self, completeness_score: float) -> str:
        """
        获取整体状态指示器

        Args:
            completeness_score: 完整度分数

        Returns:
            状态字符串
        """
        return self._get_status(completeness_score)
