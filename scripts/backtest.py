#!/usr/bin/env python3
"""
Walk-Forward Backtesting Script for BTC Predictor.

Simulates historical predictions by:
1. For each day in date range:
   - Train model on rolling window of past data
   - Predict next day's price
   - Calculate all 4 PnL strategies
   - Save result to backtest_results table

Each backtest run gets a unique UUID to distinguish different simulations.

Usage:
    python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30
    python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30 \
        --training-window=60
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

from scripts.backtest_utils import (
    fetch_training_data,
    generate_prediction,
    get_actual_price_for_date,
    save_backtest_result,
)
from shared.db.database import SessionLocal
from sqlalchemy.orm import Session
from shared.utils import (
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest for BTC Predictor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backtest May 2024
  python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-31

  # Backtest with 60-day training window
  python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-31 \
      --training-window=60

  # Backtest last 30 days
  python scripts/backtest.py --start-date=2024-04-01 --end-date=2024-04-30
        """,
    )

    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date for backtest (YYYY-MM-DD)",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date for backtest (YYYY-MM-DD)",
    )

    parser.add_argument(
        "--training-window",
        type=int,
        default=30,
        help="Training window in days (default: 30)",
    )

    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> tuple[date, date, int]:
    """
    Validate parsed arguments.

    Args:
        args: Parsed arguments namespace

    Returns:
        Tuple of (start_date, end_date, training_window)

    Raises:
        ValueError: If arguments are invalid
    """
    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid start-date format: {args.start_date}") from e

    try:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid end-date format: {args.end_date}") from e

    # Validate date range
    if start_date >= end_date:
        raise ValueError(
            f"start-date must be before end-date ({start_date} >= {end_date})"
        )

    # Validate training window
    if args.training_window < 1:
        raise ValueError(f"training-window must be >= 1 (got {args.training_window})")

    return start_date, end_date, args.training_window


def check_data_availability(
    start_date: date, training_window: int, db: SessionLocal
) -> None:
    """
    Check if sufficient data exists for backtesting.

    Args:
        start_date: Start date for backtest
        training_window: Training window in days
        db: Database session

    Raises:
        ValueError: If insufficient data
    """
    # Need data from (start_date - training_window) onwards
    required_start = start_date - timedelta(days=training_window)

    # Try to fetch training data for first day
    training_data = fetch_training_data(
        start_date - timedelta(days=1), training_window, db
    )

    if training_data is None or len(training_data) == 0:
        raise ValueError(
            f"Insufficient data: need at least {training_window} days "
            f"of data before {start_date} (from {required_start})"
        )


def run_backtest(
    start_date: date,
    end_date: date,
    training_window: int,
    backtest_run_id: UUID,
    db: Session | None = None,
) -> dict:
    """
    Run walk-forward backtest for date range.

    Args:
        start_date: Start date for backtest
        end_date: End date for backtest
        training_window: Training window in days
        backtest_run_id: Unique UUID for this backtest run
        db: Database session (optional, will create if None)

    Returns:
        Dictionary with run statistics
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    stats = {
        "total_days": 0,
        "predictions": 0,
        "skipped_no_actual": 0,
        "skipped_training_failed": 0,
        "skipped_no_training_data": 0,
    }

    try:
        # Iterate over each day in range
        current_date = start_date

        while current_date <= end_date:
            stats["total_days"] += 1

            # Progress logging every 10 days
            if stats["total_days"] % 10 == 0:
                progress_pct = (
                    (current_date - start_date).days
                    / (end_date - start_date).days
                    * 100
                )
                logger.info(
                    f"Backtesting day {stats['total_days']} "
                    f"({current_date}) - {progress_pct:.1f}% complete"
                )

            # Step 1: Fetch training data (rolling window up to day before current_date)
            training_end = current_date - timedelta(days=1)
            training_data = fetch_training_data(training_end, training_window, db)

            if training_data is None or len(training_data) == 0:
                logger.warning(
                    f"Skipping {current_date}: insufficient training data "
                    f"(need {training_window} days before {current_date})"
                )
                stats["skipped_no_training_data"] += 1
                current_date += timedelta(days=1)
                continue

            # Step 2: Get price at prediction time (last close of training_end)
            price_at_prediction = get_actual_price_for_date(training_end, db)

            if price_at_prediction is None:
                logger.warning(
                    f"Skipping {current_date}: no price data for {training_end}"
                )
                stats["skipped_no_actual"] += 1
                current_date += timedelta(days=1)
                continue

            # Step 3: Train model and generate prediction
            try:
                predicted_price, model_params = generate_prediction(
                    training_data,
                    current_date,
                    price_at_prediction,
                    db,
                    window_days=training_window,
                )
            except ValueError as e:
                logger.warning(f"Skipping {current_date}: training failed - {e}")
                stats["skipped_training_failed"] += 1
                current_date += timedelta(days=1)
                continue

            # Step 4: Fetch actual price for current_date
            actual_price = get_actual_price_for_date(current_date, db)

            if actual_price is None:
                logger.warning(f"Skipping {current_date}: no actual price data")
                stats["skipped_no_actual"] += 1
                current_date += timedelta(days=1)
                continue

            # Step 5: Calculate all 4 PnL strategies
            pnl_simple = calculate_pnl(
                predicted_price, price_at_prediction, actual_price
            )
            pnl_long_short = calculate_pnl_long_short(
                predicted_price, price_at_prediction, actual_price
            )
            pnl_threshold = calculate_pnl_threshold(
                predicted_price, price_at_prediction, actual_price
            )
            pnl_realistic = calculate_pnl_realistic(
                predicted_price, price_at_prediction, actual_price
            )

            # Step 6: Save to backtest_results
            predicted_at = datetime.combine(training_end, datetime.min.time())
            save_backtest_result(
                backtest_run_id=backtest_run_id,
                predicted_for=current_date,
                predicted_at=predicted_at,
                price_at_prediction=price_at_prediction,
                predicted_price=predicted_price,
                actual_price=actual_price,
                pnl_simple=pnl_simple,
                pnl_long_short=pnl_long_short,
                pnl_threshold=pnl_threshold,
                pnl_realistic=pnl_realistic,
                model_params=model_params,
                db=db,
            )

            stats["predictions"] += 1

            # Move to next day
            current_date += timedelta(days=1)

    finally:
        if close_db:
            db.close()

    return stats


def main() -> int:
    """
    Main entry point for backtest script.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    start_time = time.time()

    try:
        # Parse and validate arguments
        args = parse_arguments()
        start_date, end_date, training_window = validate_arguments(args)

        # Log configuration
        logger.info("=" * 60)
        logger.info("BTC Predictor Walk-Forward Backtesting")
        logger.info("=" * 60)
        logger.info(f"Start date: {start_date}")
        logger.info(f"End date: {end_date}")
        logger.info(f"Training window: {training_window} days")
        logger.info(f"Date range: {(end_date - start_date).days + 1} days")

        # Generate unique backtest run ID
        backtest_run_id = uuid4()
        logger.info(f"Backtest run ID: {backtest_run_id}")
        logger.info("=" * 60)

        # Check data availability
        db = SessionLocal()
        try:
            check_data_availability(start_date, training_window, db)
        finally:
            db.close()

        # Run backtest
        logger.info("Starting backtest...")
        stats = run_backtest(start_date, end_date, training_window, backtest_run_id)

        # Log summary
        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("Backtest completed successfully!")
        logger.info(f"Run ID: {backtest_run_id}")
        logger.info(f"Total days processed: {stats['total_days']}")
        logger.info(f"Predictions created: {stats['predictions']}")
        logger.info(f"Skipped (no actual price): {stats['skipped_no_actual']}")
        logger.info(f"Skipped (training failed): {stats['skipped_training_failed']}")
        logger.info(f"Skipped (no training data): {stats['skipped_no_training_data']}")
        logger.info(f"Elapsed time: {elapsed:.1f} seconds")
        logger.info("=" * 60)

        # Query summary from database
        db = SessionLocal()
        try:
            from sqlalchemy import func, select

            from shared.db.models import BacktestResult

            stmt = select(
                func.count(BacktestResult.id),
                func.sum(BacktestResult.pnl_simple),
                func.sum(BacktestResult.pnl_long_short),
                func.sum(BacktestResult.pnl_threshold),
                func.sum(BacktestResult.pnl_realistic),
            ).where(BacktestResult.backtest_run_id == backtest_run_id)

            result = db.execute(stmt).one()
            count, sum_simple, sum_long_short, sum_threshold, sum_realistic = result

            logger.info("PnL Summary:")
            logger.info(f"  Simple strategy: ${sum_simple or 0:.2f}")
            logger.info(f"  Long/Short strategy: ${sum_long_short or 0:.2f}")
            logger.info(f"  Threshold strategy: ${sum_threshold or 0:.2f}")
            logger.info(f"  Realistic strategy: ${sum_realistic or 0:.2f}")
            logger.info("=" * 60)

        finally:
            db.close()

        return 0

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.warning("Backtest interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
