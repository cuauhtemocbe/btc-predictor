#!/usr/bin/env python3
"""
Walk-forward backtest for BTC Predictor.

For every day of the range it trains the chosen model on the daily rows before that
day, predicts the day's close with the production feature and model code, and stores
the result in ``backtest_results`` (see ``scripts/backtest_engine.py``). Each run
gets its own UUID.

Usage:
    python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30
    python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30 \
        --model=xgboost --training-window=30
"""

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scripts.backtest_engine import DEFAULT_SEED, BacktestConfig, run_walk_forward
from scripts.backtest_report import build_report, format_report
from shared.db.database import SessionLocal
from shared.db.models import BacktestResult
from workers.daily.models.factory import MODEL_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest for BTC Predictor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backtest May 2024 with the production window
  python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-31

  # Backtest another model with a 30-day window
  python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-31 \\
      --model=xgboost --training-window=30
        """,
    )
    parser.add_argument(
        "--start-date", required=True, help="First day predicted (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date", required=True, help="Last day predicted (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--model",
        default="linear",
        choices=MODEL_NAMES,
        help="Model to backtest (default: linear)",
    )
    parser.add_argument(
        "--training-window",
        type=int,
        default=BacktestConfig.default_window(),
        help="Window in days (default: settings.training_window_days, the "
        "production value)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducible runs (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--retrain-every",
        type=int,
        default=1,
        help="Retrain the model every N days and reuse it in between "
        "(default: 1, every day). Reported with the results.",
    )
    parser.add_argument(
        "--test-start-date",
        help="First day of the test slice, the out-of-sample headline (YYYY-MM-DD, "
        "within the range). Earlier days are the validation slice. Default: the "
        "start of the last 30%% of the range.",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> BacktestConfig:
    """
    Validate parsed arguments and turn them into a BacktestConfig.

    Raises:
        ValueError: If a date is malformed, the range is empty or the window < 1
    """
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid start-date format: {args.start_date}") from e
    try:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid end-date format: {args.end_date}") from e

    if start_date > end_date:
        raise ValueError(
            f"start-date must be before end-date ({start_date} > {end_date})"
        )
    if args.training_window < 1:
        raise ValueError(f"training-window must be >= 1 (got {args.training_window})")

    test_start_date = None
    if args.test_start_date is not None:
        try:
            test_start_date = datetime.strptime(args.test_start_date, "%Y-%m-%d").date()
        except ValueError as e:
            raise ValueError(
                f"Invalid test-start-date format: {args.test_start_date}"
            ) from e
    if args.retrain_every < 1:
        raise ValueError(f"retrain-every must be >= 1 (got {args.retrain_every})")

    return BacktestConfig(
        model_name=args.model,
        window_days=args.training_window,
        start_date=start_date,
        end_date=end_date,
        seed=args.seed,
        retrain_every=args.retrain_every,
        test_start_date=test_start_date,
    )


def log_pnl_summary(db: Session, run_id: UUID) -> None:
    """Log the total PnL of each strategy for a run."""
    sums = db.execute(
        select(
            func.count(BacktestResult.id),
            func.sum(BacktestResult.pnl_simple),
            func.sum(BacktestResult.pnl_long_short),
            func.sum(BacktestResult.pnl_threshold),
            func.sum(BacktestResult.pnl_realistic),
        ).where(BacktestResult.backtest_run_id == run_id)
    ).one()
    _, simple, long_short, threshold, realistic = sums
    logger.info("PnL Summary:")
    logger.info(f"  Simple strategy: ${simple or 0:.2f}")
    logger.info(f"  Long/Short strategy: ${long_short or 0:.2f}")
    logger.info(f"  Threshold strategy: ${threshold or 0:.2f}")
    logger.info(f"  Realistic strategy: ${realistic or 0:.2f}")


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
) -> int:
    """
    Entry point.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    started = time.time()
    try:
        config = build_config(parse_arguments(argv))
        run_id = uuid4()
        logger.info("=" * 60)
        logger.info("BTC Predictor Walk-Forward Backtesting")
        logger.info(f"Model: {config.model_name}  Window: {config.window_days} days")
        logger.info(
            f"Seed: {config.seed}  Retrain every: {config.retrain_every} day(s)"
        )
        logger.info(f"Range: {config.start_date} to {config.end_date}")
        logger.info(f"Backtest run ID: {run_id}")
        logger.info("=" * 60)

        with session_factory() as db:
            stats = run_walk_forward(db, config, run_id)
            logger.info(f"Predictions created: {stats.predictions}")
            logger.info(f"Skipped (no actual price): {stats.skipped_no_actual}")
            logger.info(f"Skipped (training failed): {stats.skipped_training_failed}")
            log_pnl_summary(db, run_id)
            print(format_report(build_report(db, run_id)))

        logger.info(f"Elapsed time: {time.time() - started:.1f} seconds")
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
