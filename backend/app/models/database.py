from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    ForeignKey, Enum, JSON, Date, BigInteger, Boolean, UniqueConstraint, Text,
    inspect, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, date
import enum
import re
import logging

logger = logging.getLogger(__name__)

SQLALCHEMY_DATABASE_URL = "sqlite:///./momentum_radar.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ============ 默认板块 ETF 配置 ============

DEFAULT_SECTOR_ETFS = [
    {"symbol": "XLK", "name": "Technology Select Sector SPDR", "type": "sector"},
    {"symbol": "XLC", "name": "Communication Services Select Sector SPDR", "type": "sector"},
    {"symbol": "XLY", "name": "Consumer Discretionary Select Sector SPDR", "type": "sector"},
    {"symbol": "XLP", "name": "Consumer Staples Select Sector SPDR", "type": "sector"},
    {"symbol": "XLV", "name": "Health Care Select Sector SPDR", "type": "sector"},
    {"symbol": "XLF", "name": "Financial Select Sector SPDR", "type": "sector"},
    {"symbol": "XLI", "name": "Industrial Select Sector SPDR", "type": "sector"},
    {"symbol": "XLE", "name": "Energy Select Sector SPDR", "type": "sector"},
    {"symbol": "XLU", "name": "Utilities Select Sector SPDR", "type": "sector"},
    {"symbol": "XLRE", "name": "Real Estate Select Sector SPDR", "type": "sector"},
    {"symbol": "XLB", "name": "Materials Select Sector SPDR", "type": "sector"},
]

# 有效的板块 ETF 符号列表
VALID_SECTOR_SYMBOLS = [etf["symbol"] for etf in DEFAULT_SECTOR_ETFS]


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
    sector = Column(String, index=True)
    industry = Column(String)
    price = Column(Float)
    score_total = Column(Float)
    
    # Scores JSON: {momentum, trend, volume, quality, options}
    scores = Column(JSON)
    
    # Changes JSON: {delta3d, delta5d}
    changes = Column(JSON)
    
    # Metrics JSON: {return20d, return63d, sma20Slope, ivr, iv30}
    metrics = Column(JSON)
    
    # 热度标签相关
    heat_type = Column(String, default='normal', index=True)  # 'trend', 'event', 'hedge', 'normal'
    heat_score = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    
    # 门槛检查
    thresholds_pass = Column(Boolean, default=True)
    thresholds = Column(JSON, default=dict)  # {'price_above_sma50': 'PASS', 'rs_positive': 'PASS'}
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ETF(Base):
    __tablename__ = "etfs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True)
    name = Column(String)
    type = Column(String)  # 'sector' or 'industry'
    parent_sector = Column(String, nullable=True)  # 行业 ETF 所属板块
    score = Column(Float, default=0.0)
    rank = Column(Integer, default=0)
    
    # Delta JSON: {delta3d, delta5d}
    delta = Column(JSON, default=dict)
    
    completeness = Column(Float, default=0.0)
    holdings_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联持仓
    holdings = relationship("ETFHolding", back_populates="etf", cascade="all, delete-orphan")


class ETFHolding(Base):
    """ETF 持仓数据表"""
    __tablename__ = "etf_holdings"

    id = Column(Integer, primary_key=True, index=True)
    etf_id = Column(Integer, ForeignKey("etfs.id"), nullable=False, index=True)
    etf_symbol = Column(String, nullable=False, index=True)
    ticker = Column(String, nullable=False, index=True)
    weight = Column(Float, nullable=False)
    data_date = Column(Date, nullable=False, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联 ETF
    etf = relationship("ETF", back_populates="holdings")
    
    __table_args__ = (
        UniqueConstraint('etf_symbol', 'ticker', 'data_date', name='uix_holding_etf_ticker_date'),
    )


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


class MarketRegimeSnapshot(Base):
    """市场环境每日快照表"""
    __tablename__ = 'market_regime_snapshots'

    id = Column(Integer, primary_key=True)
    snapshot_date = Column(Date, nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False)
    regime_text = Column(String(50), nullable=True)
    spy = Column(JSON, nullable=True)
    vix = Column(Float, nullable=True)
    indicators = Column(JSON, nullable=True)
    error = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrokerStatus(Base):
    """Broker 连接状态表"""
    __tablename__ = 'broker_status'
    
    id = Column(Integer, primary_key=True)
    broker_type = Column(String(20), nullable=False, unique=True)  # ibkr/futu
    is_connected = Column(Boolean, default=False)
    last_connected_at = Column(DateTime)
    last_error = Column(String(500))
    config = Column(JSON)  # 存储连接配置


class HoldingsUploadLog(Base):
    """Holdings 上传记录表"""
    __tablename__ = 'holdings_upload_logs'
    
    id = Column(Integer, primary_key=True)
    etf_symbol = Column(String(20), nullable=False, index=True)
    etf_type = Column(String(20), nullable=False)  # sector / industry
    data_date = Column(Date, nullable=False, index=True)
    file_name = Column(String(255))
    records_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    status = Column(String(20), default='success')  # success / error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('etf_symbol', 'data_date', name='uix_upload_etf_date'),
    )


# ============ 辅助函数 ============

def is_valid_ticker(ticker: str) -> bool:
    """
    验证 Ticker 是否有效
    - 不为空
    - 只包含英文字母(可能带数字，如 BRK.B)
    """
    if not ticker or not isinstance(ticker, str):
        return False
    ticker = ticker.strip()
    if not ticker:
        return False
    # 允许字母、数字、点号和短横线
    pattern = r'^[A-Za-z][A-Za-z0-9.\-]*$'
    return bool(re.match(pattern, ticker))


def is_valid_sector_symbol(symbol: str) -> bool:
    """验证是否为有效的板块 ETF 符号"""
    return symbol.upper() in VALID_SECTOR_SYMBOLS


# ============ 数据库操作函数 ============

def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)
    _ensure_etfs_parent_sector_column()
    _ensure_stocks_heat_columns()
    logger.info("数据库表已创建")


def _ensure_etfs_parent_sector_column():
    """为旧版 SQLite 数据库补齐缺失列"""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "etfs" not in inspector.get_table_names():
        return
    column_names = {col["name"] for col in inspector.get_columns("etfs")}
    if "parent_sector" not in column_names:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE etfs ADD COLUMN parent_sector VARCHAR"))
        logger.info("已补齐列: etfs.parent_sector")


def _ensure_stocks_heat_columns():
    """为旧版 SQLite 数据库补齐 stocks 表的热度相关列"""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "stocks" not in inspector.get_table_names():
        return
    
    column_names = {col["name"] for col in inspector.get_columns("stocks")}
    
    # 需要添加的新列及其默认值
    new_columns = [
        ("heat_type", "VARCHAR", "'normal'"),
        ("heat_score", "FLOAT", "0.0"),
        ("risk_score", "FLOAT", "0.0"),
        ("thresholds_pass", "BOOLEAN", "1"),
        ("thresholds", "JSON", "'{}'"),
    ]
    
    with engine.begin() as conn:
        for col_name, col_type, default_value in new_columns:
            if col_name not in column_names:
                sql = f"ALTER TABLE stocks ADD COLUMN {col_name} {col_type} DEFAULT {default_value}"
                conn.execute(text(sql))
                logger.info(f"已补齐列: stocks.{col_name}")


def init_default_sector_etfs():
    """初始化默认的 11 个板块 ETF"""
    db = SessionLocal()
    try:
        for etf_data in DEFAULT_SECTOR_ETFS:
            existing = db.query(ETF).filter(ETF.symbol == etf_data["symbol"]).first()
            if not existing:
                etf = ETF(
                    symbol=etf_data["symbol"],
                    name=etf_data["name"],
                    type=etf_data["type"],
                    score=0.0,
                    rank=0,
                    delta={"delta3d": None, "delta5d": None},
                    completeness=0.0,
                    holdings_count=0
                )
                db.add(etf)
                logger.info(f"初始化板块 ETF: {etf_data['symbol']}")
        
        db.commit()
        logger.info(f"已初始化 {len(DEFAULT_SECTOR_ETFS)} 个默认板块 ETF")
    except Exception as e:
        db.rollback()
        logger.error(f"初始化板块 ETF 失败: {e}")
        raise
    finally:
        db.close()
