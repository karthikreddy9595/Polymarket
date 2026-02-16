"""
Test script to verify the order retry logic is working.
Run this to test:
1. is_order_active() method
2. get_open_orders() method
3. get_top_bids() method (orderbook)
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.polymarket_client import get_polymarket_client


async def test_order_methods():
    """Test the order checking methods."""
    print("=" * 60)
    print("Testing Order Retry Logic Methods")
    print("=" * 60)

    # Get client
    client = await get_polymarket_client()

    # Connect
    print("\n[1] Connecting to Polymarket...")
    connected = await client.connect()
    if not connected:
        print("ERROR: Failed to connect to Polymarket")
        return
    print("SUCCESS: Connected to Polymarket")

    # Test get_open_orders
    print("\n[2] Testing get_open_orders()...")
    try:
        open_orders = await client.get_open_orders()
        print(f"SUCCESS: get_open_orders() returned {len(open_orders)} orders")

        if open_orders:
            print("\nActive orders found:")
            for i, order in enumerate(open_orders[:5]):  # Show first 5
                order_id = order.get("id") or order.get("orderID") or "N/A"
                status = order.get("status", "N/A")
                side = order.get("side", "N/A")
                price = order.get("price", "N/A")
                size = order.get("size", "N/A")
                print(f"  [{i+1}] ID: {order_id[:20]}... | Status: {status} | {side} {size} @ {price}")
        else:
            print("No active orders found (this is normal if you have no open positions)")
    except Exception as e:
        print(f"ERROR: get_open_orders() failed: {e}")

    # Test is_order_active with a fake order ID (should return False)
    print("\n[3] Testing is_order_active() with fake order ID...")
    try:
        fake_order_id = "0x1234567890abcdef1234567890abcdef12345678"
        is_active = await client.is_order_active(fake_order_id)
        print(f"SUCCESS: is_order_active(fake_id) returned: {is_active}")
        if not is_active:
            print("CORRECT: Fake order ID correctly identified as not active")
        else:
            print("WARNING: Fake order ID should return False")
    except Exception as e:
        print(f"ERROR: is_order_active() failed: {e}")

    # Test is_order_active with real order if exists
    if open_orders and len(open_orders) > 0:
        print("\n[4] Testing is_order_active() with real order ID...")
        real_order_id = open_orders[0].get("id") or open_orders[0].get("orderID")
        if real_order_id:
            try:
                is_active = await client.is_order_active(real_order_id)
                print(f"SUCCESS: is_order_active(real_id) returned: {is_active}")
                if is_active:
                    print("CORRECT: Real active order correctly identified as active")
            except Exception as e:
                print(f"ERROR: is_order_active() failed: {e}")

    # Test get_top_bids with a sample token (BTC market)
    print("\n[5] Testing get_top_bids() - Fetching orderbook...")
    try:
        # Find a BTC 5-min market to test with
        btc_markets = await client.find_btc_5min_markets()
        if btc_markets:
            market = btc_markets[0]
            tokens = market.get("tokens", [])
            if tokens:
                token_id = tokens[0].get("token_id")
                print(f"Using token from market: {market.get('question', 'N/A')[:50]}...")

                # Get top 5 bids
                top_bids = await client.get_top_bids(token_id, count=5)
                if top_bids:
                    print(f"SUCCESS: get_top_bids() returned {len(top_bids)} bid prices")
                    print(f"\nTop 5 bid prices (highest to lowest):")
                    for i, price in enumerate(top_bids):
                        print(f"  [{i+1}] ${price:.4f}")
                else:
                    print("WARNING: get_top_bids() returned empty (no bids in orderbook)")

                # Also show the full orderbook for reference
                print("\n[6] Full orderbook sample...")
                orderbook = await client.get_orderbook(token_id)
                if orderbook:
                    bids = orderbook.get("bids", [])[:5]
                    asks = orderbook.get("asks", [])[:5]
                    print(f"Bids (top 5): {bids}")
                    print(f"Asks (top 5): {asks}")
            else:
                print("WARNING: No tokens found in market")
        else:
            print("WARNING: No BTC markets found to test orderbook")
    except Exception as e:
        print(f"ERROR: get_top_bids() failed: {e}")

    # Cleanup
    await client.close()

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
    print("\nTo test the full retry logic in action:")
    print("1. Run the trading bot in LIVE mode")
    print("2. Enter a position")
    print("3. Wait for stoploss to trigger OR manually trigger via price drop")
    print("4. Watch the logs for messages like:")
    print("   - 'Using orderbook bids for sell: [0.48, 0.47, 0.46, ...]'")
    print("   - 'Market SELL attempt X/5: ... (bid price)'")
    print("   - 'Order still active (unfilled), cancelling and retrying'")
    print("   - 'Refreshed orderbook bids: [...]'")
    print("   - 'Sell order FILLED (not in active orders)'")


if __name__ == "__main__":
    asyncio.run(test_order_methods())
