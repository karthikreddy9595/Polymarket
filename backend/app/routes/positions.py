"""Position and P&L endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, Position, get_or_create_bot_state
from ..models.schemas import PositionResponse, PnLSummary

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("", response_model=list[PositionResponse])
async def get_positions(
    market_id: Optional[str] = Query(None, description="Filter by market ID"),
    db: AsyncSession = Depends(get_db)
):
    """Get all current positions."""
    query = select(Position)

    if market_id:
        query = query.where(Position.market_id == market_id)

    # Only show positions with quantity > 0
    query = query.where(Position.quantity > 0)

    result = await db.execute(query)
    positions = result.scalars().all()

    return [PositionResponse.model_validate(p) for p in positions]


@router.get("/pnl", response_model=PnLSummary)
async def get_pnl_summary(
    db: AsyncSession = Depends(get_db)
):
    """Get P&L summary using BotState values (updated by trading bot)."""
    # Get bot state - this is the source of truth for P&L and win/loss stats
    bot_state = await get_or_create_bot_state(db)

    # Get all positions for display
    positions_result = await db.execute(
        select(Position).where(Position.quantity > 0)
    )
    positions = positions_result.scalars().all()

    # Use BotState values - these are properly updated by the trading bot
    total_pnl = bot_state.total_pnl
    winning_trades = bot_state.wins
    losing_trades = bot_state.losses
    total_trades = bot_state.trades_count

    # Calculate win rate from BotState values
    total_completed = winning_trades + losing_trades
    win_rate = (winning_trades / total_completed * 100) if total_completed > 0 else 0.0

    return PnLSummary(
        total_pnl=total_pnl,
        realized_pnl=total_pnl,  # For compatibility - all P&L from completed trades
        unrealized_pnl=0.0,  # Not tracking unrealized separately anymore
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        positions=[PositionResponse.model_validate(p) for p in positions]
    )


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific position by ID."""
    result = await db.execute(
        select(Position).where(Position.id == position_id)
    )
    position = result.scalar_one_or_none()

    if not position:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Position not found")

    return PositionResponse.model_validate(position)
