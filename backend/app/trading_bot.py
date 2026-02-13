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
    PAPER_WATCHING = "Watching for entry at 0.75"
    PAPER_BOUGHT = "Paper position opened"
    PAPER_MONITORING = "Monitoring SL/Target"


class PaperTradingState:
    """Track paper trading strategy state."""
    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all state."""
        self.position_open: bool = False
        self.entry_price: float = 0.0
        self.entry_side: Optional[str] = None  # "YES" or "NO"
        self.entry_token_id: Optional[str] = None


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

        # Reset paper trading state
        self._paper_state.reset()

        # Update database state
        await self._update_bot_state(
            is_running=True,
            last_action=BotAction.STARTED.value,
            current_market_id=market_id
        )

        # Start the main trading loop
        self._task = asyncio.create_task(self._run_strategy(market_id))
        logger.info(f"Trading bot started with market_id: {market_id}")
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
                        logger.info(f"[{self._timestamp()}] [BOT] Market expired: {market_title}")
                        logger.info(f"[{self._timestamp()}] [BOT] Searching for next 5-minute market...")

                        # Reset state for new market
                        self._paper_state.reset()
                        current_market_id = None  # Force auto-discovery for next market

                        await self._update_bot_state(
                            last_action="Market expired, searching for next..."
                        )
                        await asyncio.sleep(2)
                        continue

                    # Check if we switched to a new market
                    if self._current_market and (self._current_market.get("id") != market_id):
                        logger.info(f"[{self._timestamp()}] [BOT] Switched to new market: {market_title}")
                        self._paper_state.reset()

                    self._current_market = market
                    current_market_id = market_id  # Track for next iteration

                    logger.info(f"[{self._timestamp()}] [BOT] Trading: {market_title} | {time_to_close:.1f} min left")

                    await self._update_bot_state(
                        current_market_id=market_id,
                        last_action=f"Trading: {market_title}..."
                    )

                    # For paper trading, trade immediately regardless of time threshold
                    # For live trading, wait for time threshold
                    if not self.settings.paper_trading and time_to_close > self.settings.time_threshold:
                        await self._update_bot_state(
                            last_action=f"{BotAction.WAITING.value} ({time_to_close:.1f} min to close)"
                        )
                        await asyncio.sleep(self.settings.position_check_interval)
                        continue

                    # Execute trading logic
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

        # Use different strategy for paper trading
        if self.settings.paper_trading:
            await self._execute_paper_trading_strategy(
                market=market,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id
            )
            return

        # Live trading - original strategy
        # Check current positions
        positions = await self._get_positions_for_market(market)

        await self._update_bot_state(last_action=BotAction.PLACING_ORDERS.value)

        if not positions:
            # No positions - place buy orders on both YES and NO
            await self._place_order(
                market=market,
                token_id=yes_token_id,
                side="buy",
                price=self.settings.buy_price,
                size=self.settings.order_size,
                outcome="YES"
            )

            await self._place_order(
                market=market,
                token_id=no_token_id,
                side="buy",
                price=self.settings.buy_price,
                size=self.settings.order_size,
                outcome="NO"
            )
        else:
            # Check for filled buy orders and place corresponding sells
            for position in positions:
                if position.quantity > 0:
                    # We have a position, place sell order at 0.5
                    await self._place_order(
                        market=market,
                        token_id=position.token_id,
                        side="sell",
                        price=self.settings.sell_price,
                        size=position.quantity,
                        outcome=position.outcome
                    )

    async def _execute_paper_trading_strategy(
        self,
        market: Dict[str, Any],
        yes_token_id: str,
        no_token_id: str
    ) -> None:
        """
        Paper trading strategy:
        1. Entry: Buy when price >= 0.80
        2. Stop Loss: Exit when price drops to 0.50-0.55 range
        3. Target: Exit when price reaches 0.98-1.0 range
        4. Re-entry: After position closes, look for new signal if time >= 30 seconds
        """
        # Price levels
        ENTRY_SIGNAL = 0.80      # Buy when price >= 0.80
        STOPLOSS = 0.55          # Exit when price < 0.55
        TARGET = 0.98            # Exit when price > 0.98
        MIN_TIME_FOR_ENTRY = 0.167  # 10 seconds = 0.167 minutes

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

        # Check if we have a position
        positions = await self._get_positions_for_market(market)
        has_position = any(p.quantity > 0 for p in positions)

        if has_position:
            self._paper_state.position_open = True
            # Monitor position for stoploss/target
            await self._monitor_paper_position(
                market, positions,
                stoploss=STOPLOSS,
                target=TARGET
            )
            return

        # No position - check if we can enter
        if self._paper_state.position_open:
            logger.info(f"[{self._timestamp()}] [PAPER] Position closed, looking for re-entry...")
            self._paper_state.reset()

        # Check if enough time remaining for new entry (>= 10 seconds)
        if time_to_close < MIN_TIME_FOR_ENTRY:
            logger.info(f"[{self._timestamp()}] [PAPER] Not enough time for entry: {time_to_close:.2f} min < 0.17 min (10s)")
            await self._update_bot_state(
                last_action=f"Waiting for next market (time left: {time_to_close:.1f} min)"
            )
            return

        # Watch for entry signal: Buy when price >= 0.80
        await self._update_bot_state(
            last_action=f"{BotAction.PAPER_WATCHING.value} | YES: {yes_price:.3f}, NO: {no_price:.3f}"
        )

        # Check YES side for entry signal (price >= 0.80)
        if yes_price >= ENTRY_SIGNAL:
            logger.info(f"[{self._timestamp()}] [PAPER] ✓ Entry signal: YES @ {yes_price:.4f} >= {ENTRY_SIGNAL}")
            await self._place_paper_entry(
                market=market,
                token_id=yes_token_id,
                side="YES",
                price=yes_price
            )
            return

        # Check NO side for entry signal (price >= 0.80)
        if no_price >= ENTRY_SIGNAL:
            logger.info(f"[{self._timestamp()}] [PAPER] ✓ Entry signal: NO @ {no_price:.4f} >= {ENTRY_SIGNAL}")
            await self._place_paper_entry(
                market=market,
                token_id=no_token_id,
                side="NO",
                price=no_price
            )
            return

        # Log when waiting for signal
        logger.debug(f"[{self._timestamp()}] [PAPER] Waiting for entry signal - need price >= {ENTRY_SIGNAL}")

    async def _place_paper_entry(
        self,
        market: Dict[str, Any],
        token_id: str,
        side: str,
        price: float
    ) -> None:
        """Place a paper trading entry order. Entry signal: price >= 0.80"""
        ENTRY_SIGNAL = 0.80

        # CHECK: Only buy if price >= entry signal
        if price < ENTRY_SIGNAL:
            logger.warning(f"[{self._timestamp()}] [PAPER] ✗ REJECTED: {side} @ {price:.4f} < {ENTRY_SIGNAL} (need >= {ENTRY_SIGNAL})")
            return

        order_id = await self._simulate_paper_order(
            market_id=market.get("id") or market.get("conditionId"),
            token_id=token_id,
            side="buy",
            price=price,
            size=self.settings.order_size,
            outcome=side
        )

        if order_id:
            self._paper_state.position_open = True
            self._paper_state.entry_price = price
            self._paper_state.entry_side = side
            self._paper_state.entry_token_id = token_id
            await self._update_bot_state(
                last_action=f"{BotAction.PAPER_BOUGHT.value}: {side} @ {price:.4f}"
            )
            logger.info(f"[{self._timestamp()}] [PAPER] ★ Position opened: {side} @ {price:.4f} | SL: <0.55 | Target: >0.98")

    async def _monitor_paper_position(
        self,
        market: Dict[str, Any],
        positions: List[Position],
        stoploss: float = 0.55,
        target: float = 0.98
    ) -> None:
        """
        Monitor paper position for stoploss/target exit.
        - Target: exit when price > 0.98
        - Stoploss: exit when price < 0.55
        - Market close: If neither hit, close at market expiry as TARGET_1
        """
        # Check time to market close
        time_to_close = market.get("time_to_close_minutes", float("inf"))
        MARKET_CLOSE_THRESHOLD = 0.1  # 6 seconds - close position before market ends

        for position in positions:
            if position.quantity <= 0:
                continue

            current_price = await self.client.get_current_price(position.token_id)
            if current_price is None:
                continue

            pnl = (current_price - position.avg_price) * position.quantity
            pnl_pct = ((current_price - position.avg_price) / position.avg_price) * 100 if position.avg_price > 0 else 0

            await self._update_bot_state(
                last_action=f"{BotAction.PAPER_MONITORING.value} | {position.outcome}: {current_price:.4f} (P&L: {pnl_pct:+.1f}%) | {time_to_close:.1f}m left"
            )

            logger.info(f"[{self._timestamp()}] [MONITOR] {position.outcome}: {current_price:.4f} | Entry: {position.avg_price:.4f} | P&L: {pnl_pct:+.1f}% | Time: {time_to_close:.2f}m | SL: <{stoploss} | Target: >{target}")

            # Check target: exit when price > 0.98
            if current_price > target:
                logger.info(f"[{self._timestamp()}] [PAPER] ★ TARGET REACHED! {position.outcome} @ {current_price:.4f} > {target}")
                await self._exit_paper_position(market, position, current_price, "TARGET")
                return

            # Check stoploss: exit when price < 0.55
            if current_price < stoploss:
                logger.info(f"[{self._timestamp()}] [PAPER] ✗ STOPLOSS HIT! {position.outcome} @ {current_price:.4f} < {stoploss}")
                await self._exit_paper_position(market, position, current_price, "STOPLOSS")
                return

            # Check market close: exit before market ends, consider as TARGET_1
            if time_to_close <= MARKET_CLOSE_THRESHOLD:
                logger.info(f"[{self._timestamp()}] [PAPER] ◆ MARKET CLOSE - TARGET_1! {position.outcome} @ {current_price:.4f} | Time: {time_to_close:.2f}m")
                await self._exit_paper_position(market, position, current_price, "TARGET_1")
                return

    async def _exit_paper_position(
        self,
        market: Dict[str, Any],
        position: Position,
        exit_price: float,
        reason: str
    ) -> None:
        """Exit a paper position."""
        order_id = await self._simulate_paper_order(
            market_id=market.get("id") or market.get("conditionId"),
            token_id=position.token_id,
            side="sell",
            price=exit_price,
            size=position.quantity,
            outcome=position.outcome
        )

        if order_id:
            pnl = (exit_price - position.avg_price) * position.quantity
            pnl_pct = ((exit_price - position.avg_price) / position.avg_price) * 100 if position.avg_price > 0 else 0
            self._paper_state.reset()  # Reset for next trade
            await self._update_bot_state(
                last_action=f"[{reason}] Sold {position.outcome} @ {exit_price:.4f}, P&L: {pnl:+.4f} ({pnl_pct:+.1f}%)"
            )
            logger.info(f"[{self._timestamp()}] [PAPER] ══════════════════════════════════════")
            logger.info(f"[{self._timestamp()}] [PAPER] POSITION CLOSED: {reason}")
            logger.info(f"[{self._timestamp()}] [PAPER] Side: {position.outcome}")
            logger.info(f"[{self._timestamp()}] [PAPER] Entry: {position.avg_price:.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] Exit: {exit_price:.4f}")
            logger.info(f"[{self._timestamp()}] [PAPER] P&L: {pnl:+.4f} ({pnl_pct:+.1f}%)")
            logger.info(f"[{self._timestamp()}] [PAPER] ══════════════════════════════════════")

    async def _monitor_positions(self, market: Dict[str, Any]) -> None:
        """
        Monitor positions for exit conditions.

        Exit conditions:
        1. Max loss (0.3) - Square off all positions
        2. Price target (0.98) - Sell positions

        Note: Paper trading has its own monitoring in _execute_paper_trading_strategy
        """
        # Paper trading handles its own position monitoring
        if self.settings.paper_trading:
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
                return None

        # Check if paper trading is enabled
        is_paper = self.settings.paper_trading

        if is_paper:
            # Paper trading - simulate the order
            order_id = await self._simulate_paper_order(
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                outcome=outcome
            )
            if order_id:
                logger.info(f"[PAPER] Placed {side} order for {outcome}: {size} @ {price}")
                return order_id
            return None

        # Live trading - place real order
        result = await self.client.place_limit_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size
        )

        if result:
            order_id = result.get("orderID") or result.get("id")

            # Record in database
            await self._record_trade(
                order_id=order_id,
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                is_paper=False
            )

            # Track active order
            self._active_orders[order_key] = {
                "order_id": order_id,
                "status": "open",
                "price": price,
                "size": size
            }

            logger.info(f"Placed {side} order for {outcome}: {size} @ {price}")
            return order_id

        return None

    async def _simulate_paper_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> Optional[str]:
        """Simulate a paper trade order. Entry signal: price >= 0.80"""
        ENTRY_SIGNAL = 0.80

        # CHECK: For buy orders, only allow if price >= entry signal
        if side.lower() == "buy" and price < ENTRY_SIGNAL:
            logger.warning(f"[{self._timestamp()}] [PAPER] ✗ ORDER REJECTED: Buy {outcome} @ {price:.4f} < {ENTRY_SIGNAL}")
            return None

        # Generate a unique paper order ID
        order_id = f"paper_{uuid.uuid4().hex[:16]}"

        # Get current market price to check if order would fill
        current_price = await self.client.get_current_price(token_id)

        # Determine if order fills immediately based on current price
        order_fills = False
        if current_price is not None:
            if side.lower() == "buy" and current_price <= price:
                order_fills = True
            elif side.lower() == "sell" and current_price >= price:
                order_fills = True

        # Calculate cost for buy orders
        cost = price * size

        async with async_session_maker() as session:
            bot_state = await get_or_create_bot_state(session)

            # Check if we have enough paper balance for buy orders
            if side.lower() == "buy":
                if bot_state.paper_balance < cost:
                    logger.warning(f"[{self._timestamp()}] [PAPER] Insufficient balance: {bot_state.paper_balance:.2f} < {cost:.2f}")
                    return None

                # Deduct from paper balance
                bot_state.paper_balance -= cost
                logger.info(f"[{self._timestamp()}] [PAPER] Deducted {cost:.4f} from balance. New balance: {bot_state.paper_balance:.4f}")

            await session.commit()

        # Record the paper trade
        status = OrderStatus.FILLED if order_fills else OrderStatus.OPEN
        await self._record_trade(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            is_paper=True,
            status=status
        )

        # If order fills, update position
        if order_fills:
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
            "status": "filled" if order_fills else "open",
            "price": price,
            "size": size,
            "is_paper": True
        }

        return order_id

    async def _update_paper_position(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        outcome: str
    ) -> None:
        """Update paper trading position after a fill."""
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
                    # Calculate P&L
                    pnl = (price - position.avg_price) * size
                    position.quantity -= size
                    position.current_pnl += pnl
                    position.updated_at = datetime.utcnow()

                    # Update bot state
                    bot_state.total_pnl += pnl
                    bot_state.paper_balance += price * size  # Add proceeds
                    bot_state.trades_count += 1

                    if pnl > 0:
                        bot_state.wins += 1
                    else:
                        bot_state.losses += 1

                    logger.info(f"[{self._timestamp()}] [PAPER] Sold {size} {outcome} @ {price:.4f}, P&L: {pnl:.4f}")

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
                "paper_trading": bot_state.paper_trading,
                "paper_balance": bot_state.paper_balance,
                "paper_starting_balance": bot_state.paper_starting_balance
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
