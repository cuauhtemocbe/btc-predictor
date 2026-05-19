#!/usr/bin/env python3
"""Backfill historical Bitcoin prices from CoinGecko API.

This script fetches historical BTC prices from CoinGecko's market_chart endpoint
and inserts them into the btc_prices table. It's designed to be idempotent and
safe to re-run (UNIQUE constraint on timestamp prevents duplicates).

Usage:
    python scripts/backfill_prices.py --days=90
    python scripts/backfill_prices.py --days=365 --verbose

Inside Docker:
    docker compose exec api python scripts/backfill_prices.py --days=90
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from sqlalchemy.exc import IntegrityError

# Import from workers (shared Docker environment)
sys.path.insert(0, '/app/workers')
from fetch_price.coingecko_client import CoinGeckoClient

# Import from shared package
from shared.config import settings
from shared.db.database import SessionLocal
from shared.db.models import BtcPrice

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments with 'days' and 'verbose' fields.
    """
    parser = argparse.ArgumentParser(
        description="Backfill historical BTC prices from CoinGecko",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch last 90 days (default)
  python scripts/backfill_prices.py

  # Fetch last 7 days
  python scripts/backfill_prices.py --days=7

  # Fetch last year with verbose logging
  python scripts/backfill_prices.py --days=365 --verbose
        """
    )

    parser.add_argument(
        '--days',
        type=int,
        default=90,
        help='Number of days of historical data to fetch (default: 90)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose (DEBUG) logging'
    )

    return parser.parse_args()


def transform_price_to_ohlcv(timestamp: datetime, price: float) -> BtcPrice:
    """Transform a simple (timestamp, price) into OHLCV format.

    Since CoinGecko's market_chart endpoint only returns price (not full OHLCV),
    we map: open = close = high = low = price, and volume = 0.

    Args:
        timestamp: UTC datetime of the price
        price: BTC price in USD

    Returns:
        BtcPrice model instance ready for insertion
    """
    return BtcPrice(
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=0.0,  # CoinGecko market_chart doesn't provide volume
        source="coingecko"
    )


async def insert_prices_batch(
    session,
    prices: list[BtcPrice],
    batch_size: int = 100
) -> tuple[int, int]:
    """Insert prices in batches and handle duplicates.

    Args:
        session: SQLAlchemy session
        prices: List of BtcPrice instances to insert
        batch_size: Number of records per batch (default: 100)

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    inserted = 0
    skipped = 0
    total = len(prices)

    for i in range(0, total, batch_size):
        batch = prices[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(
            f"Processing batch {batch_num}/{total_batches} "
            f"({i}/{total} records, {i*100//total}%)"
        )

        for price in batch:
            try:
                session.add(price)
                session.flush()
                inserted += 1
            except IntegrityError:
                # UNIQUE constraint on timestamp - skip duplicate
                session.rollback()
                skipped += 1
                logger.debug(f"Skipped duplicate: {price.timestamp}")

        # Commit after each batch
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to commit batch {batch_num}: {e}")
            raise

    return inserted, skipped


async def backfill_prices(days: int) -> None:
    """Main backfill logic.

    Args:
        days: Number of days of historical data to fetch

    Raises:
        ValueError: If days is invalid
        Exception: If API or database errors occur
    """
    logger.info(f"Starting backfill for {days} days of BTC prices")

    # Validate days parameter
    if days <= 0:
        raise ValueError(f"days must be positive, got {days}")

    # Initialize CoinGecko client
    client = CoinGeckoClient(timeout=30.0)

    try:
        # Fetch historical prices from CoinGecko
        logger.info(f"Fetching {days} days of data from CoinGecko API...")
        raw_prices = await client.fetch_historical_prices(
            coin_id="bitcoin",
            vs_currency="usd",
            days=days,
            max_retries=5
        )

        if not raw_prices:
            logger.warning("CoinGecko returned empty prices array")
            logger.info("Backfill completed: 0 prices inserted, 0 duplicates skipped")
            return

        logger.info(f"Fetched {len(raw_prices)} price points from CoinGecko")

        # Transform to OHLCV format
        logger.info("Transforming prices to OHLCV format...")
        prices = [
            transform_price_to_ohlcv(timestamp, price)
            for timestamp, price in raw_prices
        ]

        # Insert into database
        logger.info(f"Inserting {len(prices)} prices into database...")

        session = SessionLocal()
        try:
            inserted, skipped = await insert_prices_batch(
                session,
                prices,
                batch_size=100
            )
        finally:
            session.close()

        # Report results
        logger.info(
            f"Backfill completed: {inserted} new prices inserted, "
            f"{skipped} duplicates skipped"
        )

    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        raise

    finally:
        # Close httpx client
        await client._client.aclose()


def main() -> None:
    """Entry point for the backfill script."""
    # Parse arguments
    args = parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    logger.info("BTC Predictor - Backfill Historical Prices")
    logger.info(f"Database: {settings.database_url.split('@')[-1]}")  # Hide credentials
    logger.info(f"Days to fetch: {args.days}")

    try:
        # Run backfill
        asyncio.run(backfill_prices(args.days))
        sys.exit(0)

    except KeyboardInterrupt:
        logger.warning("Backfill interrupted by user (Ctrl+C)")
        sys.exit(130)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
