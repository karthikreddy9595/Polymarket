"""Trade analysis endpoints with quant metrics."""

from typing import List, Optional
from datetime import datetime, timedelta
import math
import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, Trade, BotState, Position, Side, OrderStatus
from ..config import get_settings
from ..polymarket_client import get_polymarket_client

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class TradeAnalysisRow(BaseModel):
    """Single trade analysis row."""
    timestamp: str
    security: str  # YES or NO (Up or Down)
    buy_price: Optional[float]
    sell_price: Optional[float]
    profit_loss: float
    cumulative_profit: float
    cumulative_equity: float


class PerformanceMetrics(BaseModel):
    """Quant performance metrics."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_trade_duration: float  # in minutes
    best_trade: float
    worst_trade: float
    current_equity: float
    starting_equity: float
    equity_curve: List[float]
    drawdown_curve: List[float]
    timestamps: List[str]


class AnalysisResponse(BaseModel):
    """Full analysis response."""
    trades: List[TradeAnalysisRow]
    metrics: PerformanceMetrics


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio from returns."""
    if len(returns) < 2:
        return 0.0

    avg_return = sum(returns) / len(returns)
    variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
    std_dev = math.sqrt(variance) if variance > 0 else 0

    if std_dev == 0:
        return 0.0

    return (avg_return - risk_free_rate) / std_dev


def calculate_sortino_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Calculate Sortino ratio (only considers downside deviation)."""
    if len(returns) < 2:
        return 0.0

    avg_return = sum(returns) / len(returns)
    negative_returns = [r for r in returns if r < 0]

    if len(negative_returns) == 0:
        return float('inf') if avg_return > 0 else 0.0

    downside_variance = sum(r ** 2 for r in negative_returns) / len(negative_returns)
    downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0

    if downside_std == 0:
        return 0.0

    return (avg_return - risk_free_rate) / downside_std


def calculate_max_drawdown(equity_curve: List[float]) -> tuple:
    """Calculate maximum drawdown and percentage."""
    if len(equity_curve) < 2:
        return 0.0, 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0

    for equity in equity_curve:
        if equity > peak:
            peak = equity

        drawdown = peak - equity
        drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0

        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = drawdown_pct

    return max_dd, max_dd_pct


@router.get("", response_model=AnalysisResponse)
async def get_analysis(
    db: AsyncSession = Depends(get_db),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    last_n_trades: Optional[int] = Query(None, description="Get last N trades only"),
    security: Optional[str] = Query(None, description="Filter by security (Up/Down)")
):
    """Get comprehensive trade analysis with quant metrics."""
    settings = get_settings()

    # Get bot state for starting balance
    result = await db.execute(select(BotState).limit(1))
    bot_state = result.scalar_one_or_none()

    starting_equity = bot_state.paper_starting_balance if bot_state else 1000.0

    # Use live balance from Polymarket when in live trading mode
    if not settings.paper_trading:
        client = await get_polymarket_client()
        if client.is_connected:
            live_balance = await client.get_balance()
            current_equity = live_balance if live_balance is not None else starting_equity
        else:
            current_equity = starting_equity
    else:
        current_equity = bot_state.paper_balance if bot_state else starting_equity

    # Build query with filters
    query = select(Trade).where(Trade.status == OrderStatus.FILLED)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.where(Trade.created_at >= start_dt)
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.where(Trade.created_at < end_dt)
        except ValueError:
            pass

    query = query.order_by(Trade.created_at)
    result = await db.execute(query)
    all_trades = list(result.scalars().all())

    # Get all positions to map token_id to outcome
    result = await db.execute(select(Position))
    all_positions = list(result.scalars().all())
    token_to_outcome = {p.token_id: p.outcome for p in all_positions}

    # Group trades into buy-sell pairs to calculate P&L
    trade_rows: List[TradeAnalysisRow] = []
    equity_curve: List[float] = [starting_equity]
    drawdown_curve: List[float] = [0.0]
    timestamps: List[str] = ["Start"]
    returns: List[float] = []

    cumulative_profit = 0.0
    equity = starting_equity

    # Track open positions for pairing
    open_positions = {}  # token_id -> (buy_trade, outcome)

    winning_trades = 0
    losing_trades = 0
    total_profit = 0.0
    total_loss = 0.0
    best_trade = 0.0
    worst_trade = 0.0

    for trade in all_trades:
        token_id = trade.token_id

        if trade.side == Side.BUY:
            # Opening a position
            # Get outcome from position mapping, default to "Up"
            outcome = token_to_outcome.get(token_id, "Up")
            open_positions[token_id] = (trade, outcome)

        elif trade.side == Side.SELL:
            # Closing a position
            if token_id in open_positions:
                buy_trade, outcome = open_positions[token_id]
                del open_positions[token_id]

                # Calculate P&L
                pnl = (trade.price - buy_trade.price) * trade.size
                cumulative_profit += pnl
                equity += pnl

                # Track returns for Sharpe calculation
                if buy_trade.price > 0:
                    trade_return = (trade.price - buy_trade.price) / buy_trade.price
                    returns.append(trade_return)

                # Track wins/losses
                if pnl > 0:
                    winning_trades += 1
                    total_profit += pnl
                    if pnl > best_trade:
                        best_trade = pnl
                else:
                    losing_trades += 1
                    total_loss += abs(pnl)
                    if pnl < worst_trade:
                        worst_trade = pnl

                # Add to trade rows
                trade_rows.append(TradeAnalysisRow(
                    timestamp=trade.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    security=outcome,
                    buy_price=buy_trade.price,
                    sell_price=trade.price,
                    profit_loss=round(pnl, 4),
                    cumulative_profit=round(cumulative_profit, 4),
                    cumulative_equity=round(equity, 4)
                ))

                # Update curves
                equity_curve.append(equity)
                timestamps.append(trade.created_at.strftime("%H:%M:%S"))

    # Calculate drawdown curve
    peak = equity_curve[0]
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        drawdown_curve.append(peak - eq)

    # Calculate metrics
    total_trades = winning_trades + losing_trades
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    avg_profit = (total_profit / winning_trades) if winning_trades > 0 else 0.0
    avg_loss = (total_loss / losing_trades) if losing_trades > 0 else 0.0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf') if total_profit > 0 else 0.0

    max_dd, max_dd_pct = calculate_max_drawdown(equity_curve)
    sharpe = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)

    # Estimate avg trade duration (placeholder - would need entry/exit timestamps)
    avg_duration = 2.5  # Default 2.5 minutes for 5-min markets

    metrics = PerformanceMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=round(win_rate, 2),
        total_pnl=round(cumulative_profit, 4),
        avg_profit=round(avg_profit, 4),
        avg_loss=round(avg_loss, 4),
        profit_factor=round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
        max_drawdown=round(max_dd, 4),
        max_drawdown_pct=round(max_dd_pct, 2),
        sharpe_ratio=round(sharpe, 2),
        sortino_ratio=round(sortino, 2) if sortino != float('inf') else 999.99,
        avg_trade_duration=avg_duration,
        best_trade=round(best_trade, 4),
        worst_trade=round(worst_trade, 4),
        current_equity=round(current_equity, 4),
        starting_equity=round(starting_equity, 4),
        equity_curve=[round(e, 2) for e in equity_curve],
        drawdown_curve=[round(d, 2) for d in drawdown_curve],
        timestamps=timestamps
    )

    return AnalysisResponse(
        trades=trade_rows,
        metrics=metrics
    )


@router.get("/summary")
async def get_quick_summary(
    db: AsyncSession = Depends(get_db)
):
    """Get quick summary stats."""
    settings = get_settings()

    result = await db.execute(select(BotState).limit(1))
    bot_state = result.scalar_one_or_none()

    if not bot_state:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "current_balance": 1000.0
        }

    # Use live balance when in live trading mode
    if not settings.paper_trading:
        client = await get_polymarket_client()
        if client.is_connected:
            live_balance = await client.get_balance()
            current_balance = live_balance if live_balance is not None else bot_state.paper_balance
        else:
            current_balance = bot_state.paper_balance
    else:
        current_balance = bot_state.paper_balance

    total = bot_state.wins + bot_state.losses
    win_rate = (bot_state.wins / total * 100) if total > 0 else 0

    return {
        "total_trades": bot_state.trades_count,
        "wins": bot_state.wins,
        "losses": bot_state.losses,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(bot_state.total_pnl, 4),
        "current_balance": round(current_balance, 4)
    }


@router.get("/export")
async def export_trades(
    db: AsyncSession = Depends(get_db),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    format: str = Query("csv", description="Export format: csv or xlsx")
):
    """Export trade data to CSV/Excel."""
    settings = get_settings()

    # Get bot state for starting balance
    result = await db.execute(select(BotState).limit(1))
    bot_state = result.scalar_one_or_none()

    # Use live balance for starting equity when in live trading mode
    if not settings.paper_trading:
        client = await get_polymarket_client()
        if client.is_connected:
            live_balance = await client.get_balance()
            starting_equity = live_balance if live_balance is not None else (bot_state.paper_starting_balance if bot_state else 1000.0)
        else:
            starting_equity = bot_state.paper_starting_balance if bot_state else 1000.0
    else:
        starting_equity = bot_state.paper_starting_balance if bot_state else 1000.0

    # Build query with filters
    query = select(Trade).where(Trade.status == OrderStatus.FILLED)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.where(Trade.created_at >= start_dt)
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.where(Trade.created_at < end_dt)
        except ValueError:
            pass

    query = query.order_by(Trade.created_at)
    result = await db.execute(query)
    all_trades = list(result.scalars().all())

    # Get positions for outcome mapping
    result = await db.execute(select(Position))
    all_positions = list(result.scalars().all())
    token_to_outcome = {p.token_id: p.outcome for p in all_positions}

    # Process trades into rows
    rows = []
    open_positions = {}
    cumulative_profit = 0.0
    equity = starting_equity

    for trade in all_trades:
        token_id = trade.token_id

        if trade.side == Side.BUY:
            outcome = token_to_outcome.get(token_id, "Up")
            open_positions[token_id] = (trade, outcome)
        elif trade.side == Side.SELL:
            if token_id in open_positions:
                buy_trade, outcome = open_positions[token_id]
                del open_positions[token_id]

                pnl = (trade.price - buy_trade.price) * trade.size
                cumulative_profit += pnl
                equity += pnl

                rows.append({
                    "Timestamp": trade.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "Security": outcome,
                    "Buy Price": round(buy_trade.price, 4),
                    "Sell Price": round(trade.price, 4),
                    "Size": round(trade.size, 4),
                    "P&L": round(pnl, 4),
                    "Cumulative P&L": round(cumulative_profit, 4),
                    "Equity": round(equity, 4),
                    "Result": "WIN" if pnl > 0 else "LOSS"
                })

    # Generate CSV
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("No trades found")

    output.seek(0)

    filename = f"trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
