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
    return63d: float
    sma20Slope: float
    ivr: float
    iv30: float


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


class TaskCreate(TaskBase):
    pass


class TaskResponse(TaskBase):
    id: int
    createdAt: str

    class Config:
        from_attributes = True
