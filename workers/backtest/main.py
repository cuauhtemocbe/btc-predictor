"""
Backtest Worker - Railway Cron Job

Executes walk-forward backtesting on a schedule with adaptive window sizing.

The worker automatically detects available data and adjusts:
- Backtest date range
- Training window size

This ensures backtesting works even with limited historical data.
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Add scripts and shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice
from sqlalchemy import func

from backtest import main as run_backtest_main

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def calculate_adaptive_window(db) -> tuple[date, date, int] | None:
    """
    Calculate optimal backtest window based on available data.

    Strategy:
    - Query oldest and newest data in btc_prices table
    - Calculate total days available
    - Set training window and backtest range adaptively:
      * >= 60 days: 30 days training, 30 days backtest
      * 40-59 days: Use half for training, half for backtest
      * 20-39 days: Use 10 days training, rest for backtest
      * < 20 days: Skip (insufficient data)

    Args:
        db: Database session

    Returns:
        Tuple of (start_date, end_date, training_window) or None if insufficient data
    """
    # Query oldest and newest prices
    result = db.query(
        func.date(func.min(BtcPrice.timestamp)).label("oldest"),
        func.date(func.max(BtcPrice.timestamp)).label("newest"),
        func.count(func.distinct(func.date(BtcPrice.timestamp))).label("total_days"),
    ).first()

    if not result or not result.oldest or not result.newest:
        logger.error("No price data found in database")
        return None

    oldest_date = result.oldest
    newest_date = result.newest
    total_days = result.total_days

    logger.info(f"Available data: {oldest_date} to {newest_date} ({total_days} days)")

    # Adaptive window calculation
    if total_days >= 60:
        # Ideal case: 30 days training + 30 days backtest
        training_window = 30
        backtest_days = 30
        logger.info("Using optimal window: 30 days training, 30 days backtest")
    elif total_days >= 40:
        # Use half/half
        training_window = total_days // 2
        backtest_days = total_days - training_window
        logger.info(
            f"Using adaptive window: {training_window} days training, "
            f"{backtest_days} days backtest"
        )
    elif total_days >= 20:
        # Minimum viable: 10 days training, rest backtest
        training_window = 10
        backtest_days = total_days - training_window - 1  # -1 for safety margin
        logger.info(
            f"Using minimal window: {training_window} days training, "
            f"{backtest_days} days backtest"
        )
    else:
        logger.error(
            f"Insufficient data: only {total_days} days available (minimum 20 required)"
        )
        return None

    # Calculate backtest range (most recent data)
    end_date = newest_date - timedelta(days=1)  # Yesterday (allow time for data)
    start_date = end_date - timedelta(days=backtest_days - 1)

    # Validate we have enough data before start_date for training
    required_start = start_date - timedelta(days=training_window)
    if required_start < oldest_date:
        logger.warning(
            f"Insufficient data for training window. "
            f"Required: {required_start}, Available: {oldest_date}"
        )
        # Adjust backtest range to fit available data
        start_date = oldest_date + timedelta(days=training_window)
        logger.info(f"Adjusted backtest start date to {start_date}")

    return start_date, end_date, training_window


def main():
    """
    Execute adaptive backtest based on available data.

    This is designed to run as a Railway cron job.
    """
    logger.info("Starting scheduled backtest worker (adaptive mode)")

    # Connect to database
    db = SessionLocal()
    try:
        # Calculate optimal window based on available data
        window_config = calculate_adaptive_window(db)

        if window_config is None:
            logger.error("Cannot calculate backtest window - insufficient data")
            sys.exit(1)

        start_date, end_date, training_window = window_config

        logger.info(f"Backtesting range: {start_date} to {end_date}")
        logger.info(f"Training window: {training_window} days")

        # Override sys.argv to pass arguments to backtest script
        sys.argv = [
            "backtest.py",
            f"--start-date={start_date.isoformat()}",
            f"--end-date={end_date.isoformat()}",
            f"--training-window={training_window}",
        ]

        # Run backtest
        exit_code = run_backtest_main()

        if exit_code == 0:
            logger.info("Backtest completed successfully")
        else:
            logger.error(f"Backtest failed with exit code {exit_code}")
            sys.exit(exit_code)

    finally:
        db.close()


if __name__ == "__main__":
    main()
