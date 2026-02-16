"""Test script to verify BTC price filter is working correctly."""

import asyncio
import sys
import os

# Fix Windows console encoding
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')

sys.path.insert(0, '.')

from app.btc_price_service import BTCPriceService
from app.polymarket_client import PolymarketClient


async def test_btc_price_service():
    print("=" * 70)
    print("BTC Price Filter Test")
    print("=" * 70)

    # First, find a current market to get the slug
    print("\n[1] Finding current Bitcoin Up/Down market...")
    client = PolymarketClient()
    markets = await client.find_btc_5min_markets()

    if not markets:
        print("No markets found!")
        return

    market = markets[0]
    market_slug = market.get("slug")
    market_title = market.get("question", "Unknown")
    time_to_close = market.get("time_to_close_minutes", 0)

    print(f"  Market: {market_title}")
    print(f"  Slug: {market_slug}")
    print(f"  Time to close: {time_to_close:.2f} minutes")

    if not market_slug:
        print("  ERROR: No slug found in market data!")
        print(f"  Available keys: {list(market.keys())}")
        return

    # Test BTC price service
    print("\n[2] Testing BTC Price Service...")
    service = BTCPriceService()
    await service.start()

    try:
        # Test 1: Fetch market open price
        print("\n[3] Fetching market open price from Polymarket website...")
        price_to_beat = await service.fetch_price_to_beat(market_slug)

        if price_to_beat:
            print(f"  [OK] Market open: ${price_to_beat:,.2f}")
        else:
            print("  [FAIL] Could not fetch market open price")
            print("  Trying manual set for testing...")
            # For testing, set a manual price
            service.set_price_to_beat(97000.0, market_slug)
            print(f"  Set manual market open price: $97,000.00")

        # Test 2: Get live BTC price
        print("\n[4] Fetching live BTC price...")
        live_price = await service.get_live_btc_price()

        if live_price:
            print(f"  [OK] Live BTC price: ${live_price:,.2f}")
        else:
            print("  [FAIL] Could not fetch live price")
            return

        # Test 3: Calculate difference
        print("\n[5] Calculating price difference...")
        difference = await service.get_price_difference()

        if difference is not None:
            direction = "UP" if difference > 0 else "DOWN" if difference < 0 else "FLAT"
            print(f"  [OK] Difference: ${difference:+,.2f} ({direction})")
            print(f"  [OK] Absolute: ${abs(difference):,.2f}")
        else:
            print("  [FAIL] Could not calculate difference")

        # Test 4: Check order placement with different thresholds
        print("\n[6] Testing order placement decisions...")

        thresholds = [5, 10, 20, 50, 100, 200]
        for threshold in thresholds:
            should_place, info = await service.should_place_order(min_difference=threshold)
            status = "[ALLOW]" if should_place else "[BLOCK]"
            abs_diff = info.get('abs_difference', 0)
            print(f"  Threshold ${threshold}: {status} (diff: ${abs_diff:,.2f})")

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Market: {market_title}")
        print(f"Market open: ${service.price_to_beat:,.2f}" if service.price_to_beat else "Market open: Not set")
        print(f"Live BTC price: ${live_price:,.2f}")
        if service.price_to_beat:
            diff = live_price - service.price_to_beat
            print(f"Difference: ${diff:+,.2f} ({'UP' if diff > 0 else 'DOWN' if diff < 0 else 'FLAT'})")
            print(f"\nWith $10 threshold: {'ORDER ALLOWED' if abs(diff) >= 10 else 'ORDER BLOCKED'}")
        print("=" * 70)

    finally:
        await service.stop()


if __name__ == "__main__":
    print("\nRunning BTC Price Filter Test...\n")
    asyncio.run(test_btc_price_service())
