from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


# Enums
class ETFType(str, Enum):
    SECTOR = "sector"
    INDUSTRY = "industry"


class TaskType(str, Enum):
    ROTATION = "rotation"
    DRILLDOWN = "drilldown"
    MOMENTUM = "momentum"


# Stock Schemas
class StockScores(BaseModel):
    momentum: float
    trend: float
    volume: float
    quality: float
    options: float


class StockChanges(BaseModel):
    delta3d: Optional[float] = None
    delta5d: Optional[float] = None


class StockMetrics(BaseModel):
    return20d: float
    return20dEx3d: Optional[float] = None
    return63d: float
    relativeStrength: Optional[float] = None
    relativeStrengthDiff: Optional[float] = None
    distanceToHigh20d: Optional[float] = None
    volumeMultiple: Optional[float] = None
    maAlignment: Optional[str] = None
    trendPersistence: Optional[float] = None
    breakoutVolume: Optional[float] = None
    volumeRatio: Optional[float] = None
    obvTrend: Optional[str] = None
    maxDrawdown20d: Optional[float] = None
    atrPercent: Optional[float] = None
    deviationFrom20ma: Optional[float] = None
    overheat: Optional[str] = None
    optionsHeat: Optional[str] = None
    optionsRelVolume: Optional[float] = None
    sma20Slope: float
    ivr: float
    iv30: float
    rsi: Optional[float] = None
    beta: Optional[float] = None


class StockBase(BaseModel):
    symbol: str
    name: str
    sector: str
    industry: str
    price: float
    scoreTotal: float
    scores: StockScores
    changes: StockChanges
    metrics: StockMetrics


class StockCreate(StockBase):
    pass


class StockResponse(StockBase):
    id: int

    class Config:
        from_attributes = True


# ETF Schemas
class ETFDelta(BaseModel):
    delta3d: Optional[float] = None
    delta5d: Optional[float] = None


class ETFBase(BaseModel):
    symbol: str
    name: str
    type: ETFType
    score: float
    rank: int
    delta: ETFDelta
    completeness: float
    holdingsCount: int


class ETFCreate(ETFBase):
    pass


class ETFResponse(ETFBase):
    id: int

    class Config:
        from_attributes = True


# Task Schemas
class TaskBase(BaseModel):
    title: str
    type: TaskType
    baseIndex: str
    sector: Optional[str] = None
    etfs: List[str]
    # Phase 4 新增（Node-Centric Drilldown）— 全部可选以保持向后兼容
    rootNode: Optional[str] = None
    viewMode: Optional[str] = None
    selectedNodes: Optional[List[str]] = None
    pinnedEvidenceNodes: Optional[List[str]] = None
    maxDepth: Optional[int] = None


class TaskCreate(TaskBase):
    pass


class TaskEtfsAdd(BaseModel):
    etfs: List[str]
    # 允许追加 ETF 时一并扩展 selected_nodes（可选）
    selectedNodes: Optional[List[str]] = None


class TaskResponse(TaskBase):
    id: int
    createdAt: str

    class Config:
        from_attributes = True
