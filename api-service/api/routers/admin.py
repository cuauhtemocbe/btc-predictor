"""
Temporary admin endpoints for maintenance tasks.

IMPORTANT: This file should be removed after backfill is complete.
"""

import logging

# Import CoinGecko client
import sys
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter
from shared.db.database import SessionLocal
from shared.db.models import BtcPrice

# Add workers directory to path
workers_path = Path(__file__).parent.parent.parent.parent / "workers"
sys.path.insert(0, str(workers_path))

from fetch_price.coingecko_client import CoinGeckoClient  # noqa: E402

router = APIRouter(prefix="/admin", tags=["admin"])

logger = logging.getLogger(__name__)


@router.post("/backfill")
async def run_backfill(days: int = 30):
    """
    Execute backfill for historical BTC prices.

    Args:
        days: Number of days to fetch (default: 30 for 4-hour granularity)

    Returns:
        Summary of backfill operation
    """
    logger.info(f"Starting backfill with days={days}")

    # Initialize CoinGecko client
    client = CoinGeckoClient()

    try:
        # Fetch prices
        logger.info(f"Fetching {days} days of data from CoinGecko...")
        prices = await client.get_ohlc_data(days=days)
        logger.info(f"Fetched {len(prices)} candles")

        # Save to database
        db = SessionLocal()
        inserted = 0
        skipped = 0

        try:
            for price_data in prices:
                # Check if timestamp already exists
                existing = (
                    db.query(BtcPrice)
                    .filter(BtcPrice.timestamp == price_data["timestamp"])
                    .first()
                )

                if existing:
                    skipped += 1
                    continue

                # Insert new record
                price_record = BtcPrice(
                    timestamp=price_data["timestamp"],
                    open=Decimal(str(price_data["open"])),
                    high=Decimal(str(price_data["high"])),
                    low=Decimal(str(price_data["low"])),
                    close=Decimal(str(price_data["close"])),
                    volume=Decimal(str(price_data["volume"])),
                    source="coingecko_backfill",
                )

                db.add(price_record)
                inserted += 1

                # Commit in batches of 50
                if inserted % 50 == 0:
                    db.commit()
                    logger.info(f"Inserted {inserted} records...")

            # Final commit
            db.commit()
            logger.info(f"Backfill complete: {inserted} inserted, {skipped} skipped")

            return {
                "status": "success",
                "days": days,
                "total_fetched": len(prices),
                "inserted": inserted,
                "skipped": skipped,
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        return {"status": "error", "message": str(e)}
