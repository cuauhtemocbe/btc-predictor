"""
Weekly trainer job - trains a model dedicated to the 7-day-ahead horizon.

Before this job existed, workers/weekly/predictor.py reused whatever model
was active for daily (1-day-ahead) predictions and relabeled its 1-step
output as a "7 days ahead" prediction -- the model was never actually
trained to predict that far out. This job trains a model whose target is
genuinely 7 calendar days after the end of its feature window, using the
same sliding-window mechanism as the daily trainer with horizon_days=7.

This job:
1. Detects available historical data and calculates a window size (reusing
   the daily trainer's dynamic-window strategy)
2. Fetches daily-aggregated historical prices
3. Creates sliding window features with a 7-day-ahead target
4. Trains a LinearRegressionModel (matching the daily trainer's simplest,
   currently-production single-model path in workers/daily/trainer.py:main())
5. Saves the model with timeframe="1w" and horizon_days=7 in its params,
   then activates it via shared.db.crud.activate_model() -- which, since
   issue #66, scopes deactivation to (name, timeframe) and therefore never
   touches the active "1d" model.

Entry point: python -m workers.weekly.trainer
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from shared.db.crud import activate_model
from shared.db.database import SessionLocal
from shared.db.models import Model
from workers.daily.trainer import (
    calculate_dynamic_window,
    count_available_days,
    create_sliding_windows,
    fetch_training_data,
)
from workers.weekly.models import LinearRegressionModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

HORIZON_DAYS = 7
MODEL_NAME = "linear_weekly_v1"
TIMEFRAME = "1w"


def save_weekly_model(
    session: Session,
    model_instance: LinearRegressionModel,
    version: str,
    train_from: date,
    train_to: date,
    window_days: int,
) -> Model:
    """
    Save a trained weekly model and activate it atomically.

    Args:
        session: Database session
        model_instance: Trained model instance
        version: Model version (timestamp-based, e.g. "2026.08.10.223000")
        train_from: Start date of training data
        train_to: End date of training data
        window_days: Size of sliding window used

    Returns:
        The activated Model record
    """
    model_artifact = model_instance.serialize()

    model_record = Model(
        name=MODEL_NAME,
        version=version,
        params={"window_days": window_days, "horizon_days": HORIZON_DAYS},
        artifact=model_artifact,
        trained_at=datetime.now(UTC),
        train_from=train_from,
        train_to=train_to,
        timeframe=TIMEFRAME,
        is_active=False,
    )

    session.add(model_record)
    session.commit()
    session.refresh(model_record)

    activate_model(session, model_record.id)

    logger.info(
        f"Saved and activated {MODEL_NAME} v{version} "
        f"(ID: {model_record.id}, trained on {train_from} to {train_to}, "
        f"horizon_days={HORIZON_DAYS})"
    )

    return model_record


def main() -> int:
    """
    Main entry point for the weekly trainer job.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting weekly trainer job")

    session = SessionLocal()

    try:
        days_available = count_available_days(session)
        logger.info(f"Available historical data: {days_available} days")

        window_days, min_days = calculate_dynamic_window(days_available)

        # The last training sample needs horizon_days days of "future" data
        # past its window to have a target -- calculate_dynamic_window()
        # doesn't know about the horizon, so pad its floor here.
        required_days = min_days + HORIZON_DAYS - 1
        logger.info(
            f"Dynamic configuration: window={window_days}d, "
            f"required={required_days}d (min={min_days}d + "
            f"horizon={HORIZON_DAYS}d - 1)"
        )

        version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M%S")

        prices = fetch_training_data(session, window_days, required_days)

        X, y = create_sliding_windows(prices, window_days, horizon_days=HORIZON_DAYS)

        logger.info(f"Training {MODEL_NAME} (horizon_days={HORIZON_DAYS})...")
        model = LinearRegressionModel(window_days=window_days)
        model.train(X, y)

        train_to = date.today()
        train_from = train_to - timedelta(days=len(prices))

        save_weekly_model(
            session=session,
            model_instance=model,
            version=version,
            train_from=train_from,
            train_to=train_to,
            window_days=window_days,
        )

        logger.info("Weekly trainer job completed successfully")
        return 0

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
