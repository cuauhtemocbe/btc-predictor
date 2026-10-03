"""
Weekly trainer job - trains a model dedicated to the 7-day-ahead horizon.

Before this job existed, workers/weekly/predictor.py reused whatever model
was active for daily (1-day-ahead) predictions and relabeled its 1-step
output as a "7 days ahead" prediction -- the model was never actually
trained to predict that far out. This job trains a model whose target is
genuinely 7 calendar days after the end of its feature window, using the
same sliding-window mechanism as the daily trainer with horizon_days=7.

This job:
1. Reads the window size from settings.training_window_days (same as the
   daily trainer)
2. Fetches every stored daily BTCUSDT close price
3. Builds return features with a 7-day log return target (the sum of the next
   7 daily log returns)
4. Trains a LinearRegressionModel (matching the daily trainer's simplest,
   currently-production single-model path in workers/daily/trainer.py:main())
5. Saves the model with timeframe="1w" and horizon_days=7 in its params,
   then activates it via shared.db.crud.activate_model() -- which, since
   issue #66, scopes deactivation to (symbol, family, timeframe) and therefore never
   touches the active "1d" model.

Entry point: python -m workers.weekly.trainer
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.crud import activate_model
from shared.db.database import SessionLocal
from shared.db.models import Model
from shared.features import LOG_RETURN_TARGET, build_training_set, feature_count
from workers.daily.trainer import fetch_training_data
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
        params={
            "window_days": window_days,
            "horizon_days": HORIZON_DAYS,
            "target": LOG_RETURN_TARGET,
        },
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
        window_days = settings.training_window_days
        logger.info(f"Training window: {window_days}d, horizon: {HORIZON_DAYS}d")

        version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M%S")

        series = fetch_training_data(session, window_days, horizon_days=HORIZON_DAYS)

        training_set = build_training_set(
            series.closes, series.volumes, window_days, horizon_days=HORIZON_DAYS
        )
        logger.info(f"Created {len(training_set.y)} training samples")

        logger.info(f"Training {MODEL_NAME} (horizon_days={HORIZON_DAYS})...")
        model = LinearRegressionModel(
            window_days=window_days, n_features=feature_count(window_days)
        )
        model.train(training_set.X, training_set.y)

        train_to = date.today()
        train_from = train_to - timedelta(days=len(series))

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
