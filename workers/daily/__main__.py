"""Daily cron job: evaluator, trainer, predictor, in that order.

Each stage must succeed before the next runs: a failed evaluator leaves nothing
fresh to train on, and a failed trainer leaves the predictor a stale or missing
model. The pipeline stops at the first failure and returns that stage's exit
code (#64).

Entry point: ``python -m workers.daily``
"""

import logging
import sys
from collections.abc import Callable

from workers.daily import evaluator, predictor, trainer

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
    """Run evaluator, trainer and predictor, stopping at the first stage that fails.

    Returns:
        0 on success, otherwise the exit code of the failing stage.
    """
    logger.info("=" * 60)
    logger.info("Starting daily job orchestration")
    logger.info("=" * 60)

    logger.info("Step 1: Running evaluator")
    evaluator_exit = _run_stage("Evaluator", evaluator.main)

    if evaluator_exit != 0:
        logger.error(f"Evaluator failed with exit code {evaluator_exit}")
        logger.error("Stopping before trainer: evaluation must succeed first")
        return evaluator_exit

    logger.info("Step 2: Running trainer")
    trainer_exit = _run_stage("Trainer", trainer.main)

    if trainer_exit != 0:
        logger.error(f"Trainer failed with exit code {trainer_exit}")
        logger.error("Stopping before predictor: a fresh model is required first")
        return trainer_exit

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
