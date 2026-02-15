"""Database models and setup using SQLAlchemy with async SQLite."""

import os
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import enum

from .config import get_settings


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class OrderStatus(enum.Enum):
    """Order status enumeration."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Side(enum.Enum):
    """Trade side enumeration."""
    BUY = "buy"
    SELL = "sell"


class Trade(Base):
    """Trade record model."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, index=True)
    market_id = Column(String(100), index=True)
    market_name = Column(String(500), nullable=True)  # Market title/question
    token_id = Column(String(100))
    side = Column(SQLEnum(Side))
    price = Column(Float)
    size = Column(Float)
    filled_size = Column(Float, default=0.0)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    pnl = Column(Float, default=0.0)
    is_paper = Column(Boolean, default=False)  # Paper trade flag
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Trade {self.order_id} {self.side.value} {self.size}@{self.price} paper={self.is_paper}>"


class Position(Base):
    """Position tracking model."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(100), index=True)
    token_id = Column(String(100), unique=True, index=True)
    outcome = Column(String(10))  # YES or NO
    quantity = Column(Float, default=0.0)
    avg_price = Column(Float, default=0.0)
    current_price = Column(Float, default=0.0)
    current_pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Position {self.outcome} qty={self.quantity} pnl={self.current_pnl}>"


class BotState(Base):
    """Bot state persistence model."""
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    is_running = Column(Boolean, default=False)
    current_market_id = Column(String(100), nullable=True)
    last_action = Column(String(200), nullable=True)
    total_pnl = Column(Float, default=0.0)
    trades_count = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    # Paper trading fields
    paper_trading = Column(Boolean, default=True)
    paper_balance = Column(Float, default=1000.0)
    paper_starting_balance = Column(Float, default=1000.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<BotState running={self.is_running} pnl={self.total_pnl} paper={self.paper_trading}>"


# Database engine and session setup
settings = get_settings()

# Ensure data directory exists
def get_database_url() -> str:
    """Get database URL, ensuring the directory exists."""
    db_url = settings.database_url

    # Extract path from sqlite URL
    if "sqlite" in db_url:
        # Parse the path from URL like sqlite+aiosqlite:///./data/trades.db
        path_part = db_url.split("///")[-1]

        # Convert to absolute path
        if path_part.startswith("./"):
            base_dir = Path(__file__).parent.parent  # backend directory
            db_path = base_dir / path_part[2:]
        else:
            db_path = Path(path_part)

        # Create directory if it doesn't exist
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Return URL with absolute path
        return f"sqlite+aiosqlite:///{db_path.absolute()}"

    return db_url

engine = create_async_engine(
    get_database_url(),
    echo=False,
    future=True
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db() -> None:
    """Initialize the database and create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_or_create_bot_state(session: AsyncSession) -> BotState:
    """Get the current bot state or create a new one."""
    from sqlalchemy import select

    result = await session.execute(select(BotState).limit(1))
    bot_state = result.scalar_one_or_none()

    if bot_state is None:
        bot_state = BotState()
        session.add(bot_state)
        await session.commit()
        await session.refresh(bot_state)

    return bot_state
