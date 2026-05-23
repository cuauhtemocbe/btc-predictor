"""
Test script to validate CoinGecko OHLC granularity for different day ranges.

This script tests the actual granularity returned by CoinGecko API for different
values of the `days` parameter to confirm the documentation claims.

Expected granularity (CoinGecko free plan):
- days=1-2: 30 minutes
- days=3-30: 4 hours
- days=31+: 4 days
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "workers"))

from fetch_price.coingecko_client import CoinGeckoClient


async def test_granularity(days: int) -> None:
    """
    Test CoinGecko OHLC granularity for a specific day range.

    Args:
        days: Number of days to fetch
    """
    print(f"\n{'='*70}")
    print(f"Testing days={days}")
    print(f"{'='*70}")

    client = CoinGeckoClient()

    try:
        # Fetch OHLC data
        data = await client.fetch_ohlcv("bitcoin", "usd", days=days)

        num_candles = len(data)
        print(f"✓ Fetched {num_candles} candles")

        if num_candles == 0:
            print("⚠️  No data returned")
            return

        # Analyze timestamps
        timestamps = [candle["timestamp"] for candle in data]
        timestamps.sort()

        # Calculate intervals between candles
        intervals = []
        for i in range(1, len(timestamps)):
            interval_seconds = (timestamps[i] - timestamps[0]).total_seconds()
            interval_hours = interval_seconds / 3600

            if i == 1:
                first_interval = interval_hours
                intervals.append(first_interval)
            elif i < 10:  # Sample first 10 intervals
                intervals.append(interval_hours)

        # Calculate average interval
        if len(data) > 1:
            total_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600
            avg_interval_hours = total_hours / (num_candles - 1)

            print(f"\nDate range: {timestamps[0].date()} to {timestamps[-1].date()}")
            print(f"Total span: {total_hours:.1f} hours ({total_hours/24:.1f} days)")
            print(f"Average interval: {avg_interval_hours:.2f} hours")

            # Determine granularity
            if avg_interval_hours < 1:
                granularity = f"{avg_interval_hours * 60:.0f} minutes"
            elif avg_interval_hours < 24:
                granularity = f"{avg_interval_hours:.1f} hours"
            else:
                granularity = f"{avg_interval_hours / 24:.1f} days"

            print(f"Detected granularity: {granularity}")

            # Expected granularity based on docs
            if days <= 2:
                expected = "30 minutes"
            elif days <= 30:
                expected = "4 hours"
            else:
                expected = "4 days"

            print(f"Expected granularity: {expected}")

            # Validation
            tolerance = 0.1  # 10% tolerance
            if days <= 2:
                expected_hours = 0.5
            elif days <= 30:
                expected_hours = 4
            else:
                expected_hours = 96  # 4 days

            if abs(avg_interval_hours - expected_hours) / expected_hours <= tolerance:
                print("✅ Granularity matches documentation")
            else:
                print("❌ Granularity DOES NOT match documentation")

            # Show sample data
            print(f"\nFirst 3 candles:")
            for i, candle in enumerate(data[:3]):
                print(f"  {i+1}. {candle['timestamp'].isoformat()} - "
                      f"O:{candle['open']:.2f} H:{candle['high']:.2f} "
                      f"L:{candle['low']:.2f} C:{candle['close']:.2f}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Run granularity tests for different day ranges."""
    print("\n" + "="*70)
    print("CoinGecko OHLC Granularity Test")
    print("="*70)
    print("\nTesting different day ranges to confirm actual granularity...")

    # Test cases based on documentation
    test_cases = [
        1,    # Expected: 30 minutes (48 candles)
        2,    # Expected: 30 minutes (96 candles)
        7,    # Expected: 4 hours (42 candles)
        30,   # Expected: 4 hours (180 candles) ← TARGET
        31,   # Expected: 4 DAYS (starts degrading)
        90,   # Expected: 4 DAYS (~22 candles)
        365,  # Expected: 4 DAYS (~92 candles)
    ]

    for days in test_cases:
        await test_granularity(days)
        await asyncio.sleep(1)  # Rate limiting courtesy

    print("\n" + "="*70)
    print("Test Summary")
    print("="*70)
    print("\nKey Findings:")
    print("- days=1-2: Should give 30-minute candles")
    print("- days=3-30: Should give 4-hour candles (6 per day)")
    print("- days=31+: Should give 4-DAY candles (sparse data)")
    print("\n✅ RECOMMENDATION: Use days=30 for maximum 4-hour granularity")
    print("   → 180 candles total (30 days × 6 candles/day)")
    print("   → Aggregates to 30 daily data points with DATE_TRUNC")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
