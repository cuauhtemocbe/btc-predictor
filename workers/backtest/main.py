"""
Backtest Worker - Railway Cron Job

Runs the walk-forward backtest (``scripts/backtest.py``) with the production
configuration, so the stored results describe what the live system does:

- window: ``settings.training_window_days``, the value the daily worker trains with
- range: derived from the engine's history requirement, never earlier than the
  earliest start date with enough history
- split: the last ``TEST_DAYS`` days are the out-of-sample test slice
- seed and retrain frequency: explicit constants, logged and shown in the report

With too little history it exits 1 and logs the engine's message instead of
shrinking the window.
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Add the repo root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# `scripts.backtest`, not `backtest`: with /app/workers on PYTHONPATH a bare
# `backtest` can resolve to this package instead of the script.
from scripts.backtest import main as run_backtest_main
from scripts.backtest_engine import (
    DEFAULT_SEED,
    BacktestConfig,
    DailyHistory,
    InsufficientHistoryError,
    check_enough_history,
    load_daily_history,
)
from shared.config import settings
from shared.db.database import SessionLocal
from workers.daily.trainer import required_training_days

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

SEED = DEFAULT_SEED
RETRAIN_EVERY = 1  # Linear trains in milliseconds, so retrain every day like prod
TEST_DAYS = 100  # a test slice shorter than this is not a meaningful headline
LOOKBACK_DAYS = 365  # range length when the history is longer than that


def plan_range(history: DailyHistory, window_days: int) -> tuple[date, date, date]:
    """
    Choose the backtest range from the loaded history.

    The range ends on the newest loaded day and covers up to ``LOOKBACK_DAYS`` days.
    It starts no earlier than the earliest start date the engine allows for the
    window, and the last ``TEST_DAYS`` days are the test slice.

    Returns:
        ``(start_date, end_date, test_start_date)``

    Raises:
        InsufficientHistoryError: If the history is shorter than
            ``required_training_days(window_days)`` or leaves less than
            ``TEST_DAYS`` test days plus one validation day.
    """
    needed = required_training_days(window_days)
    end_date = history.dates[-1] if history.dates else date.today()
    wanted_start = end_date - timedelta(days=LOOKBACK_DAYS - 1)

    if len(history.dates) > needed:
        start_date = max(wanted_start, history.dates[needed])
    else:
        start_date = wanted_start
    config = BacktestConfig(
        model_name="linear",
        window_days=window_days,
        start_date=start_date,
        end_date=end_date,
    )
    check_enough_history(history, config)

    test_start_date = end_date - timedelta(days=TEST_DAYS - 1)
    if start_date >= test_start_date:
        raise InsufficientHistoryError(
            f"The earliest allowed start date is {start_date}, which leaves "
            f"{(end_date - start_date).days + 1} days up to {end_date}; the test "
            f"slice alone needs {TEST_DAYS} days plus at least one validation day"
        )
    return start_date, end_date, test_start_date


def build_arguments(
    start_date: date, end_date: date, test_start_date: date, window_days: int
) -> list[str]:
    """Command-line arguments of ``scripts/backtest.py`` for the cron run."""
    return [
        "backtest.py",
        f"--start-date={start_date.isoformat()}",
        f"--end-date={end_date.isoformat()}",
        f"--test-start-date={test_start_date.isoformat()}",
        f"--training-window={window_days}",
        f"--seed={SEED}",
        f"--retrain-every={RETRAIN_EVERY}",
    ]


def main():
    """
    Execute the production-parity backtest.

    This is designed to run as a Railway cron job.
    """
    logger.info("Starting scheduled backtest worker (production configuration)")
    window_days = settings.training_window_days

    with SessionLocal() as db:
        history = load_daily_history(db)
    if history.dates:
        logger.info(
            f"Available data: {history.dates[0]} to {history.dates[-1]} "
            f"({len(history.dates)} days)"
        )

    try:
        start_date, end_date, test_start_date = plan_range(history, window_days)
    except InsufficientHistoryError as e:
        logger.error(f"Cannot plan the backtest range: {e}")
        sys.exit(1)

    logger.info(f"Backtesting range: {start_date} to {end_date}")
    logger.info(f"Test slice: {test_start_date} to {end_date} ({TEST_DAYS} days)")
    logger.info(
        f"Training window: {window_days} days  Seed: {SEED}  "
        f"Retrain every: {RETRAIN_EVERY} day(s)"
    )

    # Override sys.argv to pass arguments to backtest script
    sys.argv = build_arguments(start_date, end_date, test_start_date, window_days)

    exit_code = run_backtest_main()

    if exit_code == 0:
        logger.info("Backtest completed successfully")
    else:
        logger.error(f"Backtest failed with exit code {exit_code}")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
