"""Async wrapper for Polymarket CLOB client with real-time WebSocket price streaming."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Callable, Set
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import aiohttp
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from .config import get_settings

logger = logging.getLogger(__name__)


class LivePriceStream:
    """
    Real-time price streaming via WebSocket - NO CACHING.
    Fetches live prices on every request.
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._callbacks: List[Callable[[str, float], None]] = []
        self._running = False

    async def start(self) -> None:
        """Start the price stream."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._running = True
        logger.info("Live price stream started")

    async def stop(self) -> None:
        """Stop the price stream."""
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("Live price stream stopped")

    def add_callback(self, callback: Callable[[str, float], None]) -> None:
        """Add a callback for price updates."""
        self._callbacks.append(callback)

    async def get_live_price(self, token_id: str) -> Optional[float]:
        """
        Get LIVE price for a token using CLOB /midpoint endpoint.
        Falls back to /price endpoint if midpoint fails.
        """
        settings = get_settings()

        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            timeout = aiohttp.ClientTimeout(total=5)

            # Try /midpoint first
            url = f"{settings.polymarket_host}/midpoint"
            params = {"token_id": token_id}

            async with self._session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    mid = data.get("mid")
                    if mid is not None:
                        price = float(mid)
                        logger.info(f"[LIVE] {token_id[:16]}... = {price:.4f}")
                        return price

            # Fallback to /price endpoint
            url = f"{settings.polymarket_host}/price"
            params = {"token_id": token_id, "side": "buy"}

            async with self._session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    price_str = data.get("price")
                    if price_str is not None:
                        price = float(price_str)
                        logger.info(f"[LIVE/price] {token_id[:16]}... = {price:.4f}")
                        return price

            logger.warning(f"[LIVE] No price available for {token_id[:20]}...")
            return None

        except asyncio.TimeoutError:
            logger.error(f"[LIVE] Timeout for {token_id[:20]}...")
            return None
        except Exception as e:
            logger.error(f"[LIVE] Error: {e}")
            return None

    async def get_live_prices_batch(self, token_ids: List[str]) -> Dict[str, float]:
        """Get live prices for multiple tokens in parallel."""
        tasks = [self.get_live_price(tid) for tid in token_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        prices = {}
        for token_id, result in zip(token_ids, results):
            if isinstance(result, float):
                prices[token_id] = result

        return prices


class PolymarketClient:
    """Async wrapper around py-clob-client for Polymarket trading."""

    def __init__(self):
        self.settings = get_settings()
        self.client: Optional[ClobClient] = None
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._connected = False
        self.live_prices = LivePriceStream()

    async def connect(self) -> bool:
        """Initialize and authenticate with Polymarket."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._sync_connect)
            self._connected = True

            # Start live price stream
            await self.live_prices.start()

            logger.info("Connected to Polymarket successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Polymarket: {e}")
            self._connected = False
            return False

    def _sync_connect(self) -> None:
        """Synchronous connection setup."""
        creds = ApiCreds(
            api_key=self.settings.polymarket_api_key,
            api_secret=self.settings.polymarket_api_secret,
            api_passphrase=self.settings.polymarket_api_passphrase,
        )

        self.client = ClobClient(
            host=self.settings.polymarket_host,
            key=self.settings.private_key,
            chain_id=self.settings.chain_id,
            creds=creds,
        )

        # Derive API credentials if needed
        if self.settings.private_key:
            self.client.set_api_creds(self.client.create_or_derive_api_creds())

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self.client is not None

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in the executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs)
        )

    async def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float
    ) -> Optional[Dict[str, Any]]:
        """
        Place a limit order.

        Args:
            token_id: The token ID to trade
            side: "buy" or "sell"
            price: Limit price (0.0 to 1.0)
            size: Number of shares

        Returns:
            Order response dict or None if failed
        """
        if not self.is_connected:
            logger.error("Client not connected")
            return None

        try:
            order_side = BUY if side.lower() == "buy" else SELL

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )

            result = await self._run_sync(
                self.client.create_and_post_order,
                order_args
            )

            logger.info(f"Placed {side} order: {size} @ {price} for token {token_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        if not self.is_connected:
            return False

        try:
            await self._run_sync(self.client.cancel, order_id)
            logger.info(f"Cancelled order: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if not self.is_connected:
            return False

        try:
            await self._run_sync(self.client.cancel_all)
            logger.info("Cancelled all orders")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return False

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details by ID."""
        if not self.is_connected:
            return None

        try:
            return await self._run_sync(self.client.get_order, order_id)
        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    async def get_open_orders(self, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by market."""
        if not self.is_connected:
            return []

        try:
            result = await self._run_sync(self.client.get_orders)
            orders = result if isinstance(result, list) else []

            if market_id:
                orders = [o for o in orders if o.get("market") == market_id]

            return orders
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions."""
        if not self.is_connected:
            return []

        try:
            result = await self._run_sync(self.client.get_positions)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_market_info(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get market information including time to close."""
        try:
            url = f"{self.settings.gamma_host}/markets/{market_id}"
            response = await self._run_sync(requests.get, url)

            if response.status_code == 200:
                data = response.json()

                # Handle array response (API returns array for single market)
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]

                logger.debug(f"Raw market response keys: {data.keys() if isinstance(data, dict) else 'not a dict'}")

                # Log the outcomePrices for debugging
                if isinstance(data, dict):
                    outcome_prices = data.get("outcomePrices")
                    logger.debug(f"[get_market_info] outcomePrices from API: {outcome_prices}")

                # Parse tokens from outcomes and clobTokenIds (they are JSON strings)
                if isinstance(data, dict) and "tokens" not in data:
                    tokens = self._parse_tokens(data)
                    if tokens:
                        data["tokens"] = tokens
                        logger.debug(f"Parsed tokens: {tokens}")

                return data
            logger.error(f"Market info request failed with status {response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to get market info: {e}")
            return None

    def _parse_tokens(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse tokens from outcomes, clobTokenIds, and outcomePrices fields."""
        tokens = []

        try:
            outcomes_str = market_data.get("outcomes", "[]")
            token_ids_str = market_data.get("clobTokenIds", "[]")
            prices_str = market_data.get("outcomePrices", "[]")

            # Parse JSON strings
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            token_ids = json.loads(token_ids_str) if isinstance(token_ids_str, str) else token_ids_str
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str

            logger.debug(f"Parsed outcomes: {outcomes}, token_ids: {token_ids}, prices: {prices}")

            if len(outcomes) != len(token_ids):
                logger.warning(f"Outcomes/token_ids length mismatch: {len(outcomes)} vs {len(token_ids)}")
                return []

            # Map outcomes to tokens - "Up" maps to "Yes", "Down" maps to "No"
            outcome_mapping = {"Up": "Yes", "Down": "No", "Yes": "Yes", "No": "No"}

            for i, (outcome, token_id) in enumerate(zip(outcomes, token_ids)):
                mapped_outcome = outcome_mapping.get(outcome, outcome)
                price = float(prices[i]) if i < len(prices) else None
                tokens.append({
                    "outcome": mapped_outcome,
                    "token_id": token_id,
                    "original_outcome": outcome,
                    "price": price
                })
                if price is not None:
                    logger.debug(f"[_parse_tokens] {mapped_outcome} ({token_id[:16]}...): price={price:.4f}")

            return tokens
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tokens JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to parse tokens: {e}")
            return []

    async def get_orderbook(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get orderbook for a token."""
        if not self.is_connected:
            return None

        try:
            return await self._run_sync(self.client.get_order_book, token_id)
        except Exception as e:
            logger.error(f"Failed to get orderbook: {e}")
            return None

    async def get_current_price(self, token_id: str) -> Optional[float]:
        """
        Get LIVE current price for a token - NO CACHING.
        Always fetches fresh data from the orderbook API.
        """
        return await self.live_prices.get_live_price(token_id)

    def _is_dst(self, dt: datetime) -> bool:
        """Check if a given UTC datetime is in US Eastern Daylight Time."""
        year = dt.year

        # DST starts: Second Sunday of March at 2:00 AM local (7:00 AM UTC)
        march_first = datetime(year, 3, 1)
        days_until_sunday = (6 - march_first.weekday()) % 7
        second_sunday = march_first + timedelta(days=days_until_sunday + 7)
        dst_start = second_sunday.replace(hour=7)  # 2 AM EST = 7 AM UTC

        # DST ends: First Sunday of November at 2:00 AM local (6:00 AM UTC)
        nov_first = datetime(year, 11, 1)
        days_until_sunday = (6 - nov_first.weekday()) % 7
        first_sunday = nov_first + timedelta(days=days_until_sunday)
        dst_end = first_sunday.replace(hour=6)  # 2 AM EDT = 6 AM UTC

        return dst_start <= dt.replace(tzinfo=None) < dst_end

    def _get_5min_window_search_queries(self) -> List[str]:
        """
        Generate search queries for current and next 5-minute windows in ET.
        Returns list of query strings for public-search API.
        Format: "Bitcoin Up or Down - February 14, 9AM ET"
        """
        # Get current time in UTC and convert to ET
        now_utc = datetime.utcnow()

        # Determine offset: EDT (UTC-4) during DST, EST (UTC-5) otherwise
        if self._is_dst(now_utc):
            et_offset = timedelta(hours=-4)
            tz_name = "EDT"
        else:
            et_offset = timedelta(hours=-5)
            tz_name = "EST"

        now_et = now_utc + et_offset

        # Calculate current 5-minute window start
        minute = now_et.minute
        window_start_min = (minute // 5) * 5
        window_start_hour = now_et.hour

        # Calculate next window start
        next_start_min = window_start_min + 5
        next_start_hour = window_start_hour
        if next_start_min >= 60:
            next_start_min = 0
            next_start_hour = (next_start_hour + 1) % 24

        # Format time for search query (e.g., "9AM", "9:05AM", "12PM", "12:30PM")
        def format_search_time(hour: int, minute: int) -> str:
            period = "AM" if hour < 12 else "PM"
            display_hour = hour if hour <= 12 else hour - 12
            if display_hour == 0:
                display_hour = 12
            if minute == 0:
                return f"{display_hour}{period}"
            else:
                return f"{display_hour}:{minute:02d}{period}"

        # Format date (e.g., "February 14")
        date_str = now_et.strftime("%B %d").replace(" 0", " ").strip()

        # Build search queries - format: "Bitcoin Up or Down - February 14, 9AM ET"
        current_query = f"Bitcoin Up or Down - {date_str}, {format_search_time(window_start_hour, window_start_min)} ET"
        next_query = f"Bitcoin Up or Down - {date_str}, {format_search_time(next_start_hour, next_start_min)} ET"

        logger.info(f"[AUTO] Current ET time: {now_et.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}")
        logger.info(f"[AUTO] Search query 1: {current_query}")
        logger.info(f"[AUTO] Search query 2: {next_query}")

        return [current_query, next_query]

    async def find_btc_5min_markets(self) -> List[Dict[str, Any]]:
        """
        Find Bitcoin 5-minute "Up or Down" markets using public-search API.
        Uses query format: "Bitcoin Up or Down - February 14, 9AM ET"
        """
        try:
            # Get search queries for current/next 5-minute windows
            search_queries = self._get_5min_window_search_queries()

            btc_markets = []
            now_utc = datetime.utcnow()

            # Try each search query
            for query in search_queries:
                encoded_query = quote(query)
                url = f"{self.settings.gamma_host}/public-search?q={encoded_query}"

                logger.info(f"[AUTO] Searching: {url}")
                response = await self._run_sync(requests.get, url)

                if response.status_code != 200:
                    logger.error(f"Search failed: {response.status_code}")
                    continue

                data = response.json()

                # API returns: {"events": [{"markets": [...]}], "pagination": {...}}
                events = data.get("events", [])
                logger.info(f"[AUTO] Found {len(events)} events for: {query}")

                for event in events:
                    # Each event contains a markets array
                    markets = event.get("markets", [])

                    for market in markets:
                        title = market.get("question", "") or market.get("title", "")
                        market_id = market.get("id") or market.get("conditionId")
                        outcomes_str = market.get("outcomes", "[]")

                        # Skip if already added
                        if any(m.get("id") == market_id or m.get("conditionId") == market_id for m in btc_markets):
                            continue

                        # Parse outcomes
                        try:
                            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                        except:
                            outcomes = []

                        # Verify it's a Bitcoin Up or Down market
                        if "bitcoin up or down" not in title.lower():
                            continue

                        # Check end date and calculate time to close
                        end_date_str = market.get("endDate") or market.get("end_date")
                        if not end_date_str:
                            continue

                        try:
                            end_date = datetime.fromisoformat(
                                end_date_str.replace("Z", "+00:00")
                            ).replace(tzinfo=None)

                            time_to_close = (end_date - now_utc).total_seconds() / 60

                            # Only include markets that haven't closed yet
                            if time_to_close > 0:
                                market["time_to_close_minutes"] = time_to_close

                                # Parse tokens
                                if "tokens" not in market:
                                    tokens = self._parse_tokens(market)
                                    if tokens:
                                        market["tokens"] = tokens

                                logger.info(f"[AUTO] ✓ FOUND: {title} | {time_to_close:.1f} min | ID: {market_id}")
                                btc_markets.append(market)

                        except (ValueError, TypeError) as e:
                            logger.debug(f"Error parsing end date: {e}")
                            continue

            # Sort by time to close (nearest first)
            btc_markets.sort(key=lambda m: m.get("time_to_close_minutes", float("inf")))

            if btc_markets:
                selected = btc_markets[0]
                logger.info(f"[AUTO] ========================================")
                logger.info(f"[AUTO] FOUND {len(btc_markets)} MARKETS")
                logger.info(f"[AUTO] SELECTED: {selected.get('question', '')}")
                logger.info(f"[AUTO] MARKET ID: {selected.get('id') or selected.get('conditionId')}")
                logger.info(f"[AUTO] CLOSES IN: {selected.get('time_to_close_minutes', 0):.1f} minutes")
                logger.info(f"[AUTO] ========================================")
            else:
                logger.warning("[AUTO] No Bitcoin Up or Down markets found!")

            return btc_markets

        except Exception as e:
            logger.error(f"Failed to find BTC markets: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def _log_all_btc_markets(self, markets: List[Dict[str, Any]]) -> None:
        """Log all Bitcoin markets for debugging."""
        now = datetime.utcnow()
        for market in markets[:20]:  # Log first 20
            title = market.get("question", "")
            market_id = market.get("id") or market.get("conditionId")
            end_date_str = market.get("endDate", "")
            outcomes_str = market.get("outcomes", "[]")

            try:
                outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            except:
                outcomes = []

            time_to_close = None
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(
                        end_date_str.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    time_to_close = (end_date - now).total_seconds() / 60
                except:
                    pass

            ttc_str = f"{time_to_close:.1f}min" if time_to_close else "N/A"
            logger.info(f"[DEBUG] {title[:60]} | {outcomes} | {ttc_str} | {market_id}")

    async def get_time_to_close(self, market_id: str) -> Optional[float]:
        """
        Get minutes remaining until market closes.

        Returns:
            Minutes remaining or None if market not found
        """
        market_info = await self.get_market_info(market_id)
        if not market_info:
            return None

        end_date_str = market_info.get("endDate")
        if not end_date_str:
            return None

        try:
            end_date = datetime.fromisoformat(
                end_date_str.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            now = datetime.utcnow()

            if end_date <= now:
                return 0

            return (end_date - now).total_seconds() / 60
        except (ValueError, TypeError):
            return None

    async def close(self) -> None:
        """Close the client and cleanup."""
        self._connected = False
        await self.live_prices.stop()
        self._executor.shutdown(wait=False)
        logger.info("Polymarket client closed")


# Singleton instance
_client: Optional[PolymarketClient] = None


async def get_polymarket_client() -> PolymarketClient:
    """Get or create the Polymarket client singleton."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client
