"""
Fetch Price Job - Main Entry Point

Fetches BTC/USD prices from CoinGecko and saves to database.
Granularity: ~4 hours per candle (CoinGecko behavior for 1-day window).
Data is aggregated to daily frequency by daily worker using DATE_TRUNC.
"""

import asyncio
import logging
import sys
from datetime import timezone
from decimal import Decimal
from typing import Dict, List

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice
from sqlalchemy.orm import Session

from fetch_price.coingecko_client import CoinGeckoClient
from fetch_price.exceptions import (
    InvalidSymbolError,
    PriceAPIError,
    RateLimitError,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def fetch_prices(days: int = 1) -> List[Dict]:
    """
    Fetch BTC/USD prices from CoinGecko.

    Args:
        days: Number of days of data to fetch (default: 1 = last ~24 hours)

    Returns:
        List of price dictionaries with keys: timestamp, open, high, low, close, volume
        Note: volume will be 0 (CoinGecko OHLC doesn't include volume)

    Raises:
        TimeoutError: CoinGecko API timeout
        RateLimitError: CoinGecko rate limit exceeded
        InvalidSymbolError: Invalid coin identifier
        PriceAPIError: Other CoinGecko API errors
    """
    client = CoinGeckoClient()

    # Fetch candles from CoinGecko
    # Returns List[Tuple[datetime, float, float, float, float, float]]
    candles = await client.fetch_ohlcv(coin_id="bitcoin", vs_currency="usd", days=days)

    # Convert tuples to dictionaries for easier handling
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

    logger.info(f"Fetched {len(prices)} candles from CoinGecko")
    return prices


def filter_existing_timestamps(prices: List[Dict], session: Session) -> List[Dict]:
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
    # Note: SQLite returns datetime without timezone, so we need to replace with UTC for comparison
    existing_set = {
        t[0].replace(tzinfo=timezone.utc) if t[0].tzinfo is None else t[0] for t in existing
    }

    # Filter out existing timestamps
    new_prices = [p for p in prices if p["timestamp"] not in existing_set]

    skipped_count = len(prices) - len(new_prices)
    if skipped_count > 0:
        logger.info(f"Skipped {skipped_count} existing timestamps")

    return new_prices


def save_prices(prices: List[Dict], session: Session) -> int:
    """
    Save prices to the database.

    Args:
        prices: List of price dictionaries
        session: Database session

    Returns:
        Number of records inserted
    """
    if not prices:
        return 0

    # Create BtcPrice objects
    btc_prices = [BtcPrice(**price) for price in prices]

    # Bulk insert
    session.add_all(btc_prices)
    session.commit()

    logger.info(f"Inserted {len(btc_prices)} new records")
    return len(btc_prices)


async def main() -> int:
    """
    Main entry point for fetch_price job.

    Returns:
        Exit code: 0 for success, 1 for error
    """
    try:
        logger.info("Fetch price job starting")

        # Fetch prices from CoinGecko
        prices = await fetch_prices(days=1)

        # Filter and save
        with SessionLocal() as session:
            new_prices = filter_existing_timestamps(prices, session)

            if new_prices:
                inserted = save_prices(new_prices, session)
                logger.info(f"Job completed: {inserted} new records added")
            else:
                logger.info(
                    f"Job completed: No new prices to insert (all {len(prices)} already exist)"
                )

        return 0

    except (TimeoutError, RateLimitError, InvalidSymbolError, PriceAPIError) as e:
        logger.error(f"CoinGecko API error: {e}")
        return 1

    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
