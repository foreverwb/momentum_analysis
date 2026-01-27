from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, 
    ForeignKey, Enum, JSON, Date, BigInteger, Boolean, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import enum

SQLALCHEMY_DATABASE_URL = "sqlite:///./momentum_radar.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class ETFType(enum.Enum):
    SECTOR = "sector"
    INDUSTRY = "industry"


class TaskType(enum.Enum):
    ROTATION = "rotation"
    DRILLDOWN = "drilldown"
    MOMENTUM = "momentum"


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True)
    name = Column(String)
    sector = Column(String)
    industry = Column(String)
    price = Column(Float)
    score_total = Column(Float)
    
    # Scores JSON: {momentum, trend, volume, quality, options}
    scores = Column(JSON)
    
    # Changes JSON: {delta3d, delta5d}
    changes = Column(JSON)
    
    # Metrics JSON: {return20d, return63d, sma20Slope, ivr, iv30}
    metrics = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ETF(Base):
    __tablename__ = "etfs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True)
    name = Column(String)
    type = Column(String)  # 'sector' or 'industry'
    score = Column(Float)
    rank = Column(Integer)
    
    # Delta JSON: {delta3d, delta5d}
    delta = Column(JSON)
    
    completeness = Column(Float)
    holdings_count = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    type = Column(String)  # 'rotation', 'drilldown', 'momentum'
    base_index = Column(String)
    sector = Column(String, nullable=True)
    
    # ETFs JSON array
    etfs = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============ 新增表结构 (Task 1) ============

class PriceHistory(Base):
    """历史价格数据表"""
    __tablename__ = 'price_history'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    source = Column(String(20), default='ibkr')  # ibkr/futu/yfinance
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('symbol', 'date', name='uix_price_symbol_date'),
    )


class IVData(Base):
    """期权 IV 数据表"""
    __tablename__ = 'iv_data'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    iv7 = Column(Float)
    iv30 = Column(Float)
    iv60 = Column(Float)
    iv90 = Column(Float)
    total_oi = Column(BigInteger)
    delta_oi_1d = Column(BigInteger)
    source = Column(String(20), default='futu')
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('symbol', 'date', name='uix_iv_symbol_date'),
    )


class ImportedData(Base):
    """用户导入数据表 (Finviz/MarketChameleon等)"""
    __tablename__ = 'imported_data'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    source = Column(String(50), nullable=False)  # finviz/marketchameleon
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('symbol', 'date', 'source', name='uix_import_symbol_date_source'),
    )


class ScoreSnapshot(Base):
    """评分快照表"""
    __tablename__ = 'score_snapshots'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    symbol_type = Column(String(10), nullable=False)  # etf/stock
    date = Column(Date, nullable=False, index=True)
    total_score = Column(Float)
    score_breakdown = Column(JSON)  # 各维度评分详情
    thresholds_pass = Column(Boolean, default=True)  # 是否通过阈值检查
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('symbol', 'symbol_type', 'date', name='uix_score_symbol_type_date'),
    )


class BrokerStatus(Base):
    """Broker 连接状态表"""
    __tablename__ = 'broker_status'
    
    id = Column(Integer, primary_key=True)
    broker_type = Column(String(20), nullable=False, unique=True)  # ibkr/futu
    is_connected = Column(Boolean, default=False)
    last_connected_at = Column(DateTime)
    last_error = Column(String(500))
    config = Column(JSON)  # 存储连接配置


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)