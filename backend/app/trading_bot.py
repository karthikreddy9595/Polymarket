"""Core trading bot logic with async strategy execution."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import (
    Trade, Position, BotState, OrderStatus, Side,
    async_session_maker, get_or_create_bot_state
)
from .polymarket_client import PolymarketClient, get_polymarket_client

logger = logging.getLogger(__name__)


class BotAction(Enum):
    """Bot action types for logging."""
    STARTED = "Bot started"
    STOPPED = "Bot stopped"
    SCANNING = "Scanning for markets"
    WAITING = "Waiting for entry window"
    PLACING_ORDERS = "Placing orders"
    ORDER_FILLED = "Order filled"
    MONITORING = "Monitoring positions"
    SQUARE_OFF = "Squaring off positions"
    PRICE_TARGET = "Price target reached"
    MAX_LOSS = "Max loss triggered"
    # Paper trading specific actions
    PAPER_WATCHING = "Watching for entry (0.78-0.80)"
    PAPER_BOUGHT = "Paper position opened"
    PAPER_MONITORING = "Monitoring SL/Target"


class PaperTradingState:
    """Track paper trading strategy state."""
    def __init__(self):
        self.position_open = False
        self.entry_price = 0.0
        self.entry_side = None
        self.entry_token_id = None
        self.positions_taken = 0

    def reset(self):
        """Reset position state (preserves positions_taken externally)."""
        logger.debug(f"[STATE] PaperTradingState.reset() called - position_open was {self.position_open}")
        self.position_open = False
        self.entry_price = 0.0
        self.entry_side = None
        self.entry_token_id = None
        self.positions_taken = 0
        logger.debug(f"[STATE] PaperTradingState.reset() done - position_open is now {self.position_open}")

    def close_position(self):
        """Close current position and increment positions_taken."""
        logger.info(f"[STATE] Closing paper position - was open: {self.position_open}, positions_taken: {self.positions_taken}")
        self.position_open = False
        self.entry_price = 0.0
        self.entry_side = None
        self.entry_token_id = None
        self.positions_taken += 1
        logger.info(f"[STATE] Paper position closed - position_open: {self.position_open}, positions_taken: {self.positions_taken}")


class LiveTradingState:
    """Track live trading strategy state."""
    def __init__(self):
        self.position_open = False
        self.entry_price = 0.0
        self.entry_side = None
        self.entry_token_id = None
        self.positions_taken = 0
        self.buy_order_id = None
        self.buy_filled = False
        self.filled_size = 0.0
        self.stoploss_price = 0.0
        self.stoploss_order_id = None
        self.stoploss_order_placed = False
        self.use_soft_stoploss = False
        self.sell_attempted = False

    def reset(self):
        """Reset all state (preserves positions_taken externally)."""
        logger.debug(f"[STATE] LiveTradingState.reset() called - position_open was {self.position_open}")
        self.position_open = False
        self.entry_price = 0.0
        self.entry_side = None
        self.entry_token_id = None
        self.positions_taken = 0
        self.buy_order_id = None
        self.buy_filled = False
        self.filled_size = 0.0
        self.stoploss_price = 0.0
        self.stoploss_order_id = None
        self.stoploss_order_placed = False
        self.use_soft_stoploss = False
        self.sell_attempted = False
        logger.debug(f"[STATE] LiveTradingState.reset() done - position_open is now {self.position_open}")

    def close_position(self):
        """Close current position and increment positions_taken."""
        logger.info(f"[STATE] Closing live position - was open: {self.position_open}, positions_taken: {self.positions_taken}")
        prev_positions = self.positions_taken
        self.position_open = False
        self.entry_price = 0.0
        self.entry_side = None
        self.entry_token_id = None
        self.buy_order_id = None
        self.buy_filled = False
        self.filled_size = 0.0
        self.stoploss_price = 0.0
        self.stoploss_order_id = None
        self.stoploss_order_placed = False
        self.use_soft_stoploss = False
        self.sell_attempted = False
        self.positions_taken = prev_positions + 1
        logger.info(f"[STATE] Live position closed - position_open: {self.position_open}, positions_taken: {self.positions_taken}")


class TradingBot:
    """Async trading bot for Polymarket."""

    def __init__(self):
        self.settings = get_settings()
        self.client: Optional[PolymarketClient] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current_market: Optional[Dict[str, Any]] = None
        self._active_orders: Dict[str, Dict[str, Any]] = {}
        self._paper_state = PaperTradingState()
        self._live_state = LiveTradingState()  # Live trading state

    @property
    def is_running(self) -> bool:
        """Check if bot is running."""
        return self._running

    async def start(self, market_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Start the trading bot.

        Args:
            market_id: Optional specific market to trade

        Returns:
            Tuple of (success, error_message)
        """
        if self._running:
            logger.warning("Bot is already running")
            return False, "Bot is already running"

        # Initialize client
        self.client = await get_polymarket_client()

        # Check if client is already connected, if not try to connect
        if not self.client.is_connected:
            logger.info("Client not connected, attempting to connect...")
            if not await self.client.connect():
                logger.error("Failed to connect to Polymarket")
                return False, "Failed to connect to Polymarket API"
        else:
            logger.info("Client already connected")

        # Verify we have a private key for trading
        if not self.settings.private_key:
            logger.error("No private key configured - cannot trade")
            return False, "No private key configured - cannot trade"

        self._running = True

        # Reset trading state
        self._paper_state.reset()
        self._live_state.reset()

        mode = "PAPER" if self.settings.paper_trading else "LIVE"
        logger.info(f"[{mode}] Bot started | Trigger: {self.settings.trigger_price} | Target: {self.settings.target} | SL: {self.settings.stoploss} | Size: {self.settings.order_size}")

        # Update database state
        await self._update_bot_state(
            is_running=True,
            last_action=BotAction.STARTED.value,
            current_market_id=market_id
        )

        self._task = asyncio.create_task(self._run_strategy(market_id))
        return True, ""

    async def stop(self) -> bool:
        """Stop the trading bot."""
        if not self._running:
            logger.warning("Bot is not running")
            return False

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Cancel all open orders
        if self.client and self.client.is_connected:
            await self.client.cancel_all_orders()

        # Update database state
        await self._update_bot_state(
            is_running=False,
            last_action=BotAction.STOPPED.value
        )

        logger.info("Trading bot stopped")
        return True

    def _timestamp(self) -> str:
        """Get current timestamp for logging."""
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    async def _run_strategy(self, target_market_id: Optional[str] = None) -> None:
        """Main trading strategy loop."""
        current_market_id = target_market_id  # Track current market, None = auto-discover

        try:
            while self._running:
                try:
                    # Find a market to trade (always auto-discover to get next market)
                    market = await self._find_market(current_market_id)

                    if not market:
                        await self._update_bot_state(
                            last_action="Scanning for Bitcoin Up/Down markets..."
                        )
                        logger.info(f"[{self._timestamp()}] [BOT] No market found, scanning again in 10s...")
                        await asyncio.sleep(10)
                        continue

                    market_id = market.get("id") or market.get("conditionId")
                    time_to_close = market.get("time_to_close_minutes", float("inf"))
                    market_title = market.get("question", "Unknown")[:60]

                    # Check if market has expired - search for next market
                    if time_to_close <= 0:
                        # Reset state for new market
                        self._paper_state.reset()
                        self._live_state.reset()
                        current_market_id = None
                        await self._update_bot_state(last_action="Market expired, searching...")
                        await asyncio.sleep(2)
                        continue

                    # Check if we switched to a new market
                    if self._current_market and (self._current_market.get("id") != market_id):
                        logger.info(f"[{self._timestamp()}] [LIVE] New market: {market_title}")
                        self._paper_state.reset()
                        self._live_state.reset()

                    self._current_market = market
                    current_market_id = market_id

                    await self._update_bot_state(
                        current_market_id=market_id,
                        last_action=f"Trading: {market_title}..."
                    )

                    # Execute trading logic (no time threshold - trade immediately)
                    await self._execute_trading_logic(market)

                    # Monitor positions
                    await self._monitor_positions(market)

                    await asyncio.sleep(self.settings.position_check_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[{self._timestamp()}] Strategy error: {e}")
                    import traceback
                    traceback.print_exc()
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info(f"[{self._timestamp()}] Strategy loop cancelled")
        finally:
            self._running = False

    async def _find_market(self, target_market_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Find a market to trade. Auto-discovers next market if current expired."""
        # Always auto-discover to get the current/next active market
        markets = await self.client.find_btc_5min_markets()

        if markets:
            market = markets[0]
            market_id = market.get("id") or market.get("conditionId")
            time_to_close = market.get("time_to_close_minutes", 0)

            # Log tokens for debugging
            tokens = market.get("tokens", [])
            for t in tokens:
                logger.debug(f"Token {t.get('outcome')}: price={t.get('price')}")

            return market

        return None

    async def _execute_trading_logic(self, market: Dict[str, Any]) -> None:
        """
        Execute the core trading logic.

        Paper Trading Strategy:
        1. Monitor both YES and NO prices
        2. When one side touches 0.8, that's the signal
        3. Buy when price drops to 0.75 (better entry)
        4. Stoploss at 0.55, target at 0.98
        5. Repeat when no position

        Live Trading Strategy:
        1. When market is < 3 minutes to close, place limit orders
        2. Place limit buy/sell orders at price 0.8
        3. After buy fill, place sell order at 0.5
        4. No positions? Buy both YES and NO at 0.8
        """
        tokens = market.get("tokens", [])
        logger.debug(f"Market data keys: {market.keys()}")
        logger.debug(f"Tokens found: {tokens}")

        if len(tokens) < 2:
            logger.warning(f"Market doesn't have expected tokens. Got {len(tokens)} tokens. "
                          f"outcomes={market.get('outcomes')}, clobTokenIds={market.get('clobTokenIds')}")
            return

        # Get YES and NO token IDs
        yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
        no_token = next((t for t in tokens if t.get("outcome") == "No"), None)

        if not yes_token or not no_token:
            logger.warning("Could not identify YES/NO tokens")
            return

        yes_token_id = yes_token.get("token_id")
        no_token_id = no_token.get("token_id")

        # Use different strategy for paper trading vs live trading
        if self.settings.paper_trading:
            # PAPER TRADING - orders are simulated, not sent to Polymarket
            await self._execute_paper_trading_strategy(
                market=market,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id
            )
            return

        # LIVE TRADING - real orders sent to Polymarket
        await self._execute_live_trading_strategy(
            market=market,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id
        )

    async def _execute_live_trading_strategy(
        self,
        market: Dict[str, Any],
        yes_token_id: str,
        no_token_id: str
    ) -> None:
        """
        Simplified live trading strategy:
        1. Entry: MARKET order when price >= TRIGGER_PRICE (0.75)
        2. After fill: Place LIMIT sell at TARGET (0.99) and STOPLOSS (0.55)
        3. Cancel unfilled orders before market close
        4. NO BUYING when <= 10 seconds to expiry
        5. FORCE SELL all positions when <= 5 seconds to expiry
        """
        # Config values
        TRIGGER_PRICE = self.settings.trigger_price
        STOPLOSS = self.settings.stoploss
        TARGET = self.settings.target
        ORDER_CANCEL_THRESHOLD = self.settings.order_cancel_threshold
        NO_BUY_THRESHOLD = 10 / 60  # 10 seconds in minutes = 0.1667 - no buying below this
        FORCE_CLOSE_THRESHOLD = 0 / 60  # 7 seconds in minutes = 0.0833 - force sell positions
        max_positions = self.settings.max_positions_per_market

        # Get fresh time to close
        market_id = market.get("id") or market.get("conditionId")
        time_to_close = await self.client.get_time_to_close(market_id)
        if time_to_close is None:
            time_to_close = market.get("time_to_close_minutes", 0)
        market["time_to_close_minutes"] = time_to_close

        # Get live prices
        yes_price = await self.client.get_current_price(yes_token_id)
        no_price = await self.client.get_current_price(no_token_id)

        if yes_price is None or no_price is None:
            logger.warning(f"[{self._timestamp()}] [LIVE] Could not get prices - YES: {yes_price}, NO: {no_price}")
            return

        # Get and display balance
        balance = await self.client.get_balance()
        balance_str = f"${balance:.2f}" if balance is not None else "N/A"

        logger.info(f"[{self._timestamp()}] [LIVE] YES: {yes_price:.4f} | NO: {no_price:.4f} | Time: {time_to_close:.1f}m | Balance: {balance_str}")

        # CRITICAL: Force close all positions when <= 5 seconds to expiry
        if time_to_close <= FORCE_CLOSE_THRESHOLD:
            await self._force_close_live_position(market, "5SEC_EXPIRY")
            return

        # Check if we need to cancel orders before market close
        if time_to_close <= ORDER_CANCEL_THRESHOLD:
            await self._handle_market_close_live(market)
            return

        # Check if we've reached max positions
        if self._live_state.positions_taken >= max_positions:
            logger.info(f"[{self._timestamp()}] [LIVE] Max positions reached ({self._live_state.positions_taken}/{max_positions}). Waiting for next market...")
            await self._update_bot_state(
                last_action=f"Max positions reached ({self._live_state.positions_taken}/{max_positions}). Waiting for next market..."
            )
            return

        # Check if we have a position open (either filled or pending)
        if self._live_state.position_open:
            logger.debug(f"[{self._timestamp()}] [LIVE] Position is open, monitoring...")
            await self._monitor_live_position(market)
            return

        # NO BUYING when <= 10 seconds to expiry
        if time_to_close <= NO_BUY_THRESHOLD:
            time_seconds = time_to_close * 60
            logger.info(f"[{self._timestamp()}] [LIVE] No buying - only {time_seconds:.1f}s to expiry (< 10s)")
            await self._update_bot_state(
                last_action=f"[LIVE] No buying - {time_seconds:.1f}s to expiry"
            )
            return

        # No position - look for entry signal (price >= trigger)
        logger.info(f"[{self._timestamp()}] [LIVE] Looking for entry: YES={yes_price:.4f}, NO={no_price:.4f}, trigger={TRIGGER_PRICE}, positions={self._live_state.positions_taken}/{max_positions}")

        await self._update_bot_state(
            last_action=f"[LIVE] Watching for entry (>= {TRIGGER_PRICE}) | YES: {yes_price:.3f}, NO: {no_price:.3f}"
        )

        # Check YES side for entry signal
        if yes_price >= TRIGGER_PRICE and yes_price < TARGET:
            logger.info(f"[{self._timestamp()}] [LIVE] Entry signal triggered: YES @ {yes_price:.4f} >= {TRIGGER_PRICE}")
            await self._place_live_entry(market=market, token_id=yes_token_id, side="YES", current_price=yes_price)
            return

        # Check NO side for entry signal
        if no_price >= TRIGGER_PRICE and no_price < TARGET:
            logger.info(f"[{self._timestamp()}] [LIVE] Entry signal triggered: NO @ {no_price:.4f} >= {TRIGGER_PRICE}")
            await self._place_live_entry(market=market, token_id=no_token_id, side="NO", current_price=no_price)
            return

    async def _place_live_entry(
        self,
        market: Dict[str, Any],
        token_id: str,
        side: str,
        current_price: float
    ) -> None:
        """Place a MARKET buy order (at current price + buffer to fill immediately)."""
        TARGET = self.settings.target
        STOPLOSS = self.settings.stoploss
        MARKET_BUY_PRICE = min(round(current_price + 0.02, 2), 0.98)

        order_id = await self._place_order(
            market=market,
            token_id=token_id,
            side="buy",
            price=MARKET_BUY_PRICE,
            size=self.settings.order_size,
            outcome=side
        )

        if order_id:
            self._live_state.buy_order_id = order_id
            self._live_state.entry_side = side
            self._live_state.entry_token_id = token_id
            self._live_state.entry_price = current_price
            self._live_state.buy_filled = False  # Will be confirmed via positions API
            self._live_state.position_open = True

            logger.info(f"[{self._timestamp()}] [LIVE] BUY {side} @ {current_price:.4f} | Target: {TARGET} | SL: {STOPLOSS}")

            await self._update_bot_state(
                last_action=f"[LIVE] Waiting for position confirmation..."
            )

    async def _check_order_filled(self) -> bool:
        """Check if buy order is filled using getOrder and getTrades APIs.
        Also updates self._live_state.filled_size with actual filled quantity."""
        if not self._live_state.buy_order_id:
            logger.info(f"[{self._timestamp()}] [LIVE] No buy_order_id to check")
            return False

        order_id = self._live_state.buy_order_id
        logger.info(f"[{self._timestamp()}] [LIVE] Checking order: {order_id[:20]}...")

        # Method 1: Check order status via getOrder
        try:
            order = await self.client.get_order(order_id)
            logger.info(f"[{self._timestamp()}] [LIVE] getOrder response: {order}")

            if order:
                status = order.get("status", "").upper()
                size_matched = order.get("size_matched") or order.get("sizeMatched") or "0"
                size_matched = float(size_matched)

                logger.info(f"[{self._timestamp()}] [LIVE] Order status={status}, size_matched={size_matched}")

                if status in ["FILLED", "MATCHED", "LIVE"] or size_matched > 0:
                    # Store the actual filled size for selling later
                    self._live_state.filled_size = size_matched
                    logger.info(f"[{self._timestamp()}] [LIVE] Order FILLED! Size: {size_matched}")
                    return True
        except Exception as e:
            logger.error(f"[{self._timestamp()}] [LIVE] getOrder error: {e}")

        # Method 2: Check trades via getTrades
        try:
            trades = await self.client.get_trades()
            logger.info(f"[{self._timestamp()}] [LIVE] getTrades returned {len(trades) if trades else 0} trades")

            if trades:
                for trade in trades:
                    trade_order_id = trade.get("order_id") or trade.get("orderId") or trade.get("id")
                    if trade_order_id == order_id:
                        # Get size from trade if available
                        trade_size = float(trade.get("size") or trade.get("amount") or self.settings.order_size)
                        self._live_state.filled_size = trade_size
                        logger.info(f"[{self._timestamp()}] [LIVE] Found matching trade! Size: {trade_size}")
                        return True
        except Exception as e:
            logger.error(f"[{self._timestamp()}] [LIVE] getTrades error: {e}")

        return False

    def _calculate_stoploss_price(self, entry_price: float, stoploss_offset: float = 0.20) -> float:
        """Calculate stoploss price. Simply: entry_price - offset."""
        # Example: Buy at 0.80, offset 0.20 -> stoploss at 0.60
        stoploss_price = entry_price - stoploss_offset
        return max(round(stoploss_price, 2), 0.01)  # Min 0.01

    async def _monitor_live_position(self, market: Dict[str, Any]) -> None:
        """Monitor live position - track price for target and stoploss."""
        TARGET = self.settings.target

        # If buy not confirmed yet, check order status
        if not self._live_state.buy_filled and self._live_state.buy_order_id:
            logger.info(f"[{self._timestamp()}] [LIVE] Checking if order filled...")
            is_filled = await self._check_order_filled()
            if is_filled:
                self._live_state.buy_filled = True
                # Stoploss = entry_price - 0.20
                stoploss_price = self._calculate_stoploss_price(self._live_state.entry_price, 0.20)
                self._live_state.stoploss_price = stoploss_price
                # Use soft stoploss (price monitoring) - no limit order
                self._live_state.use_soft_stoploss = True
                self._live_state.stoploss_order_placed = True
                logger.info(f"[{self._timestamp()}] [LIVE] FILLED! Entry: {self._live_state.entry_price:.4f} | Soft SL: {stoploss_price:.4f} | Target: {TARGET}")

                # Update trade status to FILLED and create position in database
                market_id = market.get("id") or market.get("conditionId")
                await self._update_trade_status(self._live_state.buy_order_id, OrderStatus.FILLED)
                await self._update_live_position(
                    market_id=market_id,
                    token_id=self._live_state.entry_token_id,
                    side="buy",
                    price=self._live_state.entry_price,
                    size=self._live_state.filled_size if self._live_state.filled_size > 0 else self.settings.order_size,
                    outcome=self._live_state.entry_side
                )
            return

        # Get current price
        current_price = await self.client.get_current_price(self._live_state.entry_token_id)
        if not current_price:
            return

        entry_price = self._live_state.entry_price
        stoploss_price = getattr(self._live_state, 'stoploss_price', entry_price - 0.05)
        pnl = (current_price - entry_price) * self.settings.order_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        time_to_close = market.get("time_to_close_minutes", 0)

        await self._update_bot_state(
            last_action=f"[LIVE] {self._live_state.entry_side}: {current_price:.4f} (${pnl:+.2f}) | SL: {stoploss_price:.2f} | {time_to_close:.1f}m"
        )

        # Check if price reached TARGET - market sell for profit
        if current_price >= TARGET:
            logger.info(f"[{self._timestamp()}] [LIVE] TARGET! Price {current_price:.4f} >= {TARGET}")
            await self._market_sell(market, current_price, "TARGET")
            return

        # Check if price hit STOPLOSS - soft stoploss (price monitoring)
        if current_price <= stoploss_price:
            logger.info(f"[{self._timestamp()}] [LIVE] STOPLOSS! Price {current_price:.4f} <= {stoploss_price:.4f}")
            await self._market_sell(market, current_price, "STOPLOSS")
            return

    async def _market_sell(self, market: Dict[str, Any], current_price: float, reason: str) -> None:
        """Execute market sell order using actual token balance."""
        import math

        # Prevent repeated sell attempts (order might have gone through but returned error)
        if self._live_state.sell_attempted:
            # Check if we still have tokens - if not, the sell went through
            actual_balance = await self.client.get_conditional_balance(self._live_state.entry_token_id)
            if actual_balance is None or actual_balance < 0.1:
                logger.info(f"[{self._timestamp()}] [LIVE] Previous sell appears to have succeeded (balance: {actual_balance}), closing position")
                await self._close_live_position(f"{reason}_CONFIRMED")
                return
            logger.info(f"[{self._timestamp()}] [LIVE] Retrying sell (balance: {actual_balance})...")

        # Mark that we're attempting a sell
        self._live_state.sell_attempted = True

        # Price slightly below current to fill immediately
        sell_price = max(round(current_price - 0.02, 2), 0.01)

        # Get actual conditional token balance (most accurate)
        actual_balance = await self.client.get_conditional_balance(self._live_state.entry_token_id)

        # Minimum order size for Polymarket
        MIN_ORDER_SIZE = 0.1

        if actual_balance and actual_balance >= MIN_ORDER_SIZE:
            # Use actual balance, FLOOR to avoid "not enough balance" errors
            # round() can round UP (4.9656 -> 4.97), but we need to round DOWN (4.9656 -> 4.96)
            sell_size = math.floor(actual_balance * 100) / 100
            logger.info(f"[{self._timestamp()}] [LIVE] Actual token balance: {actual_balance}, selling: {sell_size}")
        elif actual_balance is not None and actual_balance < MIN_ORDER_SIZE:
            # Balance too small to sell, close position without selling
            logger.info(f"[{self._timestamp()}] [LIVE] Balance {actual_balance} too small to sell (min: {MIN_ORDER_SIZE}), closing position")
            await self._close_live_position(f"{reason}_DUST")
            return
        else:
            # Couldn't get balance, use filled_size
            sell_size = self._live_state.filled_size if self._live_state.filled_size > 0 else self.settings.order_size
            # Also floor the fallback size
            sell_size = math.floor(sell_size * 100) / 100
            logger.info(f"[{self._timestamp()}] [LIVE] Using filled_size: {sell_size}")

        if sell_size < MIN_ORDER_SIZE:
            logger.info(f"[{self._timestamp()}] [LIVE] Sell size {sell_size} too small (min: {MIN_ORDER_SIZE}), closing position")
            await self._close_live_position(f"{reason}_DUST")
            return

        logger.info(f"[{self._timestamp()}] [LIVE] Market SELL {sell_size} @ {sell_price}")

        sell_order_id = await self._place_order(
            market=market,
            token_id=self._live_state.entry_token_id,
            side="sell",
            price=sell_price,
            size=sell_size,
            outcome=self._live_state.entry_side
        )

        if sell_order_id:
            pnl = (current_price - self._live_state.entry_price) * sell_size
            logger.info(f"[{self._timestamp()}] [LIVE] {reason} - Sold {sell_size} @ {current_price:.4f} | P&L: ${pnl:+.2f}")

            # Update trade status and position in database
            market_id = market.get("id") or market.get("conditionId")
            await self._update_trade_status(sell_order_id, OrderStatus.FILLED)
            await self._update_live_position(
                market_id=market_id,
                token_id=self._live_state.entry_token_id,
                side="sell",
                price=current_price,
                size=sell_size,
                outcome=self._live_state.entry_side
            )

            await self._close_live_position(reason)
        else:
            logger.error(f"[{self._timestamp()}] [LIVE] Failed to sell!")

    async def _close_live_position(self, reason: str) -> None:
        """Close live position and update state."""
        # Use the close_position method which properly resets state and increments counter
        self._live_state.close_position()

        max_positions = self.settings.max_positions_per_market
        positions_taken = self._live_state.positions_taken

        await self._update_bot_state(
            last_action=f"[LIVE] [{reason}] Position closed | {positions_taken}/{max_positions}"
        )
        logger.info(f"[{self._timestamp()}] [LIVE] POSITION CLOSED: {reason} | Positions: {positions_taken}/{max_positions}")
        logger.info(f"[{self._timestamp()}] [LIVE] State after close: position_open={self._live_state.position_open}")

    async def _handle_market_close_live(self, market: Dict[str, Any]) -> None:
        """Handle market close - cancel unfilled orders."""
        time_to_close = market.get("time_to_close_minutes", 0)
        logger.info(f"[{self._timestamp()}] [LIVE] Market closing in {time_to_close:.2f} min - handling open orders")

        # Cancel unfilled buy order
        if self._live_state.buy_order_id and not self._live_state.buy_filled:
            logger.info(f"[{self._timestamp()}] [LIVE] Cancelling unfilled buy order: {self._live_state.buy_order_id}")
            await self.client.cancel_order(self._live_state.buy_order_id)
            self._live_state.buy_order_id = None

        # If we have a position, let market settle
        if self._live_state.position_open:
            logger.info(f"[{self._timestamp()}] [LIVE] Position open at market close - will auto-settle at $1.00 if profitable")
            await self._update_bot_state(
                last_action=f"[LIVE] Market closing - position will auto-settle"
            )
        else:
            await self._update_bot_state(
                last_action=f"[LIVE] Market closing - no position"
            )

    async def _force_close_live_position(self, market: Dict[str, Any], reason: str) -> None:
        """
        Force close live position when <= 5 seconds to expiry.
        Sells all open positions immediately at market price.
        """
        time_to_close = market.get("time_to_close_minutes", 0)
        time_seconds = time_to_close * 60

        logger.info(f"[{self._timestamp()}] [LIVE] FORCE CLOSE: {time_seconds:.1f}s to expiry - {reason}")

        # Cancel any unfilled buy order first
        if self._live_state.buy_order_id and not self._live_state.buy_filled:
            logger.info(f"[{self._timestamp()}] [LIVE] Cancelling unfilled buy order: {self._live_state.buy_order_id}")
            await self.client.cancel_order(self._live_state.buy_order_id)
            self._live_state.buy_order_id = None

        # Force sell if we have a filled position
        if self._live_state.position_open and self._live_state.buy_filled:
            current_price = await self.client.get_current_price(self._live_state.entry_token_id)
            if current_price:
                logger.info(f"[{self._timestamp()}] [LIVE] Force selling position at {current_price:.4f}")
                await self._market_sell(market, current_price, reason)
            else:
                logger.warning(f"[{self._timestamp()}] [LIVE] Could not get price for force sell")
                # Close position state anyway to prevent stuck state
                await self._close_live_position(f"{reason}_NO_PRICE")
        elif self._live_state.position_open:
            # Position open but buy not filled - just close state
            logger.info(f"[{self._timestamp()}] [LIVE] Position pending but not filled, closing state")
            await self._close_live_position(f"{reason}_UNFILLED")

        await self._update_bot_state(
            last_action=f"[LIVE] Force closed - {time_seconds:.1f}s to expiry"
        )

    async def _execute_paper_trading_strategy(
        self,
        market: Dict[str, Any],
        yes_token_id: str,
        no_token_id: str
    ) -> None:
        """
        Paper trading strategy (UNIFIED with live trading):
        1. Entry: Buy when price >= trigger_price (0.75) and < target
        2. Stop Loss: Exit when price drops to entry_price - 0.20 (soft stoploss)
        3. Target: Exit when price reaches target (0.99)
        4. Re-entry: After position closes, immediately look for new signal if time permits
        5. NO BUYING when <= 10 seconds to expiry
        6. FORCE SELL all positions when <= 5 seconds to expiry
        """
        # Price levels from config (same as live trading)
        TRIGGER_PRICE = self.settings.trigger_price
        STOPLOSS = self.settings.stoploss
        TARGET = self.settings.target
        ORDER_CANCEL_THRESHOLD = self.settings.order_cancel_threshold
        NO_BUY_THRESHOLD = 10 / 60  # 10 seconds in minutes = 0.1667 - no buying below this
        FORCE_CLOSE_THRESHOLD = 5 / 60  # 5 seconds in minutes = 0.0833 - force sell positions
        max_positions = self.settings.max_positions_per_market

        # Get FRESH time to expiry (not stale from market dict)
        market_id = market.get("id") or market.get("conditionId")
        time_to_close = await self.client.get_time_to_close(market_id)
        if time_to_close is None:
            time_to_close = market.get("time_to_close_minutes", 0)

        # Update market dict with fresh time
        market["time_to_close_minutes"] = time_to_close

        # Get LIVE prices from CLOB API
        yes_price = await self.client.get_current_price(yes_token_id)
        no_price = await self.client.get_current_price(no_token_id)

        if yes_price is None or no_price is None:
            logger.warning(f"[{self._timestamp()}] [PAPER] Could not get prices - YES: {yes_price}, NO: {no_price}")
            return

        # ALWAYS log live prices with timestamp
        logger.info(f"[{self._timestamp()}] [PRICE] YES: {yes_price:.4f} | NO: {no_price:.4f} | Time left: {time_to_close:.2f} min")

        # CRITICAL: Force close all positions when <= 5 seconds to expiry
        if time_to_close <= FORCE_CLOSE_THRESHOLD:
            await self._force_close_paper_position(market, "5SEC_EXPIRY")
            return

        # Check if we need to cancel entry before market close (same as live trading)
        if time_to_close <= ORDER_CANCEL_THRESHOLD:
            await self._handle_market_close_paper(market)
            return

        # Check if we've reached the maximum positions for this market
        if self._paper_state.positions_taken >= max_positions:
            logger.info(f"[{self._timestamp()}] [PAPER] Max positions reached ({self._paper_state.positions_taken}/{max_positions}). Waiting for next market...")
            await self._update_bot_state(
                last_action=f"Max positions reached ({self._paper_state.positions_taken}/{max_positions}). Waiting for next market..."
            )
            return

        # Check if we have a position open
        if self._paper_state.position_open:
            await self._monitor_paper_position_unified(market)
            return

        # NO BUYING when <= 10 seconds to expiry
        if time_to_close <= NO_BUY_THRESHOLD:
            time_seconds = time_to_close * 60
            logger.info(f"[{self._timestamp()}] [PAPER] No buying - only {time_seconds:.1f}s to expiry (< 10s)")
            await self._update_bot_state(
                last_action=f"[PAPER] No buying - {time_seconds:.1f}s to expiry"
            )
            return

        # No position - look for entry signal (price >= trigger_price)
        await self._update_bot_state(
            last_action=f"[PAPER] Watching for entry (>= {TRIGGER_PRICE}) | YES: {yes_price:.3f}, NO: {no_price:.3f}"
        )

        # Check YES side for entry signal (same logic as live trading)
        if yes_price >= TRIGGER_PRICE and yes_price < TARGET:
            logger.info(f"[{self._timestamp()}] [PAPER] Entry signal: YES @ {yes_price:.4f} (>= {TRIGGER_PRICE})")
            await self._place_paper_entry_unified(
                market=market,
                token_id=yes_token_id,
                side="YES",
                current_price=yes_price
            )
            return

        # Check NO side for entry signal (same logic as live trading)
        if no_price >= TRIGGER_PRICE and no_price < TARGET:
            logger.info(f"[{self._timestamp()}] [PAPER] Entry signal: NO @ {no_price:.4f} (>= {TRIGGER_PRICE})")
            await self._place_paper_entry_unified(
                market=market,
                token_id=no_token_id,
                side="NO",
                current_price=no_price
            )
            return

        # Log when waiting for signal
        if yes_price >= TARGET:
            logger.debug(f"[{self._timestamp()}] [PAPER] YES price {yes_price:.4f} >= target {TARGET}, skipping")
        elif no_price >= TARGET:
            logger.debug(f"[{self._timestamp()}] [PAPER] NO price {no_price:.4f} >= target {TARGET}, skipping")
        else:
            logger.debug(f"[{self._timestamp()}] [PAPER] Waiting for entry signal - need price >= {TRIGGER_PRICE}")

    async def _place_paper_entry_unified(
        self,
        market: Dict[str, Any],
        token_id: str,
        side: str,
        current_price: float
    ) -> None:
        """
        Place a paper trading entry order (UNIFIED with live trading).
        Entry signal: price >= trigger_price and < target
        """
        TRIGGER_PRICE = self.settings.trigger_price
        TARGET = self.settings.target

        # CHECK: Only buy if price is at or above trigger price
        if current_price < TRIGGER_PRICE:
            logger.warning(f"[{self._timestamp()}] [PAPER] REJECTED: {side} @ {current_price:.4f} < trigger {TRIGGER_PRICE}")
            return

        # CHECK: Don't buy if price is at or above target (no profit potential)
        if current_price >= TARGET:
            logger.warning(f"[{self._timestamp()}] [PAPER] REJECTED: {side} @ {current_price:.4f} >= target {TARGET}")
            return

        order_id = await self._simulate_paper_order_unified(
            market_id=market.get("id") or market.get("conditionId"),
            token_id=token_id,
            side="buy",
            price=current_price,
            size=self.settings.order_size,
            outcome=side
        )

        if order_id:
            # Calculate stoploss price same as live trading (entry - 0.20)
            stoploss_price = self._calculate_stoploss_price(current_price, 0.20)

            self._paper_state.position_open = True
            self._paper_state.entry_price = current_price
            self._paper_state.entry_side = side
            self._paper_state.entry_token_id = token_id

            logger.info(f"[{self._timestamp()}] [PAPER] BUY {side} @ {current_price:.4f} | Target: {TARGET} | SL: {stoploss_price:.4f}")

            await self._update_bot_state(
                last_action=f"[PAPER] Position opened: {side} @ {current_price:.4f}"
            )

    async def _monitor_paper_position_unified(self, market: Dict[str, Any]) -> None:
        """
        Monitor paper position (UNIFIED with live trading).
        Uses soft stoploss (entry_price - 0.20) same as live trading.
        """
        TARGET = self.settings.target

        # Get current price
        current_price = await self.client.get_current_price(self._paper_state.entry_token_id)
        if not current_price:
            return

        entry_price = self._paper_state.entry_price
        stoploss_price = self._calculate_stoploss_price(entry_price, 0.20)
        pnl = (current_price - entry_price) * self.settings.order_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        time_to_close = market.get("time_to_close_minutes", 0)

        await self._update_bot_state(
            last_action=f"[PAPER] {self._paper_state.entry_side}: {current_price:.4f} (${pnl:+.2f}) | SL: {stoploss_price:.2f} | {time_to_close:.1f}m"
        )

        logger.info(f"[{self._timestamp()}] [MONITOR] {self._paper_state.entry_side}: {current_price:.4f} | Entry: {entry_price:.4f} | P&L: {pnl_pct:+.1f}% | Time: {time_to_close:.2f}m | SL: {stoploss_price:.4f} | Target: {TARGET}")

        # Check if price reached TARGET - exit for profit
        if current_price >= TARGET:
            logger.info(f"[{self._timestamp()}] [PAPER] TARGET! Price {current_price:.4f} >= {TARGET}")
            await self._exit_paper_position_unified(market, current_price, "TARGET")
            return

        # Check if price hit STOPLOSS - soft stoploss (same as live trading)
        if current_price <= stoploss_price:
            logger.info(f"[{self._timestamp()}] [PAPER] STOPLOSS! Price {current_price:.4f} <= {stoploss_price:.4f}")
            await self._exit_paper_position_unified(market, current_price, "STOPLOSS")
            return

    async def _handle_market_close_paper(self, market: Dict[str, Any]) -> None:
        """Handle market close for paper trading - close position if open."""
        time_to_close = market.get("time_to_close_minutes", 0)
        logger.info(f"[{self._timestamp()}] [PAPER] Market closing in {time_to_close:.2f} min")

        # If we have a position, close it at current price (market will settle at $1.00)
        if self._paper_state.position_open:
            current_price = await self.client.get_current_price(self._paper_state.entry_token_id)
            if current_price:
                logger.info(f"[{self._timestamp()}] [PAPER] Market close - closing position at {current_price:.4f}")
                await self._exit_paper_position_unified(market, current_price, "MARKET_CLOSE")
            else:
                await self._update_bot_state(
                    last_action=f"[PAPER] Market closing - position will settle"
                )
        else:
            await self._update_bot_state(
                last_action=f"[PAPER] Market closing - no position"
            )

    async def _force_close_paper_position(self, market: Dict[str, Any], reason: str) -> None:
        """
        Force close paper position when <= 5 seconds to expiry.
        Sells all open positions immediately at current price.
        """
        time_to_close = market.get("time_to_close_minutes", 0)
        time_seconds = time_to_close * 60

        logger.info(f"[{self._timestamp()}] [PAPER] FORCE CLOSE: {time_seconds:.1f}s to expiry - {reason}")

        # Force sell if we have an open position
        if self._paper_state.position_open:
            current_price = await self.client.get_current_price(self._paper_state.entry_token_id)
            if current_price:
                logger.info(f"[{self._timestamp()}] [PAPER] Force selling position at {current_price:.4f}")
                await self._exit_paper_position_unified(market, current_price, reason)
            else:
                logger.warning(f"[{self._timestamp()}] [PAPER] Could not get price for force sell")
                # Close position state anyway to prevent stuck state
                self._paper_state.close_position()

        await self._update_bot_state(
            last_action=f"[PAPER] Force closed - {time_seconds:.1f}s to expiry"
        )

    async def _exit_paper_position_unified(
        self,
        market: Dict[str, Any],
        exit_price: float,
        reason: str
    ) -> None:
        """
        Exit a paper position (UNIFIED with live trading).
        Includes taker fees in P&L calculation.
        """
        # Store values before reset
        entry_price = self._paper_state.entry_price
        entry_side = self._paper_state.entry_side
        size = self.settings.order_size

        # Calculate fees for display
        buy_value = entry_price * size
        sell_value = exit_price * size
        buy_fee = self._calculate_taker_fee(buy_value)
        sell_fee = self._calculate_taker_fee(sell_value)
        total_fees = buy_fee + sell_fee

        # Calculate P&L
        gross_pnl = (exit_price - entry_price) * size
        net_pnl = gross_pnl - total_fees
        net_pnl_pct = (net_pnl / buy_value) * 100 if buy_value > 0 else 0

        order_id = await self._simulate_paper_order_unified(
            market_id=market.get("id") or market.get("conditionId"),
            token_id=self._paper_state.entry_token_id,
            side="sell",
            price=exit_price,
            size=size,
            outcome=entry_side
        )

        if order_id:
            # Use close_position method which properly resets and increments counter
            self._paper_state.close_position()

            max_positions = self.settings.max_positions_per_market
            positions_taken = self._paper_state.positions_taken

            logger.info(f"[{self._timestamp()}] [PAPER] ══════════════════════════════════════")
            logger.info(f"[{self._timestamp()}] [PAPER] POSITION CLOSED: {reason}")
            logger.info(f"[{self._timestamp()}] [PAPER] Side: {entry_side}")
            logger.info(f"[{self._timestamp()}] [PAPER] Entry: {entry_price:.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Exit: {exit_price:.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Gross P&L: {gross_pnl:+.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Fees: -{total_fees:.4f} (buy: {buy_fee:.4f}, sell: {sell_fee:.4f})")
            logger.info(f"[{self._timestamp()}] [PAPER] Net P&L: {net_pnl:+.4f} ({net_pnl_pct:+.1f}%)")
            logger.info(f"[{self._timestamp()}] [PAPER] Positions taken: {positions_taken}/{max_positions}")
            logger.info(f"[{self._timestamp()}] [PAPER] State: position_open={self._paper_state.position_open}")
            logger.info(f"[{self._timestamp()}] [PAPER] ══════════════════════════════════════")

            await self._update_bot_state(
                last_action=f"[{reason}] Closed @ {exit_price:.4f}, Net P&L: ${net_pnl:+.2f} | {positions_taken}/{max_positions}"
            )

    async def _exit_paper_position(
        self,
        market: Dict[str, Any],
        position: Position,
        exit_price: float,
        reason: str
    ) -> None:
        """Exit a paper position. Includes taker fees in P&L calculation."""
        # Calculate fees for display
        buy_value = position.avg_price * position.quantity
        sell_value = exit_price * position.quantity
        buy_fee = self._calculate_taker_fee(buy_value)
        sell_fee = self._calculate_taker_fee(sell_value)
        total_fees = buy_fee + sell_fee

        # Calculate P&L
        gross_pnl = (exit_price - position.avg_price) * position.quantity
        net_pnl = gross_pnl - total_fees
        net_pnl_pct = (net_pnl / buy_value) * 100 if buy_value > 0 else 0

        order_id = await self._simulate_paper_order(
            market_id=market.get("id") or market.get("conditionId"),
            token_id=position.token_id,
            side="sell",
            price=exit_price,
            size=position.quantity,
            outcome=position.outcome
        )

        if order_id:
            positions_taken = self._paper_state.positions_taken + 1  # Increment before reset
            self._paper_state.reset()  # Reset for next trade
            self._paper_state.positions_taken = positions_taken  # Restore incremented count
            max_positions = self.settings.max_positions_per_market
            await self._update_bot_state(
                last_action=f"[{reason}] Sold {position.outcome} @ {exit_price:.4f}, Net P&L: {net_pnl:+.4f} ({net_pnl_pct:+.1f}%) | Positions: {positions_taken}/{max_positions}"
            )
            logger.info(f"[{self._timestamp()}] [PAPER] ══════════════════════════════════════")
            logger.info(f"[{self._timestamp()}] [PAPER] POSITION CLOSED: {reason}")
            logger.info(f"[{self._timestamp()}] [PAPER] Side: {position.outcome}")
            logger.info(f"[{self._timestamp()}] [PAPER] Entry: {position.avg_price:.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Exit: {exit_price:.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Gross P&L: {gross_pnl:+.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Fees: -{total_fees:.4f} (buy: {buy_fee:.4f}, sell: {sell_fee:.4f})")
            logger.info(f"[{self._timestamp()}] [PAPER] Net P&L: {net_pnl:+.4f} ({net_pnl_pct:+.1f}%)")
            logger.info(f"[{self._timestamp()}] [PAPER] Positions taken: {positions_taken}/{max_positions}")
            logger.info(f"[{self._timestamp()}] [PAPER] ══════════════════════════════════════")

    async def _monitor_positions(self, market: Dict[str, Any]) -> None:
        """
        Monitor positions for exit conditions.

        Exit conditions:
        1. Max loss (0.3) - Square off all positions
        2. Price target (0.98) - Sell positions

        Note: Paper trading has its own monitoring in _execute_paper_trading_strategy
        Note: Live trading has its own monitoring in _monitor_live_position (stoploss orders)
        """
        # Paper trading handles its own position monitoring
        if self.settings.paper_trading:
            return

        # Live trading handles its own monitoring via _monitor_live_position
        # which uses stoploss limit orders - skip duplicate monitoring here
        if not self.settings.paper_trading:
            return

        positions = await self._get_positions_for_market(market)

        if not positions:
            return

        await self._update_bot_state(last_action=BotAction.MONITORING.value)

        total_pnl = 0.0
        for position in positions:
            # Get current price
            current_price = await self.client.get_current_price(position.token_id)
            if current_price is None:
                continue

            # Calculate P&L
            pnl = (current_price - position.avg_price) * position.quantity
            total_pnl += pnl

            # Update position in database
            await self._update_position(position.id, current_price, pnl)

            # Check price target
            if current_price >= self.settings.price_target:
                logger.info(f"Price target reached for {position.outcome}: {current_price}")
                await self._update_bot_state(last_action=BotAction.PRICE_TARGET.value)
                await self._place_order(
                    market=market,
                    token_id=position.token_id,
                    side="sell",
                    price=current_price - 0.01,  # Slightly below for fill
                    size=position.quantity,
                    outcome=position.outcome
                )

        # Check max loss
        if total_pnl <= -self.settings.max_loss:
            logger.warning(f"Max loss triggered! Total P&L: {total_pnl}")
            await self._update_bot_state(last_action=BotAction.MAX_LOSS.value)
            await self._square_off(market)

    async def _square_off(self, market: Dict[str, Any]) -> None:
        """Close all positions in the market."""
        await self._update_bot_state(last_action=BotAction.SQUARE_OFF.value)

        # Cancel all open orders first
        await self.client.cancel_all_orders()

        positions = await self._get_positions_for_market(market)

        for position in positions:
            if position.quantity > 0:
                current_price = await self.client.get_current_price(position.token_id)
                if current_price:
                    # Place market-like order (very low price for sell)
                    await self._place_order(
                        market=market,
                        token_id=position.token_id,
                        side="sell",
                        price=0.01,  # Near-market order
                        size=position.quantity,
                        outcome=position.outcome
                    )

        logger.info("Squared off all positions")

    async def _place_order(
        self,
        market: Dict[str, Any],
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> Optional[str]:
        """Place an order and record it in the database."""
        market_id = market.get("id") or market.get("conditionId")

        # Check for existing order
        order_key = f"{token_id}_{side}"
        if order_key in self._active_orders:
            existing = self._active_orders[order_key]
            # Skip if similar order already active
            if existing.get("status") in ["open", "pending"]:
                logger.debug(f"[{self._timestamp()}] Skipping duplicate order: {order_key}")
                return None

        # Check if paper trading is enabled
        is_paper = self.settings.paper_trading

        if is_paper:
            order_id = await self._simulate_paper_order(
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                outcome=outcome
            )
            return order_id

        # Live trading - place REAL order on Polymarket
        market_options = await self.client.get_market_options(market_id)
        tick_size = market_options.get("tick_size", "0.01")
        neg_risk = market_options.get("neg_risk", False)

        result = await self.client.place_limit_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            tick_size=tick_size,
            neg_risk=neg_risk
        )

        if result:
            order_id = result.get("orderID") or result.get("id")
            logger.info(f"[{self._timestamp()}] [LIVE] ORDER: {side.upper()} {outcome} {size} @ {price}")

            await self._record_trade(
                order_id=order_id,
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                is_paper=False
            )

            self._active_orders[order_key] = {
                "order_id": order_id,
                "status": "open",
                "price": price,
                "size": size
            }

            return order_id
        else:
            logger.error(f"[{self._timestamp()}] [LIVE] ORDER FAILED")
            return None

    def _calculate_taker_fee(self, trade_value: float) -> float:
        """
        Calculate taker fee for a trade.
        Fee = max(trade_value * fee_rate, min_fee)
        """
        fee = trade_value * self.settings.taker_fee_rate
        return max(fee, self.settings.min_taker_fee)

    async def _simulate_paper_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> Optional[str]:
        """
        Simulate a paper trade order.

        Paper trading orders always fill immediately at the specified price
        since we're simulating market orders at current prices.
        Includes taker fee calculation (configurable).
        """
        ENTRY_MIN = self.settings.entry_min
        ENTRY_MAX = self.settings.entry_max

        # CHECK: For buy orders, only allow if price is in entry range
        if side.lower() == "buy" and (price < ENTRY_MIN or price > ENTRY_MAX):
            logger.warning(f"[{self._timestamp()}] [PAPER] ✗ ORDER REJECTED: Buy {outcome} @ {price:.4f} not in range {ENTRY_MIN}-{ENTRY_MAX}")
            return None

        # Generate a unique paper order ID
        order_id = f"paper_{uuid.uuid4().hex[:16]}"

        # Calculate cost and fee for the trade
        trade_value = price * size
        taker_fee = self._calculate_taker_fee(trade_value)
        total_cost = trade_value + taker_fee  # Cost + fee for buys

        async with async_session_maker() as session:
            bot_state = await get_or_create_bot_state(session)

            # Check if we have enough paper balance for buy orders (including fee)
            if side.lower() == "buy":
                if bot_state.paper_balance < total_cost:
                    logger.warning(f"[{self._timestamp()}] [PAPER] Insufficient balance: {bot_state.paper_balance:.2f} < {total_cost:.2f} (cost: {trade_value:.2f} + fee: {taker_fee:.4f})")
                    return None

                # Deduct cost + fee from paper balance
                bot_state.paper_balance -= total_cost
                logger.info(f"[{self._timestamp()}] [PAPER] Deducted {total_cost:.4f} (cost: {trade_value:.4f} + fee: {taker_fee:.4f}) from balance. New balance: {bot_state.paper_balance:.4f}")

            await session.commit()

        # Record the paper trade - always FILLED for paper trading
        await self._record_trade(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            is_paper=True,
            status=OrderStatus.FILLED
        )

        # Update position immediately since paper orders always fill
        await self._update_paper_position(
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            outcome=outcome
        )

        # Track active order
        order_key = f"{token_id}_{side}"
        self._active_orders[order_key] = {
            "order_id": order_id,
            "status": "filled",
            "price": price,
            "size": size,
            "is_paper": True
        }

        return order_id

    async def _simulate_paper_order_unified(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> Optional[str]:
        """
        Simulate a paper trade order (UNIFIED with live trading).
        Uses trigger_price logic instead of entry_min/entry_max range.
        Paper orders always fill immediately at the specified price.
        """
        TRIGGER_PRICE = self.settings.trigger_price
        TARGET = self.settings.target

        # CHECK: For buy orders, only allow if price >= trigger_price and < target
        if side.lower() == "buy":
            if price < TRIGGER_PRICE:
                logger.warning(f"[{self._timestamp()}] [PAPER] ORDER REJECTED: Buy {outcome} @ {price:.4f} < trigger {TRIGGER_PRICE}")
                return None
            if price >= TARGET:
                logger.warning(f"[{self._timestamp()}] [PAPER] ORDER REJECTED: Buy {outcome} @ {price:.4f} >= target {TARGET}")
                return None

        # Generate a unique paper order ID
        order_id = f"paper_{uuid.uuid4().hex[:16]}"

        # Calculate cost and fee for the trade
        trade_value = price * size
        taker_fee = self._calculate_taker_fee(trade_value)
        total_cost = trade_value + taker_fee  # Cost + fee for buys

        async with async_session_maker() as session:
            bot_state = await get_or_create_bot_state(session)

            # Check if we have enough paper balance for buy orders (including fee)
            if side.lower() == "buy":
                if bot_state.paper_balance < total_cost:
                    logger.warning(f"[{self._timestamp()}] [PAPER] Insufficient balance: {bot_state.paper_balance:.2f} < {total_cost:.2f}")
                    return None

                # Deduct cost + fee from paper balance
                bot_state.paper_balance -= total_cost
                logger.info(f"[{self._timestamp()}] [PAPER] Deducted {total_cost:.4f} from balance. New balance: {bot_state.paper_balance:.4f}")

            await session.commit()

        # Record the paper trade - always FILLED for paper trading
        await self._record_trade(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            is_paper=True,
            status=OrderStatus.FILLED
        )

        # Update position immediately since paper orders always fill
        await self._update_paper_position_unified(
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            outcome=outcome
        )

        return order_id

    async def _update_paper_position_unified(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> None:
        """
        Update paper trading position after a fill (UNIFIED version).
        Includes taker fee in P&L calculation for both buy and sell sides.
        """
        async with async_session_maker() as session:
            # Find existing position
            result = await session.execute(
                select(Position).where(Position.token_id == token_id)
            )
            position = result.scalar_one_or_none()

            bot_state = await get_or_create_bot_state(session)

            if side.lower() == "buy":
                if position:
                    # Update existing position with average price
                    total_cost = (position.avg_price * position.quantity) + (price * size)
                    new_quantity = position.quantity + size
                    position.avg_price = total_cost / new_quantity
                    position.quantity = new_quantity
                    position.updated_at = datetime.utcnow()
                else:
                    # Create new position
                    position = Position(
                        market_id=market_id,
                        token_id=token_id,
                        outcome=outcome,
                        quantity=size,
                        avg_price=price,
                        current_price=price
                    )
                    session.add(position)

                bot_state.trades_count += 1

            elif side.lower() == "sell":
                if position and position.quantity >= size:
                    # Calculate fees for P&L
                    buy_value = position.avg_price * size
                    sell_value = price * size
                    buy_fee = self._calculate_taker_fee(buy_value)
                    sell_fee = self._calculate_taker_fee(sell_value)
                    total_fees = buy_fee + sell_fee

                    # Calculate P&L including fees
                    gross_pnl = (price - position.avg_price) * size
                    net_pnl = gross_pnl - total_fees

                    position.quantity -= size
                    position.current_pnl += net_pnl
                    position.updated_at = datetime.utcnow()

                    # Update bot state
                    bot_state.total_pnl += net_pnl
                    # Add proceeds minus sell fee to balance
                    net_proceeds = sell_value - sell_fee
                    bot_state.paper_balance += net_proceeds
                    bot_state.trades_count += 1

                    if net_pnl > 0:
                        bot_state.wins += 1
                    else:
                        bot_state.losses += 1

                    logger.info(f"[{self._timestamp()}] [PAPER] Sold {size} {outcome} @ {price:.4f} | Net P&L: {net_pnl:+.4f}")

            await session.commit()

    async def _update_paper_position(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> None:
        """
        Update paper trading position after a fill.
        Includes taker fee in P&L calculation for both buy and sell sides.
        """
        async with async_session_maker() as session:
            # Find existing position
            result = await session.execute(
                select(Position).where(Position.token_id == token_id)
            )
            position = result.scalar_one_or_none()

            bot_state = await get_or_create_bot_state(session)

            if side.lower() == "buy":
                if position:
                    # Update existing position with average price
                    total_cost = (position.avg_price * position.quantity) + (price * size)
                    new_quantity = position.quantity + size
                    position.avg_price = total_cost / new_quantity
                    position.quantity = new_quantity
                    position.updated_at = datetime.utcnow()
                else:
                    # Create new position
                    position = Position(
                        market_id=market_id,
                        token_id=token_id,
                        outcome=outcome,
                        quantity=size,
                        avg_price=price,
                        current_price=price
                    )
                    session.add(position)

                bot_state.trades_count += 1

            elif side.lower() == "sell":
                if position and position.quantity >= size:
                    # Calculate fees for P&L
                    buy_value = position.avg_price * size
                    sell_value = price * size
                    buy_fee = self._calculate_taker_fee(buy_value)
                    sell_fee = self._calculate_taker_fee(sell_value)
                    total_fees = buy_fee + sell_fee

                    # Calculate P&L including fees
                    # Gross P&L = (sell_price - buy_price) * size
                    # Net P&L = Gross P&L - buy_fee - sell_fee
                    gross_pnl = (price - position.avg_price) * size
                    net_pnl = gross_pnl - total_fees

                    position.quantity -= size
                    position.current_pnl += net_pnl
                    position.updated_at = datetime.utcnow()

                    # Update bot state
                    bot_state.total_pnl += net_pnl
                    # Add proceeds minus sell fee to balance
                    net_proceeds = sell_value - sell_fee
                    bot_state.paper_balance += net_proceeds
                    bot_state.trades_count += 1

                    if net_pnl > 0:
                        bot_state.wins += 1
                    else:
                        bot_state.losses += 1

                    logger.info(f"[{self._timestamp()}] [PAPER] Sold {size} {outcome} @ {price:.4f}")
                    logger.info(f"[{self._timestamp()}] [PAPER] Gross P&L: {gross_pnl:+.4f} | Fees: -{total_fees:.4f} (buy: {buy_fee:.4f}, sell: {sell_fee:.4f}) | Net P&L: {net_pnl:+.4f}")

            await session.commit()

    async def _record_trade(
        self,
        order_id: str,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        is_paper: bool = False,
        status: OrderStatus = OrderStatus.OPEN
    ) -> None:
        """Record a trade in the database."""
        async with async_session_maker() as session:
            trade = Trade(
                order_id=order_id,
                market_id=market_id,
                token_id=token_id,
                side=Side.BUY if side.lower() == "buy" else Side.SELL,
                price=price,
                size=size,
                status=status,
                is_paper=is_paper
            )
            session.add(trade)
            await session.commit()

    async def _update_trade_status(self, order_id: str, status: OrderStatus) -> None:
        """Update the status of a trade by order_id."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Trade).where(Trade.order_id == order_id)
            )
            trade = result.scalar_one_or_none()
            if trade:
                trade.status = status
                trade.updated_at = datetime.utcnow()
                await session.commit()
                logger.info(f"[{self._timestamp()}] [LIVE] Trade {order_id[:16]}... status updated to {status.value}")

    async def _update_live_position(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> None:
        """
        Update position for live trading after a fill.
        Similar to _update_paper_position but for live trades.
        """
        async with async_session_maker() as session:
            # Find existing position
            result = await session.execute(
                select(Position).where(Position.token_id == token_id)
            )
            position = result.scalar_one_or_none()

            bot_state = await get_or_create_bot_state(session)

            if side.lower() == "buy":
                if position:
                    # Update existing position with average price
                    total_cost = (position.avg_price * position.quantity) + (price * size)
                    new_quantity = position.quantity + size
                    position.avg_price = total_cost / new_quantity
                    position.quantity = new_quantity
                    position.updated_at = datetime.utcnow()
                else:
                    # Create new position
                    position = Position(
                        market_id=market_id,
                        token_id=token_id,
                        outcome=outcome,
                        quantity=size,
                        avg_price=price,
                        current_price=price
                    )
                    session.add(position)

                bot_state.trades_count += 1
                logger.info(f"[{self._timestamp()}] [LIVE] Position created/updated: BUY {size} {outcome} @ {price:.4f}")

            elif side.lower() == "sell":
                if position and position.quantity >= size:
                    # Calculate P&L
                    gross_pnl = (price - position.avg_price) * size

                    position.quantity -= size
                    position.current_pnl += gross_pnl
                    position.updated_at = datetime.utcnow()

                    # Update bot state
                    bot_state.total_pnl += gross_pnl
                    bot_state.trades_count += 1

                    if gross_pnl > 0:
                        bot_state.wins += 1
                    else:
                        bot_state.losses += 1

                    logger.info(f"[{self._timestamp()}] [LIVE] Position updated: SELL {size} {outcome} @ {price:.4f} | P&L: {gross_pnl:+.4f}")

            await session.commit()

    async def _get_positions_for_market(self, market: Dict[str, Any]) -> List[Position]:
        """Get positions for a specific market from database."""
        market_id = market.get("id") or market.get("conditionId")

        async with async_session_maker() as session:
            result = await session.execute(
                select(Position).where(Position.market_id == market_id)
            )
            return list(result.scalars().all())

    async def _update_position(
        self,
        position_id: int,
        current_price: float,
        pnl: float
    ) -> None:
        """Update position with current price and P&L."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Position).where(Position.id == position_id)
            )
            position = result.scalar_one_or_none()
            if position:
                position.current_price = current_price
                position.current_pnl = pnl
                position.updated_at = datetime.utcnow()
                await session.commit()

    async def _update_bot_state(
        self,
        is_running: Optional[bool] = None,
        last_action: Optional[str] = None,
        current_market_id: Optional[str] = None,
        total_pnl: Optional[float] = None
    ) -> None:
        """Update bot state in database."""
        async with async_session_maker() as session:
            bot_state = await get_or_create_bot_state(session)

            if is_running is not None:
                bot_state.is_running = is_running
            if last_action is not None:
                bot_state.last_action = last_action
            if current_market_id is not None:
                bot_state.current_market_id = current_market_id
            if total_pnl is not None:
                bot_state.total_pnl = total_pnl

            bot_state.updated_at = datetime.utcnow()
            await session.commit()

    async def get_status(self) -> Dict[str, Any]:
        """Get current bot status."""
        async with async_session_maker() as session:
            bot_state = await get_or_create_bot_state(session)

            time_to_close = None
            if bot_state.current_market_id and self.client:
                time_to_close = await self.client.get_time_to_close(
                    bot_state.current_market_id
                )

            # The ACTUAL trading mode is determined by config, not database
            config_paper_trading = self.settings.paper_trading
            trading_mode = "PAPER (Simulated)" if config_paper_trading else "LIVE (Real Money)"

            # Get live balance from Polymarket
            live_balance = None
            if self.client and self.client.is_connected and not config_paper_trading:
                live_balance = await self.client.get_balance()

            return {
                "is_running": bot_state.is_running,
                "current_market_id": bot_state.current_market_id,
                "last_action": bot_state.last_action,
                "total_pnl": bot_state.total_pnl,
                "trades_count": bot_state.trades_count,
                "wins": bot_state.wins,
                "losses": bot_state.losses,
                "updated_at": bot_state.updated_at,
                "time_to_close": time_to_close,
                "paper_trading": config_paper_trading,
                "trading_mode": trading_mode,
                "paper_balance": bot_state.paper_balance,
                "paper_starting_balance": bot_state.paper_starting_balance,
                "live_balance": live_balance
            }

    async def set_paper_trading(self, enabled: bool) -> None:
        """Enable or disable paper trading mode."""
        async with async_session_maker() as session:
            bot_state = await get_or_create_bot_state(session)
            bot_state.paper_trading = enabled

            # Reset paper balance when enabling
            if enabled:
                bot_state.paper_balance = self.settings.paper_balance
                bot_state.paper_starting_balance = self.settings.paper_balance

            await session.commit()
            logger.info(f"Paper trading {'enabled' if enabled else 'disabled'}")


# Singleton instance
_bot: Optional[TradingBot] = None


def get_trading_bot() -> TradingBot:
    """Get or create the trading bot singleton."""
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot
