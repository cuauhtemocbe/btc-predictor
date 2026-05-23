"""Quick test to verify days=30 granularity is 4 hours."""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "workers"))

from fetch_price.coingecko_client import CoinGeckoClient


async def main():
    """Test days=30 granularity."""
    print("\n" + "="*70)
    print("Verifying days=30 granularity")
    print("="*70 + "\n")

    client = CoinGeckoClient()
    data = await client.fetch_ohlcv("bitcoin", "usd", days=30)

    print(f"✓ Fetched {len(data)} candles for days=30\n")

    # Extract timestamps from tuples
    # Format: (timestamp, open, high, low, close)
    timestamps = [candle[0] for candle in data]
    timestamps.sort()

    if len(timestamps) < 2:
        print("❌ Not enough data")
        return

    # Calculate interval between first two candles
    first_interval_seconds = (timestamps[1] - timestamps[0]).total_seconds()
    first_interval_hours = first_interval_seconds / 3600

    # Calculate average interval
    total_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
    avg_interval_seconds = total_seconds / (len(timestamps) - 1)
    avg_interval_hours = avg_interval_seconds / 3600

    print(f"First candle interval: {first_interval_hours:.2f} hours")
    print(f"Average candle interval: {avg_interval_hours:.2f} hours")
    print(f"\nDate range: {timestamps[0].date()} to {timestamps[-1].date()}")
    print(f"Total days: {total_seconds / 86400:.1f}")
    print(f"\nExpected: 4.0 hours (6 candles/day)")

    if abs(avg_interval_hours - 4.0) < 0.5:
        print("\n✅ CONFIRMED: days=30 gives 4-hour granularity")
        print(f"   {len(data)} candles ÷ 30 days = {len(data)/30:.1f} candles/day")
    else:
        print(f"\n❌ Unexpected granularity: {avg_interval_hours:.2f} hours")

    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
