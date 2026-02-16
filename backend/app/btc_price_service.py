"""
Bitcoin price service for Polymarket trading.

Fetches:
1. "Market open" price (reference price) when market starts
2. Live BTC price from Polymarket WebSocket (Chainlink BTC/USD feed)

Calculates price difference to filter order placement.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)


class BTCPriceService:
    """
    Bitcoin price service using Polymarket data sources.
    - Market open price: Captured at market start
    - Live BTC price: From Polymarket WebSocket (Chainlink feed)
    """

    POLYMARKET_WS_URL = "wss://ws-live-data.polymarket.com"
    POLYMARKET_BASE_URL = "https://polymarket.com"

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._live_btc_price: Optional[float] = None
        self._price_to_beat: Optional[float] = None
        self._current_market_slug: Optional[str] = None
        self._last_price_update: Optional[datetime] = None
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Initialize the service."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._running = True
        logger.info("BTC Price Service started")

    async def stop(self) -> None:
        """Stop the service and cleanup."""
        self._running = False

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        logger.info("BTC Price Service stopped")

    async def _ensure_session(self) -> None:
        """Ensure HTTP session is available."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def fetch_price_to_beat(self, market_slug: str) -> Optional[float]:
        """
        Capture the "market open price" by fetching the live BTC price at market start.

        Args:
            market_slug: Market slug like "btc-updown-5m-1771218300"

        Returns:
            The reference BTC price or None if not found
        """
        # Wait 0.5 seconds to capture price at market start
        await asyncio.sleep(0.5)

        live_price = await self.get_live_btc_price()

        if live_price:
            self._price_to_beat = live_price
            self._current_market_slug = market_slug
            logger.info(f"[BTC] Captured market open price: ${live_price:,.2f} for {market_slug}")
            return live_price
        else:
            logger.warning(f"[BTC] Could not capture market open price for {market_slug}")
            return None

    async def connect_websocket(self) -> bool:
        """
        Connect to Polymarket WebSocket for live BTC prices.

        Returns:
            True if connected successfully
        """
        await self._ensure_session()

        try:
            self._ws = await self._session.ws_connect(
                self.POLYMARKET_WS_URL,
                heartbeat=30
            )

            # Subscribe to Chainlink BTC/USD price feed
            subscribe_msg = {
                "action": "subscribe",
                "subscriptions": [
                    {
                        "topic": "crypto_prices_chainlink",
                        "type": "*",
                        "filters": json.dumps({"symbol": "btc/usd"})
                    }
                ]
            }

            await self._ws.send_json(subscribe_msg)
            logger.info("[BTC] Connected to Polymarket WebSocket for BTC/USD prices")

            # Start listening for price updates in background
            self._ws_task = asyncio.create_task(self._listen_websocket())

            return True

        except Exception as e:
            logger.error(f"[BTC] Failed to connect WebSocket: {e}")
            return False

    async def _listen_websocket(self) -> None:
        """Listen for WebSocket price updates."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get("topic") == "crypto_prices_chainlink":
                            payload = data.get("payload", {})
                            if payload.get("symbol") == "btc/usd":
                                price = payload.get("value")
                                if price:
                                    self._live_btc_price = float(price)
                                    self._last_price_update = datetime.utcnow()
                    except json.JSONDecodeError:
                        pass

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning("[BTC] WebSocket closed or error")
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[BTC] WebSocket error: {e}")

    async def get_live_btc_price(self) -> Optional[float]:
        """
        Get live BTC price. Uses WebSocket price if available,
        otherwise falls back to HTTP request.

        Returns:
            Current BTC price or None
        """
        # Try WebSocket price first (most up to date)
        if self._live_btc_price and self._last_price_update:
            age = (datetime.utcnow() - self._last_price_update).total_seconds()
            if age < 30:  # Price is fresh (< 30 seconds old)
                return self._live_btc_price

        # Fallback: fetch from Binance API (reliable and fast)
        await self._ensure_session()

        try:
            url = "https://api.binance.com/api/v3/ticker/price"
            params = {"symbol": "BTCUSDT"}
            timeout = aiohttp.ClientTimeout(total=5)

            async with self._session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data.get("price", 0))
                    self._live_btc_price = price
                    self._last_price_update = datetime.utcnow()
                    return price
        except Exception as e:
            logger.error(f"[BTC] Error fetching live price: {e}")

        return self._live_btc_price  # Return cached price if available

    async def get_price_difference(self) -> Optional[float]:
        """
        Calculate the difference between live BTC price and market open price.

        Returns:
            Price difference (live - price_to_beat) or None if data unavailable
        """
        if self._price_to_beat is None:
            logger.warning("[BTC] Market open price not set")
            return None

        live_price = await self.get_live_btc_price()
        if live_price is None:
            logger.warning("[BTC] Could not get live price")
            return None

        difference = live_price - self._price_to_beat

        logger.debug(
            f"[BTC] Live: ${live_price:,.2f} | "
            f"Market open: ${self._price_to_beat:,.2f} | "
            f"Diff: ${difference:+,.2f}"
        )

        return difference

    async def should_place_order(self, min_difference: float = 10.0) -> tuple[bool, Dict[str, Any]]:
        """
        Check if order should be placed based on BTC price movement.

        Args:
            min_difference: Minimum absolute price difference required (default $10)

        Returns:
            Tuple of (should_place: bool, price_info: dict with details)
        """
        live_price = await self.get_live_btc_price()

        if self._price_to_beat is None:
            return False, {
                "error": "Market open price not set",
                "live_price": live_price,
                "price_to_beat": None
            }

        if live_price is None:
            return False, {
                "error": "Could not fetch live BTC price",
                "live_price": None,
                "price_to_beat": self._price_to_beat
            }

        difference = live_price - self._price_to_beat
        abs_difference = abs(difference)
        should_place = abs_difference >= min_difference

        price_info = {
            "live_price": live_price,
            "price_to_beat": self._price_to_beat,
            "difference": difference,
            "abs_difference": abs_difference,
            "min_required": min_difference,
            "should_place": should_place,
            "direction": "UP" if difference > 0 else "DOWN" if difference < 0 else "FLAT"
        }

        if should_place:
            logger.info(
                f"[BTC] Order ALLOWED: |${abs_difference:,.2f}| >= ${min_difference:,.2f} "
                f"({price_info['direction']})"
            )
        else:
            logger.info(
                f"[BTC] Order BLOCKED: |${abs_difference:,.2f}| < ${min_difference:,.2f}"
            )

        return should_place, price_info

    def set_price_to_beat(self, price: float, market_slug: str) -> None:
        """
        Manually set the market open price.

        Args:
            price: The reference BTC price
            market_slug: The market slug this price belongs to
        """
        self._price_to_beat = price
        self._current_market_slug = market_slug
        logger.info(f"[BTC] Market open price set: ${price:,.2f} for {market_slug}")

    def clear_price_to_beat(self) -> None:
        """Clear the stored market open price (for new market)."""
        self._price_to_beat = None
        self._current_market_slug = None
        logger.info("[BTC] Market open price cleared")

    @property
    def price_to_beat(self) -> Optional[float]:
        """Get the current market open price."""
        return self._price_to_beat

    @property
    def current_market_slug(self) -> Optional[str]:
        """Get the current market slug."""
        return self._current_market_slug

    @property
    def live_price(self) -> Optional[float]:
        """Get the cached live BTC price."""
        return self._live_btc_price


# Singleton instance
_btc_service: Optional[BTCPriceService] = None


async def get_btc_price_service() -> BTCPriceService:
    """Get or create the BTC price service singleton."""
    global _btc_service
    if _btc_service is None:
        _btc_service = BTCPriceService()
        await _btc_service.start()
    return _btc_service
