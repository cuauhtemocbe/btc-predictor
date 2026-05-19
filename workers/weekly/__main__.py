"""
Weekly cron job orchestration.

This job runs every Monday and orchestrates:
1. Evaluator: Evaluate prediction from 7 days ago (weekly prediction)
2. Predictor: Generate prediction for 7 days ahead

Entry point: python -m workers.weekly
Railway cron: 0 7 * * 1 (Mondays at 7am UTC)
"""

import logging
import sys

from workers.weekly import evaluator, predictor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """
    Main entry point for the weekly job.

    Runs evaluator → predictor in sequence.

    Returns:
        Exit code (0 = success, non-zero = failure)
    """
    logger.info("=" * 60)
    logger.info("Starting weekly job orchestration")
    logger.info("=" * 60)

    # Step 1: Evaluate prediction from 7 days ago
    logger.info("Step 1: Running weekly evaluator")
    evaluator_exit = evaluator.main()

    if evaluator_exit != 0:
        logger.error(f"Evaluator failed with exit code {evaluator_exit}")
        logger.info("Continuing to predictor despite evaluator failure")

    # Step 2: Generate prediction for 7 days ahead
    logger.info("Step 2: Running weekly predictor")
    predictor_exit = predictor.main()

    if predictor_exit != 0:
        logger.error(f"Predictor failed with exit code {predictor_exit}")
        return predictor_exit

    logger.info("=" * 60)
    logger.info("Weekly job completed successfully")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
