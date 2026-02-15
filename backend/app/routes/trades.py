"""Trade history endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, Trade, Position
from ..models.schemas import TradeResponse, TradeListResponse

router = APIRouter(prefix="/api/trades", tags=["trades"])


def trade_to_response(trade: Trade, token_to_outcome: dict) -> TradeResponse:
    """Convert Trade model to TradeResponse with outcome."""
    data = {
        "id": trade.id,
        "order_id": trade.order_id,
        "market_id": trade.market_id,
        "token_id": trade.token_id,
        "side": trade.side.value,
        "price": trade.price,
        "size": trade.size,
        "filled_size": trade.filled_size,
        "status": trade.status.value,
        "pnl": trade.pnl,
        "outcome": token_to_outcome.get(trade.token_id, "YES"),  # Default to YES
        "created_at": trade.created_at,
        "updated_at": trade.updated_at,
    }
    return TradeResponse(**data)


@router.get("", response_model=TradeListResponse)
async def get_trades(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    market_id: Optional[str] = Query(None, description="Filter by market ID"),
    exclude_market_id: Optional[str] = Query(None, description="Exclude trades from this market ID (for history)"),
    db: AsyncSession = Depends(get_db)
):
    """Get paginated trade history."""
    # Build query
    query = select(Trade)

    if market_id:
        query = query.where(Trade.market_id == market_id)

    if exclude_market_id:
        query = query.where(Trade.market_id != exclude_market_id)

    # Get total count
    count_query = select(func.count()).select_from(Trade)
    if market_id:
        count_query = count_query.where(Trade.market_id == market_id)
    if exclude_market_id:
        count_query = count_query.where(Trade.market_id != exclude_market_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    offset = (page - 1) * page_size
    query = query.order_by(desc(Trade.created_at)).offset(offset).limit(page_size)

    result = await db.execute(query)
    trades = result.scalars().all()

    # Get all positions to map token_id to outcome
    positions_result = await db.execute(select(Position))
    positions = positions_result.scalars().all()
    token_to_outcome = {p.token_id: p.outcome for p in positions}

    return TradeListResponse(
        trades=[trade_to_response(t, token_to_outcome) for t in trades],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific trade by ID."""
    result = await db.execute(
        select(Trade).where(Trade.id == trade_id)
    )
    trade = result.scalar_one_or_none()

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Get outcome from position
    positions_result = await db.execute(select(Position))
    positions = positions_result.scalars().all()
    token_to_outcome = {p.token_id: p.outcome for p in positions}

    return trade_to_response(trade, token_to_outcome)


@router.get("/order/{order_id}", response_model=TradeResponse)
async def get_trade_by_order_id(
    order_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a trade by its order ID."""
    result = await db.execute(
        select(Trade).where(Trade.order_id == order_id)
    )
    trade = result.scalar_one_or_none()

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Get outcome from position
    positions_result = await db.execute(select(Position))
    positions = positions_result.scalars().all()
    token_to_outcome = {p.token_id: p.outcome for p in positions}

    return trade_to_response(trade, token_to_outcome)
