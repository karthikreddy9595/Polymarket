"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class OrderStatusEnum(str, Enum):
    """Order status enumeration."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SideEnum(str, Enum):
    """Trade side enumeration."""
    BUY = "buy"
    SELL = "sell"


class TradeResponse(BaseModel):
    """Trade response schema."""
    id: int
    order_id: str
    market_id: str
    token_id: str
    side: SideEnum
    price: float
    size: float
    filled_size: float
    status: OrderStatusEnum
    pnl: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeListResponse(BaseModel):
    """Paginated trade list response."""
    trades: List[TradeResponse]
    total: int
    page: int
    page_size: int


class PositionResponse(BaseModel):
    """Position response schema."""
    id: int
    market_id: str
    token_id: str
    outcome: str
    quantity: float
    avg_price: float
    current_price: float
    current_pnl: float
    updated_at: datetime

    class Config:
        from_attributes = True


class BotStatusResponse(BaseModel):
    """Bot status response schema."""
    is_running: bool
    current_market_id: Optional[str] = None
    last_action: Optional[str] = None
    total_pnl: float
    trades_count: int
    wins: int
    losses: int
    updated_at: datetime
    time_to_close: Optional[float] = None  # Minutes remaining
    paper_trading: bool = True
    paper_balance: float = 1000.0
    paper_starting_balance: float = 1000.0
    live_balance: Optional[float] = None  # Live USDC balance from Polymarket

    class Config:
        from_attributes = True


class BotControlRequest(BaseModel):
    """Bot control request schema."""
    market_id: Optional[str] = Field(
        None,
        description="Optional specific market ID to trade. If not provided, bot will auto-discover markets."
    )


class PaperTradingRequest(BaseModel):
    """Paper trading toggle request schema."""
    enabled: bool = Field(
        ...,
        description="Enable or disable paper trading mode"
    )


class MarketInfo(BaseModel):
    """Market information schema."""
    market_id: str
    title: str
    description: Optional[str] = None
    end_date: datetime
    tokens: List[dict]
    time_to_close_minutes: float
    yes_price: Optional[float] = None
    no_price: Optional[float] = None


class MarketSearchResponse(BaseModel):
    """Market search response schema."""
    markets: List[MarketInfo]
    count: int


class PnLSummary(BaseModel):
    """P&L summary schema."""
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    positions: List[PositionResponse]


class OrderRequest(BaseModel):
    """Order request schema for manual orders."""
    market_id: str
    token_id: str
    side: SideEnum
    price: float
    size: float


class OrderResponse(BaseModel):
    """Order response schema."""
    success: bool
    order_id: Optional[str] = None
    message: str


class HealthResponse(BaseModel):
    """Health check response schema."""
    status: str
    database: str
    polymarket_connected: bool
    timestamp: datetime
