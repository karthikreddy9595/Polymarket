"""Position and P&L endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, Position, Trade, BotState, OrderStatus, get_or_create_bot_state
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
    """Get P&L summary including realized and unrealized P&L."""
    # Get bot state for totals
    bot_state = await get_or_create_bot_state(db)

    # Calculate realized P&L from closed trades
    realized_query = select(func.sum(Trade.pnl)).where(
        Trade.status == OrderStatus.FILLED
    )
    realized_result = await db.execute(realized_query)
    realized_pnl = realized_result.scalar() or 0.0

    # Get all positions for unrealized P&L
    positions_result = await db.execute(
        select(Position).where(Position.quantity > 0)
    )
    positions = positions_result.scalars().all()

    unrealized_pnl = sum(p.current_pnl for p in positions)
    total_pnl = realized_pnl + unrealized_pnl

    # Get trade statistics
    trades_count_result = await db.execute(select(func.count()).select_from(Trade))
    total_trades = trades_count_result.scalar() or 0

    winning_result = await db.execute(
        select(func.count()).select_from(Trade).where(Trade.pnl > 0)
    )
    winning_trades = winning_result.scalar() or 0

    losing_result = await db.execute(
        select(func.count()).select_from(Trade).where(Trade.pnl < 0)
    )
    losing_trades = losing_result.scalar() or 0

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    return PnLSummary(
        total_pnl=total_pnl,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
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
