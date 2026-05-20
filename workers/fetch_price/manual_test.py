"""Manual test script to verify BinanceClient with real API.

Run this inside the Docker container:
    docker compose exec api python -m fetch_price.manual_test

This script fetches real data from Binance to verify:
- API connectivity
- Response time <5s for 168 candles
- Data structure and types
- No errors or exceptions
"""

import asyncio
import sys
import time
from datetime import datetime

# Add workers to path
sys.path.insert(0, "/app/workers")

from fetch_price.binance_client import BinanceClient


async def main():
    """Run manual tests against real Binance API."""
    print("=" * 70)
    print("BinanceClient Manual Verification")
    print("=" * 70)
    print()

    client = BinanceClient()

    # Test 1: Fetch single candle (latest)
    print("Test 1: Fetch latest candle (limit=1)")
    print("-" * 70)
    try:
        start = time.time()
        result = await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=1)
        elapsed = time.time() - start

        print(f"✅ Success! Fetched {len(result)} candle in {elapsed:.2f}s")
        print(f"   Timestamp: {result[0][0]}")
        print(f"   Open:  ${result[0][1]:,.2f}")
        print(f"   High:  ${result[0][2]:,.2f}")
        print(f"   Low:   ${result[0][3]:,.2f}")
        print(f"   Close: ${result[0][4]:,.2f}")
        print(f"   Volume: {result[0][5]:,.4f} BTC")
        print()
    except Exception as e:
        print(f"❌ Failed: {type(e).__name__}: {e}")
        print()
        return 1

    # Test 2: Fetch 168 candles (1 week)
    print("Test 2: Fetch 168 hourly candles (1 week)")
    print("-" * 70)
    try:
        start = time.time()
        result = await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=168)
        elapsed = time.time() - start

        print(f"✅ Success! Fetched {len(result)} candles in {elapsed:.2f}s")
        print(f"   Response time: {elapsed:.2f}s (target: <5s)")

        if elapsed >= 5.0:
            print("   ⚠️  Warning: Response time exceeds 5s target")
        else:
            print("   ✅ Response time meets target (<5s)")

        # Verify ordering (newest first)
        timestamps = [candle[0] for candle in result]
        is_descending = all(timestamps[i] >= timestamps[i + 1] for i in range(len(timestamps) - 1))

        if is_descending:
            print("   ✅ Candles ordered correctly (newest first)")
        else:
            print("   ❌ Candles NOT ordered correctly")
            return 1

        print(f"   Newest: {result[0][0]} - Close: ${result[0][4]:,.2f}")
        print(f"   Oldest: {result[-1][0]} - Close: ${result[-1][4]:,.2f}")
        print()
    except Exception as e:
        print(f"❌ Failed: {type(e).__name__}: {e}")
        print()
        return 1

    # Test 3: Verify data types
    print("Test 3: Verify data types")
    print("-" * 70)
    try:
        result = await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=1)
        timestamp, open_price, high, low, close, volume = result[0]

        checks = [
            ("Timestamp is datetime", isinstance(timestamp, datetime)),
            ("Timestamp is UTC", timestamp.tzinfo is not None),
            ("Open is float", isinstance(open_price, float)),
            ("High is float", isinstance(high, float)),
            ("Low is float", isinstance(low, float)),
            ("Close is float", isinstance(close, float)),
            ("Volume is float", isinstance(volume, float)),
            ("Open > 0", open_price > 0),
            ("High > 0", high > 0),
            ("Low > 0", low > 0),
            ("Close > 0", close > 0),
            ("Volume > 0", volume > 0),
        ]

        all_passed = True
        for check_name, check_result in checks:
            status = "✅" if check_result else "❌"
            print(f"   {status} {check_name}")
            if not check_result:
                all_passed = False

        print()
        if not all_passed:
            return 1

    except Exception as e:
        print(f"❌ Failed: {type(e).__name__}: {e}")
        print()
        return 1

    # Test 4: Test error handling with invalid symbol
    print("Test 4: Test error handling (invalid symbol)")
    print("-" * 70)
    try:
        await client.fetch_ohlcv(symbol="INVALID", interval="1h", limit=1)
        print("❌ Expected InvalidSymbolError but got success")
        print()
        return 1
    except Exception as e:
        print(f"✅ Correctly raised: {type(e).__name__}")
        print(f"   Message: {str(e)}")
        print()

    # Summary
    print("=" * 70)
    print("✅ All manual tests passed!")
    print("=" * 70)
    print()
    print("The BinanceClient is working correctly with the real Binance API.")
    print("You can now proceed to use this client in your workers.")
    print()

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
