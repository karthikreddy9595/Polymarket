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
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType, PartialCreateOrderOptions, BalanceAllowanceParams, AssetType
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
                        return float(mid)

            # Fallback to /price endpoint
            url = f"{settings.polymarket_host}/price"
            params = {"token_id": token_id, "side": "buy"}

            async with self._session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    price_str = data.get("price")
                    if price_str is not None:
                        return float(price_str)
            return None
        except Exception:
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

            # Set up collateral (USDC) allowance for buying
            logger.info("Setting up trading allowances...")
            await self.ensure_collateral_allowance()
            # Note: Conditional token allowance is set per-token when selling

            logger.info("Connected to Polymarket successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Polymarket: {e}")
            self._connected = False
            return False

    def _sync_connect(self) -> None:
        """Synchronous connection setup."""
        # Get signature type and funder from config
        signature_type = self.settings.signature_type
        funder = self.settings.funder_address

        self.client = ClobClient(
            host=self.settings.polymarket_host,
            key=self.settings.private_key,
            chain_id=self.settings.chain_id,
            signature_type=signature_type,
            funder=funder,
        )

        if self.settings.private_key:
            try:
                derived_creds = self.client.create_or_derive_api_creds()
                self.client.set_api_creds(derived_creds)
            except Exception as e:
                logger.error(f"Failed to derive credentials: {e}")
                raise

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
        size: float,
        tick_size: str = "0.01",
        neg_risk: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Place a limit order.

        Args:
            token_id: The token ID to trade
            side: "buy" or "sell"
            price: Limit price (0.0 to 1.0)
            size: Number of shares
            tick_size: Minimum price increment (from market data, e.g., "0.01" or "0.001")
            neg_risk: Whether this is a negative risk market (multi-outcome events)

        Returns:
            Order response dict or None if failed
        """
        if not self.is_connected:
            logger.error("Client not connected")
            return None

        try:
            # Ensure proper allowance is set before placing order
            if side.lower() == "sell":
                # Selling requires conditional token allowance for the specific token
                await self.ensure_conditional_allowance(token_id)
            else:
                # Buying requires collateral (USDC) allowance
                await self.ensure_collateral_allowance()

            order_side = BUY if side.lower() == "buy" else SELL

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )

            # Market options required by Polymarket API (must be object, not dict)
            options = PartialCreateOrderOptions(
                tick_size=tick_size,
                neg_risk=neg_risk
            )

            # Call create_and_post_order
            result = await self._run_sync(
                lambda: self.client.create_and_post_order(order_args, options)
            )
            return result
        except Exception as e:
            logger.error(f"[LIVE] Order failed: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        if not self.is_connected:
            return False

        try:
            await self._run_sync(self.client.cancel, order_id)
            return True
        except Exception:
            return False

    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if not self.is_connected:
            return False

        try:
            await self._run_sync(self.client.cancel_all)
            return True
        except Exception:
            return False

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details by ID."""
        if not self.is_connected or not self.client:
            return None

        try:
            return await self._run_sync(lambda: self.client.get_order(order_id))
        except Exception as e:
            logger.error(f"Failed to get order: {e}")
            return None

    async def get_open_orders(self, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by market."""
        if not self.is_connected or not self.client:
            return []

        try:
            result = await self._run_sync(lambda: self.client.get_orders())
            orders = result if isinstance(result, list) else []

            if market_id:
                orders = [o for o in orders if o.get("market") == market_id]

            return orders
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []

    async def is_order_active(self, order_id: str) -> bool:
        """
        Check if an order is still active (OPEN/LIVE, not filled).
        Uses the get_orders API to check active orders.

        Returns:
            True if order is still active (unfilled), False if filled or not found
        """
        if not self.is_connected or not self.client:
            return False

        try:
            # Get all active orders
            active_orders = await self._run_sync(lambda: self.client.get_orders())
            if not active_orders or not isinstance(active_orders, list):
                return False

            # Check if our order is in the active orders list
            for order in active_orders:
                active_order_id = order.get("id") or order.get("orderID") or order.get("order_id")
                if active_order_id == order_id:
                    status = order.get("status", "").upper()
                    # Order is active if it's OPEN or LIVE (not filled)
                    if status in ["OPEN", "LIVE", "PENDING"]:
                        logger.info(f"[ORDER CHECK] Order {order_id[:20]}... is still active (status: {status})")
                        return True

            # Order not found in active orders - likely filled or cancelled
            return False
        except Exception as e:
            logger.error(f"Failed to check if order is active: {e}")
            return False

    async def get_trades(self) -> List[Dict[str, Any]]:
        """Get filled trade history."""
        if not self.is_connected or not self.client:
            return []

        try:
            result = await self._run_sync(lambda: self.client.get_trades())
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []

    async def get_positions_api(self, user_address: str) -> List[Dict[str, Any]]:
        """Get positions using Polymarket data-api."""
        try:
            url = "https://data-api.polymarket.com/positions"
            params = {
                "user": user_address,
                "sizeThreshold": 0.1,
                "limit": 100
            }
            response = await self._run_sync(lambda: requests.get(url, params=params))
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_balance(self) -> Optional[float]:
        """Get USDC balance from Polymarket."""
        if not self.is_connected or not self.client:
            return None

        try:
            loop = asyncio.get_event_loop()
            client = self.client
            signature_type = self.settings.signature_type

            def _get_balance_sync():
                try:
                    params = BalanceAllowanceParams(
                        signature_type=signature_type,
                        asset_type=AssetType.COLLATERAL
                    )
                    result = client.get_balance_allowance(params=params)
                    if result and isinstance(result, dict):
                        balance = result.get("balance")
                        if balance is not None:
                            return int(balance) / 10**6
                except Exception:
                    pass
                return None

            return await loop.run_in_executor(self._executor, _get_balance_sync)
        except Exception:
            return None

    async def ensure_conditional_allowance(self, token_id: str) -> bool:
        """
        Ensure we have allowance set for a specific conditional token (YES/NO position).
        This must be called before selling tokens.

        Args:
            token_id: The specific token ID to set allowance for (ERC1155 token)
        """
        if not self.is_connected or not self.client:
            return False

        try:
            client = self.client
            signature_type = self.settings.signature_type

            def _set_allowance_sync():
                try:
                    # For ERC1155 conditional tokens, we need to pass the token_id
                    params = BalanceAllowanceParams(
                        signature_type=signature_type,
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id
                    )
                    result = client.get_balance_allowance(params=params)
                    logger.info(f"[ALLOWANCE] Conditional allowance for {token_id[:20]}...: {result}")

                    # Check if allowance is already set (non-zero)
                    allowances = result.get("allowances", {}) if result else {}
                    has_allowance = any(int(v) > 0 for v in allowances.values()) if allowances else False

                    if not has_allowance:
                        # Set/update allowance for this conditional token
                        update_result = client.update_balance_allowance(params=params)
                        logger.info(f"[ALLOWANCE] Updated conditional allowance: {update_result}")
                    else:
                        logger.info(f"[ALLOWANCE] Conditional allowance already set")

                    return True
                except Exception as e:
                    logger.error(f"[ALLOWANCE] Failed to set conditional allowance: {e}")
                    return False

            return await self._run_sync(_set_allowance_sync)
        except Exception as e:
            logger.error(f"[ALLOWANCE] Error: {e}")
            return False

    async def get_conditional_balance(self, token_id: str) -> Optional[float]:
        """
        Get the actual conditional token balance for a specific token.

        Args:
            token_id: The specific token ID (YES/NO token)

        Returns:
            Token balance as float, or None if failed
        """
        if not self.is_connected or not self.client:
            return None

        try:
            client = self.client
            signature_type = self.settings.signature_type

            def _get_balance_sync():
                try:
                    params = BalanceAllowanceParams(
                        signature_type=signature_type,
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id
                    )
                    result = client.get_balance_allowance(params=params)
                    if result and isinstance(result, dict):
                        balance = result.get("balance")
                        if balance is not None:
                            # Balance is in base units (10^6 decimals)
                            return int(balance) / 10**6
                except Exception as e:
                    logger.error(f"Failed to get conditional balance: {e}")
                return None

            return await self._run_sync(_get_balance_sync)
        except Exception:
            return None

    async def ensure_collateral_allowance(self) -> bool:
        """
        Ensure we have allowance set for collateral (USDC).
        This must be called before buying tokens.
        """
        if not self.is_connected or not self.client:
            return False

        try:
            client = self.client
            signature_type = self.settings.signature_type

            def _set_allowance_sync():
                try:
                    params = BalanceAllowanceParams(
                        signature_type=signature_type,
                        asset_type=AssetType.COLLATERAL
                    )
                    result = client.get_balance_allowance(params=params)
                    logger.info(f"[ALLOWANCE] Current collateral allowance: {result}")

                    # Set/update allowance for collateral
                    update_result = client.update_balance_allowance(params=params)
                    logger.info(f"[ALLOWANCE] Updated collateral allowance: {update_result}")
                    return True
                except Exception as e:
                    logger.error(f"[ALLOWANCE] Failed to set collateral allowance: {e}")
                    return False

            return await self._run_sync(_set_allowance_sync)
        except Exception as e:
            logger.error(f"[ALLOWANCE] Error: {e}")
            return False

    async def get_market_info(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get market information including time to close."""
        try:
            url = f"{self.settings.gamma_host}/markets/{market_id}"
            response = await self._run_sync(requests.get, url)

            if response.status_code == 200:
                data = response.json()

                if isinstance(data, list) and len(data) > 0:
                    data = data[0]

                if isinstance(data, dict) and "tokens" not in data:
                    tokens = self._parse_tokens(data)
                    if tokens:
                        data["tokens"] = tokens

                return data
            return None
        except Exception:
            return None

    def _parse_tokens(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse tokens from outcomes, clobTokenIds, and outcomePrices fields."""
        tokens = []

        try:
            outcomes_str = market_data.get("outcomes", "[]")
            token_ids_str = market_data.get("clobTokenIds", "[]")
            prices_str = market_data.get("outcomePrices", "[]")

            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            token_ids = json.loads(token_ids_str) if isinstance(token_ids_str, str) else token_ids_str
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str

            if len(outcomes) != len(token_ids):
                return []

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

            return tokens
        except Exception:
            return []

    async def get_market_options(self, market_id: str) -> Dict[str, Any]:
        """
        Get market options required for order placement (tick_size, neg_risk).

        Args:
            market_id: The market condition ID

        Returns:
            Dict with tick_size (str) and neg_risk (bool)
        """
        # Default values
        options = {
            "tick_size": "0.01",
            "neg_risk": False
        }

        try:
            market_info = await self.get_market_info(market_id)
            if market_info:
                tick_size = market_info.get("minimum_tick_size") or market_info.get("tickSize") or market_info.get("minTickSize")
                if tick_size:
                    options["tick_size"] = str(tick_size)

                neg_risk = market_info.get("neg_risk") or market_info.get("negRisk")
                if neg_risk is not None:
                    options["neg_risk"] = bool(neg_risk)
        except Exception:
            pass

        return options

    async def get_orderbook(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get orderbook for a token."""
        if not self.is_connected:
            return None

        try:
            return await self._run_sync(self.client.get_order_book, token_id)
        except Exception as e:
            logger.error(f"Failed to get orderbook: {e}")
            return None

    async def get_top_bids(self, token_id: str, count: int = 5) -> List[float]:
        """
        Get top N bid prices from orderbook (for selling).

        When selling, we want to match against bids (what buyers are paying).
        Returns prices sorted from highest to lowest (best bids first).

        Args:
            token_id: The token ID
            count: Number of top bids to return (default 5)

        Returns:
            List of bid prices sorted highest to lowest, or empty list if failed
        """
        try:
            orderbook = await self.get_orderbook(token_id)
            if not orderbook:
                logger.warning(f"[ORDERBOOK] Failed to get orderbook for {token_id[:20]}...")
                return []

            # Orderbook structure: {"bids": [{"price": "0.50", "size": "100"}, ...], "asks": [...]}
            bids = orderbook.get("bids", [])

            if not bids:
                logger.warning(f"[ORDERBOOK] No bids found in orderbook")
                return []

            # Extract prices and sort descending (highest bid first)
            bid_prices = []
            for bid in bids:
                try:
                    price = float(bid.get("price", 0))
                    if price > 0:
                        bid_prices.append(price)
                except (ValueError, TypeError):
                    continue

            # Sort descending and take top N
            bid_prices.sort(reverse=True)
            top_bids = bid_prices[:count]

            logger.info(f"[ORDERBOOK] Top {len(top_bids)} bids: {top_bids}")
            return top_bids

        except Exception as e:
            logger.error(f"[ORDERBOOK] Failed to get top bids: {e}")
            return []

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

            for query in search_queries:
                encoded_query = quote(query)
                url = f"{self.settings.gamma_host}/public-search?q={encoded_query}"

                response = await self._run_sync(requests.get, url)

                if response.status_code != 200:
                    continue

                data = response.json()
                events = data.get("events", [])

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

                            if time_to_close > 0:
                                market["time_to_close_minutes"] = time_to_close

                                if "tokens" not in market:
                                    tokens = self._parse_tokens(market)
                                    if tokens:
                                        market["tokens"] = tokens

                                btc_markets.append(market)

                        except (ValueError, TypeError):
                            continue

            btc_markets.sort(key=lambda m: m.get("time_to_close_minutes", float("inf")))
            return btc_markets

        except Exception:
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
