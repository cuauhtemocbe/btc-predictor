"""
Daily cron job orchestration.

This job runs daily and orchestrates the following workflow:
1. Evaluator: Evaluate yesterday's prediction (update with actual price and metrics)
2. Predictor: Generate tomorrow's prediction

Entry point: python -m workers.daily
"""

import logging
import sys

from workers.daily import evaluator, predictor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """
    Main entry point for the daily job.

    Runs evaluator followed by predictor.

    Returns:
        Exit code (0 = success, non-zero = failure)
    """
    logger.info("=" * 60)
    logger.info("Starting daily job orchestration")
    logger.info("=" * 60)

    # Step 1: Evaluate yesterday's prediction
    logger.info("Step 1: Running evaluator")
    evaluator_exit = evaluator.main()

    if evaluator_exit != 0:
        logger.error(f"Evaluator failed with exit code {evaluator_exit}")
        logger.info("Continuing to predictor despite evaluator failure")

    # Step 2: Generate tomorrow's prediction
    logger.info("Step 2: Running predictor")
    predictor_exit = predictor.main()

    if predictor_exit != 0:
        logger.error(f"Predictor failed with exit code {predictor_exit}")
        return predictor_exit

    logger.info("=" * 60)
    logger.info("Daily job completed successfully")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
