"""Daily trainer job: trains the linear model on the stored BTCUSDT daily bars.

Builds the return features and the next-day log-return target (``shared.features``)
over every stored daily row, fits ``linear_v1`` with the window
``settings.training_window_days``, saves it and makes it the active model. Fails
when fewer than ``required_training_days`` rows are stored or the series is stale
or gapped (#174).

Entry point: ``python -m workers.daily.trainer``, also run by ``workers.daily``.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def required_training_days(window_days: int) -> int:
    """Minimum daily rows to train: ``(window + 1) * 5``.

    The floor dates from the 70/20/10 train/validation split and was kept.
    """
    return (window_days + 1) * 5


def fetch_training_data(
    session: Session,
    window_days: int,
    symbol: str = DEFAULT_SYMBOL,
) -> DailySeries:
    """Fetch every stored daily close and volume of ``symbol``, oldest to newest.

    Takes the latest stored row of each day.

    Raises:
        ValueError: If fewer than ``required_training_days`` rows are stored.
    """
    latest_per_day = (
        select(
            func.date_trunc("day", Price.timestamp).label("day"),
            func.max(Price.timestamp).label("latest_timestamp"),
        )
        .where(Price.symbol == symbol)
        .group_by("day")
        .subquery()
    )

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
    """Save the trained model as the active one and return its record.

    The record is inserted inactive and then activated through ``crud.activate_model``,
    which deactivates the other active version in one transaction, guarded by
    ``ix_models_one_active_version_per_name_timeframe``.

    Args:
        model_name: Name such as ``linear_v1``.
        version: Version string.
        train_from: First date of the training data.
        train_to: Last date of the training data.
        window_days: Window stored in ``params``.
    """
    model_artifact = model_instance.serialize()

    # crud.activate_model() -- the single mechanism that deactivates any
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
    """Run the trainer job.

    Returns:
        Exit code, 0 on success and 1 on failure.
    """
    logger.info("Starting daily trainer job")

    session = SessionLocal()

    try:
        window_days = settings.training_window_days
        logger.info(f"Training window: {window_days}d")

        model_name = "linear_v1"
        version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M%S")  # Timestamp version

        series = fetch_training_data(session, window_days)
        require_fresh_series(series.dates, utc_today())

        training_set = build_training_set(
            series.closes, series.volumes, window_days, horizon_days=1
        )
        logger.info(f"Created {len(training_set.y)} training samples")

        logger.info("Training LinearRegressionModel on log returns...")
        model = build_model("linear", window_days, feature_count(window_days))
        model.train(training_set.X, training_set.y)

        train_to = utc_today()
        train_from = train_to - timedelta(days=len(series))

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
