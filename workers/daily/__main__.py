"""
Daily cron job orchestration.

This job runs daily and orchestrates the following workflow:
1. Evaluator: Evaluate yesterday's prediction (update with actual price and metrics)
2. Trainer: Train/retrain ML model on historical data
3. Predictor: Generate tomorrow's prediction using active model

Each stage must succeed before the next one runs. A failed evaluator run
means no fresh actual-price data to retrain against, and a failed trainer
run means the predictor would run against a stale or nonexistent model --
neither failure is safe to build on, so the pipeline stops at the first
one and reports it as the job's own exit code (issue #64).

Entry point: python -m workers.daily
Version: 1.0.1 (migrations fix 2026-05-22)
"""

import logging
import sys
from collections.abc import Callable

from workers.daily import evaluator, predictor, trainer

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
    Main entry point for the daily job.

    Runs evaluator → trainer → predictor in sequence, stopping at the
    first stage that fails (returns non-zero or raises).

    Returns:
        Exit code (0 = success, non-zero = the failing stage's exit code)
    """
    logger.info("=" * 60)
    logger.info("Starting daily job orchestration")
    logger.info("=" * 60)

    # Step 1: Evaluate yesterday's prediction
    logger.info("Step 1: Running evaluator")
    evaluator_exit = _run_stage("Evaluator", evaluator.main)

    if evaluator_exit != 0:
        logger.error(f"Evaluator failed with exit code {evaluator_exit}")
        logger.error("Stopping before trainer: evaluation must succeed first")
        return evaluator_exit

    # Step 2: Train/retrain model
    logger.info("Step 2: Running trainer")
    trainer_exit = _run_stage("Trainer", trainer.main)

    if trainer_exit != 0:
        logger.error(f"Trainer failed with exit code {trainer_exit}")
        logger.error("Stopping before predictor: a fresh model is required first")
        return trainer_exit

    # Step 3: Generate tomorrow's prediction
    logger.info("Step 3: Running predictor")
    predictor_exit = _run_stage("Predictor", predictor.main)

    if predictor_exit != 0:
        logger.error(f"Predictor failed with exit code {predictor_exit}")
        return predictor_exit

    logger.info("=" * 60)
    logger.info("Daily job completed successfully")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
