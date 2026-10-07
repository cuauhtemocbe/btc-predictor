"""
Daily trainer job - trains ML model on historical BTC price data.

This job:
1. Reads the sliding-window size from settings.training_window_days
2. Fetches every stored daily BTCUSDT close price
3. Builds return-based features (shared.features) and the next-day log return target
4. Trains the model on log returns, not on price levels
5. Saves the trained model to the database
6. Sets it as the active model (deactivates previous models)

Training needs at least (window + 1) * 5 daily rows; with fewer rows the job fails
and reports the required and available counts.

Entry point: python -m workers.daily.trainer
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.crud import activate_model as crud_activate_model
from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, Model, Price
from shared.features import (
    LOG_RETURN_TARGET,
    DailySeries,
    build_training_set,
    feature_count,
    require_fresh_series,
)
from shared.utils import utc_today
from workers.daily.models import LinearRegressionModel
from workers.daily.models.factory import build_model

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def required_training_days(window_days: int) -> int:
    """
    Minimum number of daily rows needed to train.

    The rule is ``(window + 1) * 5`` rows. It dates from the 70/20/10 train/validation
    split (the 20% validation share needed window + 1 rows) and stays as the floor.
    """
    return (window_days + 1) * 5


def fetch_training_data(
    session: Session,
    window_days: int,
    symbol: str = DEFAULT_SYMBOL,
) -> DailySeries:
    """
    Fetch every stored DAILY close price and volume of one symbol for training.

    Uses date aggregation to get exactly one row per day (not per hour/4h).
    Takes the latest row (its close and volume) for each day.

    Args:
        session: Database session
        window_days: Size of sliding window for features
        symbol: Asset whose prices are read (default BTCUSDT)

    Returns:
        Daily closes and volumes (oldest to newest)

    Raises:
        ValueError: If fewer rows are stored than required_training_days()
    """
    # Subquery: Get the latest timestamp for each day
    latest_per_day = (
        select(
            func.date_trunc("day", Price.timestamp).label("day"),
            func.max(Price.timestamp).label("latest_timestamp"),
        )
        .where(Price.symbol == symbol)
        .group_by("day")
        .subquery()
    )

    # Main query: Join to get the close price for the latest timestamp each day
    stmt = (
        select(latest_per_day.c.day, Price.close, Price.volume)
        .join(
            latest_per_day,
            Price.timestamp == latest_per_day.c.latest_timestamp,
        )
        .where(Price.symbol == symbol)
        .order_by(latest_per_day.c.day)
    )

    rows = session.execute(stmt).all()

    required = required_training_days(window_days)
    if len(rows) < required:
        raise ValueError(
            f"Insufficient training data for {symbol}: need {required} daily rows "
            f"(window={window_days}d), have {len(rows)}"
        )

    logger.info(
        f"Fetched {len(rows)} DAYS of {symbol} prices for training "
        f"(aggregated from multiple records/day)"
    )

    return DailySeries(
        dates=[row.day.date() for row in rows],
        closes=[row.close for row in rows],
        volumes=[row.volume for row in rows],
    )


def save_model(
    session: Session,
    model_instance: LinearRegressionModel,
    model_name: str,
    version: str,
    train_from: date,
    train_to: date,
    window_days: int,
) -> Model:
    """
    Save trained model to the database.

    Args:
        session: Database session
        model_instance: Trained model instance
        model_name: Model name (e.g., "linear_v1")
        version: Model version (e.g., "1.0.0")
        train_from: Start date of training data
        train_to: End date of training data
        window_days: Size of sliding window used

    Returns:
        Created Model record
    """
    # Serialize model
    model_artifact = model_instance.serialize()

    # Create model record inactive first, then activate it atomically via
    # crud.activate_model() -- the single mechanism that deactivates any
    # other active "1d" model and activates this one in one transaction,
    # guarded by ix_models_one_active_per_timeframe.
    model_record = Model(
        name=model_name,
        version=version,
        params={
            "window_days": window_days,
            "horizon_days": 1,
            "target": LOG_RETURN_TARGET,
        },
        artifact=model_artifact,
        trained_at=datetime.now(UTC),
        train_from=train_from,
        train_to=train_to,
        timeframe="1d",
        is_active=False,
    )

    session.add(model_record)
    session.commit()
    session.refresh(model_record)

    crud_activate_model(session, model_record.id)

    logger.info(
        f"Saved model {model_name} v{version} as active "
        f"(ID: {model_record.id}, trained on {train_from} to {train_to})"
    )

    return model_record


def main() -> int:
    """
    Main entry point for the trainer job.

    Dynamically adapts training strategy based on available historical data.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting daily trainer job")

    session = SessionLocal()

    try:
        window_days = settings.training_window_days
        logger.info(f"Training window: {window_days}d")

        # Configuration
        model_name = "linear_v1"
        version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M%S")  # Timestamp version

        # Fetch training data
        series = fetch_training_data(session, window_days)
        require_fresh_series(series.dates, utc_today())

        # Return features and next-day log return target
        training_set = build_training_set(
            series.closes, series.volumes, window_days, horizon_days=1
        )
        logger.info(f"Created {len(training_set.y)} training samples")

        # Train model
        logger.info("Training LinearRegressionModel on log returns...")
        model = build_model("linear", window_days, feature_count(window_days))
        model.train(training_set.X, training_set.y)

        # Calculate training date range
        # One row per day, so the series length is the day range
        train_to = utc_today()
        train_from = train_to - timedelta(days=len(series))

        # Save model
        save_model(
            session=session,
            model_instance=model,
            model_name=model_name,
            version=version,
            train_from=train_from,
            train_to=train_to,
            window_days=window_days,
        )

        logger.info("Trainer job completed successfully")
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
