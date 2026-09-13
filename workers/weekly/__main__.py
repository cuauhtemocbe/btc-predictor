"""
Weekly cron job orchestration.

This job runs every Monday and orchestrates:
1. Evaluator: Evaluate prediction from 7 days ago (weekly prediction)
2. Trainer: Train/retrain the dedicated 7-day-horizon model
3. Predictor: Generate prediction for 7 days ahead

Each stage must succeed before the next one runs -- see workers/daily/__main__.py
for the same rationale (issue #64): a failed evaluator or trainer run makes
the next stage unsafe to run against stale or missing data.

Entry point: python -m workers.weekly
Railway cron: 0 7 * * 1 (Mondays at 7am UTC)
"""

import logging
import sys
from collections.abc import Callable

from workers.weekly import evaluator, predictor, trainer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# A stage's own main() already catches its internal errors and returns 1;
# this is only a safety net for an exception that somehow escapes that.
UNEXPECTED_EXCEPTION_EXIT_CODE = 1


def _run_stage(name: str, stage_main: Callable[[], int]) -> int:
    """Run one orchestration stage, treating an uncaught exception as failure too."""
    try:
        return stage_main()
    except Exception as e:
        logger.error(f"{name} raised an unexpected exception: {e}", exc_info=True)
        return UNEXPECTED_EXCEPTION_EXIT_CODE


def main() -> int:
    """
    Main entry point for the weekly job.

    Runs evaluator → trainer → predictor in sequence, stopping at the
    first stage that fails (returns non-zero or raises).

    Returns:
        Exit code (0 = success, non-zero = the failing stage's exit code)
    """
    logger.info("=" * 60)
    logger.info("Starting weekly job orchestration")
    logger.info("=" * 60)

    # Step 1: Evaluate prediction from 7 days ago
    logger.info("Step 1: Running weekly evaluator")
    evaluator_exit = _run_stage("Evaluator", evaluator.main)

    if evaluator_exit != 0:
        logger.error(f"Evaluator failed with exit code {evaluator_exit}")
        logger.error("Stopping before trainer: evaluation must succeed first")
        return evaluator_exit

    # Step 2: Train/retrain the 7-day-horizon model
    logger.info("Step 2: Running weekly trainer")
    trainer_exit = _run_stage("Trainer", trainer.main)

    if trainer_exit != 0:
        logger.error(f"Trainer failed with exit code {trainer_exit}")
        logger.error("Stopping before predictor: a fresh model is required first")
        return trainer_exit

    # Step 3: Generate prediction for 7 days ahead
    logger.info("Step 3: Running weekly predictor")
    predictor_exit = _run_stage("Predictor", predictor.main)

    if predictor_exit != 0:
        logger.error(f"Predictor failed with exit code {predictor_exit}")
        return predictor_exit

    logger.info("=" * 60)
    logger.info("Weekly job completed successfully")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
