"""
Backtest Worker - Railway Cron Job

Executes walk-forward backtesting on a schedule.
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from backtest import main as run_backtest_main

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    """
    Execute backtest for last 30 days.

    This is designed to run as a Railway cron job.
    """
    logger.info("Starting scheduled backtest worker")

    # Calculate date range (last 30 days with data)
    end_date = date.today() - timedelta(days=1)  # Yesterday
    start_date = end_date - timedelta(days=29)  # 30 days total

    logger.info(f"Backtesting range: {start_date} to {end_date}")

    # Override sys.argv to pass arguments to backtest script
    sys.argv = [
        "backtest.py",
        f"--start-date={start_date.isoformat()}",
        f"--end-date={end_date.isoformat()}",
        "--training-window=30",
    ]

    # Run backtest
    exit_code = run_backtest_main()

    if exit_code == 0:
        logger.info("Backtest completed successfully")
    else:
        logger.error(f"Backtest failed with exit code {exit_code}")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
