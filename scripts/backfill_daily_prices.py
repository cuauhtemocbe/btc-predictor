#!/usr/bin/env python3
"""
Backfill Historical BTC Price Data from CoinGecko

Downloads historical OHLCV data from CoinGecko with the following granularity:
- 1-30 days: 4-hour candles (~6 candles/day) ✅ RECOMMENDED
- 31-90 days: Daily candles (~1 candle/day)
- 91+ days: 4-day candles (too sparse for ML training) ❌

IMPORTANT: For ML model training, use maximum 30 days per backfill to maintain
4-hour granularity. If you need more historical data, run incremental backfills.

Example (incremental backfill):
    # Get last 30 days with 4-hour granularity
    railway run -s api python scripts/backfill_daily_prices.py --days=30

    # For more data, consider using daily worker's DATE_TRUNC aggregation
    # which works with any granularity (4h, daily, 4-day)

Features:
- Idempotent (skips duplicates via UNIQUE timestamp constraint)
- Progress logging with batch counts
- Railway-safe (timeout aware)
- Retry with exponential backoff

Usage:
    # Local (testing)
    docker compose exec api python scripts/backfill_daily_prices.py --days=7

    # Production (Railway) - RECOMMENDED
    railway run -s api python scripts/backfill_daily_prices.py --days=30
"""

import argparse
import asyncio
import logging
import sys
from datetime import timezone
from decimal import Decimal
from typing import List

from sqlalchemy.orm import Session

# Add workers directory to path for imports
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'workers'))

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice
from fetch_price.coingecko_client import CoinGeckoClient
from fetch_price.exceptions import (
    InvalidSymbolError,
    PriceAPIError,
    RateLimitError,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Backfill historical BTC daily price data from CoinGecko",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download last 7 days (testing - 4-hour granularity)
  python scripts/backfill_daily_prices.py --days=7

  # Download last 30 days (RECOMMENDED - 4-hour granularity, ~180 candles)
  python scripts/backfill_daily_prices.py --days=30

  # Download 90 days (daily granularity - less precise)
  python scripts/backfill_daily_prices.py --days=90

Notes:
  - CoinGecko Granularity:
    * 1-30 days: 4-hour candles (~6/day) ✅ Best for ML
    * 31-90 days: Daily candles (~1/day)
    * 91+ days: 4-day candles (too sparse) ❌
  - Idempotent: safe to run multiple times (skips duplicates)
  - Progress logged every 100 records
        """,
    )

    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of historical data to download (default: 30, max recommended: 30 for 4h granularity)",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for database inserts (default: 100)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


async def fetch_historical_data(days: int) -> List[dict]:
    """
    Fetch historical daily OHLCV data from CoinGecko.

    Args:
        days: Number of days of historical data (1-365)

    Returns:
        List of price dictionaries with keys: timestamp, open, high, low, close, volume, source

    Raises:
        ValueError: If days is out of range
        TimeoutError: CoinGecko API timeout
        RateLimitError: CoinGecko rate limit exceeded
        InvalidSymbolError: Invalid coin identifier
        PriceAPIError: Other CoinGecko API errors
    """
    if days < 1 or days > 365:
        raise ValueError(f"Days must be between 1 and 365, got {days}")

    logger.info(f"Fetching {days} days of historical data from CoinGecko...")

    client = CoinGeckoClient()

    # Fetch OHLCV candles
    # CoinGecko granularity: 1-30 days=4h, 31-90 days=daily, 91+ days=4-day
    candles = await client.fetch_ohlcv(coin_id="bitcoin", vs_currency="usd", days=days)

    # Convert to dictionaries
    prices = []
    for timestamp, open_price, high, low, close, volume in candles:
        prices.append(
            {
                "timestamp": timestamp,
                "open": Decimal(str(open_price)),
                "high": Decimal(str(high)),
                "low": Decimal(str(low)),
                "close": Decimal(str(close)),
                "volume": Decimal(str(volume)),
                "source": "coingecko",
            }
        )

    logger.info(f"✓ Fetched {len(prices)} candles from CoinGecko")

    # Verify granularity
    if len(prices) >= 2:
        first_ts = prices[0]["timestamp"]
        second_ts = prices[1]["timestamp"]
        diff_hours = abs((second_ts - first_ts).total_seconds() / 3600)
        logger.info(f"Granularity: ~{diff_hours:.1f}h between candles ({len(prices)} candles for {days} days)")
        # CoinGecko returns 4h granularity for 1-30 days, daily for 90+ days
        # We accept any granularity - will aggregate later as needed

    return prices


def filter_existing_timestamps(prices: List[dict], session: Session) -> List[dict]:
    """
    Filter out prices with timestamps that already exist in the database.

    Args:
        prices: List of price dictionaries
        session: Database session

    Returns:
        List of price dictionaries with only new timestamps
    """
    if not prices:
        return []

    # Extract all timestamps from fetched prices
    timestamps = [p["timestamp"] for p in prices]

    # Query database for existing timestamps
    existing = session.query(BtcPrice.timestamp).filter(BtcPrice.timestamp.in_(timestamps)).all()

    # Convert to set for O(1) lookup
    existing_set = {
        t[0].replace(tzinfo=timezone.utc) if t[0].tzinfo is None else t[0] for t in existing
    }

    # Filter out existing timestamps
    new_prices = [p for p in prices if p["timestamp"] not in existing_set]

    skipped_count = len(prices) - len(new_prices)
    if skipped_count > 0:
        logger.info(f"Skipped {skipped_count} existing timestamps (already in database)")

    return new_prices


def save_prices_batch(prices: List[dict], session: Session, batch_size: int) -> int:
    """
    Save prices to database in batches.

    Args:
        prices: List of price dictionaries
        session: Database session
        batch_size: Number of records per batch

    Returns:
        Number of records inserted
    """
    if not prices:
        return 0

    total_inserted = 0
    total_batches = (len(prices) + batch_size - 1) // batch_size

    for i in range(0, len(prices), batch_size):
        batch = prices[i:i + batch_size]
        batch_num = (i // batch_size) + 1

        # Create BtcPrice objects
        btc_prices = [BtcPrice(**price) for price in batch]

        # Bulk insert
        session.add_all(btc_prices)
        session.commit()

        total_inserted += len(batch)
        logger.info(
            f"Batch {batch_num}/{total_batches}: Inserted {len(batch)} records "
            f"({total_inserted}/{len(prices)} total)"
        )

    return total_inserted


async def main() -> int:
    """
    Main entry point for backfill script.

    Returns:
        Exit code: 0 for success, 1 for error
    """
    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Add warning for days > 30
    if args.days > 30:
        logger.warning(
            f"Requesting {args.days} days of data. "
            f"CoinGecko returns degraded granularity (daily/4-day) beyond 30 days. "
            f"Recommended: Use --days=30 for best 4-hour granularity."
        )

    try:
        logger.info("=" * 70)
        logger.info("BTC Price Historical Data Backfill")
        logger.info("=" * 70)
        logger.info(f"Days to fetch: {args.days}")
        logger.info(f"Batch size: {args.batch_size}")
        logger.info("")

        # Fetch historical data from CoinGecko
        prices = await fetch_historical_data(args.days)

        if not prices:
            logger.warning("No data returned from CoinGecko")
            return 1

        # Show date range
        oldest = min(p["timestamp"] for p in prices)
        newest = max(p["timestamp"] for p in prices)
        days_span = (newest - oldest).days + 1
        logger.info(f"Date range: {oldest.date()} to {newest.date()} ({days_span} days)")
        logger.info("")

        # Filter and save to database
        with SessionLocal() as session:
            logger.info("Filtering existing timestamps...")
            new_prices = filter_existing_timestamps(prices, session)

            if new_prices:
                logger.info(f"Saving {len(new_prices)} new records to database...")
                inserted = save_prices_batch(new_prices, session, args.batch_size)
            else:
                logger.info("All data already exists in database (skipping insert)")
                inserted = 0

        # Summary
        logger.info("")
        logger.info("=" * 70)
        logger.info("BACKFILL SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total fetched:     {len(prices)} records")
        logger.info(f"Total inserted:    {inserted} records")
        logger.info(f"Total skipped:     {len(prices) - inserted} records (already existed)")
        logger.info(f"Date range:        {oldest.date()} to {newest.date()}")
        logger.info(f"Days of data:      {days_span} days")
        logger.info("=" * 70)

        if inserted > 0:
            logger.info("✓ Backfill completed successfully with new data!")
        else:
            logger.info("✓ All requested data already exists in database")

        return 0

    except ValueError as e:
        logger.error(f"Invalid argument: {e}")
        return 1

    except (TimeoutError, RateLimitError, InvalidSymbolError, PriceAPIError) as e:
        logger.error(f"CoinGecko API error: {e}")
        return 1

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
