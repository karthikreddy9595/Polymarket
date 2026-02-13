"""Bot control endpoints."""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException

from ..models.schemas import (
    BotStatusResponse,
    BotControlRequest,
    MarketInfo,
    MarketSearchResponse,
    PaperTradingRequest,
)
from ..trading_bot import get_trading_bot
from ..polymarket_client import get_polymarket_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/scan")
async def scan_markets():
    """Scan for Bitcoin 5-minute price markets (debug endpoint)."""
    client = await get_polymarket_client()

    if not client.is_connected:
        await client.connect()

    markets = await client.find_btc_5min_markets()

    return {
        "count": len(markets),
        "markets": [
            {
                "id": m.get("id") or m.get("conditionId"),
                "question": m.get("question"),
                "time_to_close_minutes": m.get("time_to_close_minutes"),
                "outcomes": m.get("outcomes"),
                "tokens": m.get("tokens", []),
                "end_date": m.get("endDate"),
            }
            for m in markets
        ]
    }


@router.post("/start", response_model=BotStatusResponse)
async def start_bot(request: BotControlRequest = None):
    """Start the trading bot. Auto-discovers Bitcoin Up/Down market if no market_id provided."""
    try:
        bot = get_trading_bot()

        if bot.is_running:
            raise HTTPException(status_code=400, detail="Bot is already running")

        market_id = request.market_id if request else None

        # Auto-discover market if none provided
        if not market_id:
            logger.info("No market_id provided, auto-discovering Bitcoin Up/Down market...")
            client = await get_polymarket_client()
            if not client.is_connected:
                await client.connect()

            markets = await client.find_btc_5min_markets()
            if markets:
                market_id = markets[0].get("id") or markets[0].get("conditionId")
                logger.info(f"Auto-selected market: {market_id}")
            else:
                raise HTTPException(status_code=404, detail="No Bitcoin Up/Down markets found")

        logger.info(f"Starting bot with market_id: {market_id}")

        success, error_msg = await bot.start(market_id=market_id)

        if not success:
            logger.error(f"Failed to start bot: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Failed to start bot: {error_msg}")

        status = await bot.get_status()
        return BotStatusResponse(**status)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error starting bot: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/stop", response_model=BotStatusResponse)
async def stop_bot():
    """Stop the trading bot."""
    bot = get_trading_bot()

    if not bot.is_running:
        raise HTTPException(status_code=400, detail="Bot is not running")

    success = await bot.stop()

    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop bot")

    status = await bot.get_status()
    return BotStatusResponse(**status)


@router.get("/status", response_model=BotStatusResponse)
async def get_bot_status():
    """Get current bot status."""
    bot = get_trading_bot()
    status = await bot.get_status()
    return BotStatusResponse(**status)


@router.post("/paper-trading", response_model=BotStatusResponse)
async def toggle_paper_trading(request: PaperTradingRequest):
    """Enable or disable paper trading mode."""
    bot = get_trading_bot()

    if bot.is_running:
        raise HTTPException(
            status_code=400,
            detail="Cannot change paper trading mode while bot is running"
        )

    await bot.set_paper_trading(request.enabled)
    status = await bot.get_status()
    return BotStatusResponse(**status)


@router.get("/markets", response_model=MarketSearchResponse)
async def search_markets():
    """Search for available Bitcoin 5-minute markets."""
    client = await get_polymarket_client()

    if not client.is_connected:
        await client.connect()

    markets = await client.find_btc_5min_markets()

    market_list = []
    for m in markets:
        tokens = m.get("tokens", [])
        yes_price = None
        no_price = None

        for token in tokens:
            if token.get("outcome") == "Yes":
                price = await client.get_current_price(token.get("token_id"))
                yes_price = price
            elif token.get("outcome") == "No":
                price = await client.get_current_price(token.get("token_id"))
                no_price = price

        try:
            end_date = datetime.fromisoformat(
                m.get("endDate", "").replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            end_date = datetime.utcnow()

        market_list.append(MarketInfo(
            market_id=m.get("id") or m.get("conditionId", ""),
            title=m.get("question", "Unknown"),
            description=m.get("description"),
            end_date=end_date,
            tokens=tokens,
            time_to_close_minutes=m.get("time_to_close_minutes", 0),
            yes_price=yes_price,
            no_price=no_price
        ))

    return MarketSearchResponse(markets=market_list, count=len(market_list))


@router.get("/market/{market_id}", response_model=MarketInfo)
async def get_market_info(market_id: str):
    """Get information about a specific market."""
    client = await get_polymarket_client()

    if not client.is_connected:
        await client.connect()

    market = await client.get_market_info(market_id)

    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    tokens = market.get("tokens", [])
    yes_price = None
    no_price = None

    # Get LIVE prices from CLOB /midpoint API
    for token in tokens:
        token_id = token.get("token_id")
        if token.get("outcome") == "Yes":
            yes_price = await client.get_current_price(token_id)
        elif token.get("outcome") == "No":
            no_price = await client.get_current_price(token_id)

    logger.info(f"[LIVE] Market {market_id}: YES={yes_price}, NO={no_price}")

    try:
        end_date = datetime.fromisoformat(
            market.get("endDate", "").replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        end_date = datetime.utcnow()

    time_to_close = await client.get_time_to_close(market_id)

    return MarketInfo(
        market_id=market_id,
        title=market.get("question", "Unknown"),
        description=market.get("description"),
        end_date=end_date,
        tokens=tokens,
        time_to_close_minutes=time_to_close or 0,
        yes_price=yes_price,
        no_price=no_price
    )
