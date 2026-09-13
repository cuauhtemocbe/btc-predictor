"""
Weekly predictor job - predicts BTC price 7 days ahead.

This job:
1. Loads the active ML model from the database
2. Fetches recent historical DAILY close prices (not hourly)
3. Generates a prediction for 7 days ahead
4. Stores the prediction with timeframe='1w' for later evaluation

Entry point: python -m weekly.predictor
Runs: Every Monday at 7am UTC (Railway cron: 0 7 * * 1)
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice, Model, Prediction
from workers.weekly.models import BaseModel, LinearRegressionModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_active_model(session: Session) -> tuple[Model, BaseModel]:
    """
    Load the active weekly (timeframe='1w') model from the database.

    Scoped to timeframe='1w' so this never picks up the active daily
    model -- a '1d' and a '1w' model can be active at the same time (see
    ix_models_one_active_version_per_name_timeframe).

    Args:
        session: Database session

    Returns:
        Tuple of (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active weekly model found
        RuntimeError: If deserialization fails
    """
    stmt = select(Model).where(
        Model.is_active == True,  # noqa: E712
        Model.timeframe == "1w",
    )
    model_record = session.execute(stmt).scalars().first()

    if model_record is None:
        raise ValueError("No active weekly model found in database")

    # Deserialize based on model name
    try:
        if model_record.name.startswith("linear"):
            model_instance = LinearRegressionModel.deserialize(model_record.artifact)
        else:
            raise ValueError(f"Unknown model type: {model_record.name}")
    except Exception as e:
        raise RuntimeError(f"Failed to deserialize model: {e}") from e

    logger.info(
        f"Loaded active model: {model_record.name} v{model_record.version} "
        f"(trained {model_record.trained_at})"
    )

    return model_record, model_instance


def get_daily_close_prices(session: Session, window_days: int) -> list[Decimal]:
    """
    Fetch the last N DAILY close prices from the database.

    For weekly predictions, we use daily close prices (1 per day) rather than
    hourly prices (24 per day). This provides a 30-day window for training.

    Implementation: Group by DATE(timestamp) and select the closing price
    (highest timestamp for each day).

    Args:
        session: Database session
        window_days: Number of recent days to fetch (typically 30)

    Returns:
        List of daily close prices (oldest to newest)

    Raises:
        ValueError: If insufficient historical data available
    """
    # Subquery: Get the latest timestamp for each day
    latest_per_day = (
        select(
            func.date_trunc("day", BtcPrice.timestamp).label("day"),
            func.max(BtcPrice.timestamp).label("latest_timestamp"),
        )
        .group_by("day")
        .order_by(func.date_trunc("day", BtcPrice.timestamp).desc())
        .limit(window_days)
        .subquery()
    )

    # Main query: Join to get the close price for the latest timestamp each day
    stmt = (
        select(BtcPrice.close)
        .join(
            latest_per_day,
            BtcPrice.timestamp == latest_per_day.c.latest_timestamp,
        )
        .order_by(latest_per_day.c.day.desc())
    )

    results = session.execute(stmt).scalars().all()

    if len(results) < window_days:
        raise ValueError(
            f"Insufficient data: need {window_days} days, have {len(results)}"
        )

    # Reverse to get oldest to newest (chronological order)
    prices = list(reversed(results))

    logger.info(f"Fetched {len(prices)} daily close prices for weekly prediction")

    return prices


def prepare_features(prices: list[Decimal]) -> npt.NDArray[np.float64]:
    """
    Convert list of close prices to feature vector for prediction.

    Args:
        prices: List of daily close prices (oldest to newest)

    Returns:
        Numpy array of shape (1, len(prices)) for single prediction
    """
    # Convert Decimal to float
    prices_float = [float(p) for p in prices]
    # Reshape to (1, N) for single sample prediction
    return np.array([prices_float])


def check_existing_prediction(
    session: Session, predicted_for: date, timeframe: str
) -> bool:
    """
    Check if a prediction already exists for the given date and timeframe.

    Args:
        session: Database session
        predicted_for: Date to check
        timeframe: Timeframe to check ('1d', '1w')

    Returns:
        True if prediction exists, False otherwise
    """
    stmt = select(Prediction).where(
        Prediction.predicted_for == predicted_for,
        Prediction.timeframe == timeframe,
    )
    existing = session.execute(stmt).scalar_one_or_none()

    return existing is not None


def save_prediction(
    session: Session,
    model_id: int,
    predicted_for: date,
    current_price: Decimal,
    predicted_price: float,
    timeframe: str,
) -> Prediction:
    """
    Save a new prediction to the database.

    Args:
        session: Database session
        model_id: ID of the model used for prediction
        predicted_for: Date being predicted (7 days ahead)
        current_price: BTC price at prediction time
        predicted_price: Predicted BTC price
        timeframe: Prediction timeframe ('1w')

    Returns:
        Created Prediction record
    """
    prediction = Prediction(
        model_id=model_id,
        predicted_for=predicted_for,
        timeframe=timeframe,
        predicted_at=datetime.now(UTC),
        price_at_prediction=current_price,
        predicted_price=Decimal(str(predicted_price)),
        # Evaluation fields remain NULL until evaluator runs
        actual_price=None,
        evaluated_at=None,
        error_abs=None,
        error_pct=None,
        direction_correct=None,
        pnl_simulated=None,
    )

    session.add(prediction)
    session.commit()
    session.refresh(prediction)

    logger.info(
        f"Saved weekly prediction #{prediction.id}: "
        f"for={predicted_for}, predicted=${predicted_price:.2f}, "
        f"current=${current_price}, timeframe={timeframe}"
    )

    return prediction


def main() -> int:
    """
    Main entry point for the weekly predictor job.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting weekly predictor job")

    session = SessionLocal()

    try:
        # Calculate date 7 days ahead (next Monday in ISO week)
        today = date.today()
        days_ahead = 7
        predicted_date = today + timedelta(days=days_ahead)
        logger.info(f"Predicting for date: {predicted_date} (7 days ahead)")

        # Check if prediction already exists (idempotency)
        if check_existing_prediction(session, predicted_date, timeframe="1w"):
            logger.warning(
                f"Weekly prediction for {predicted_date} already exists, "
                f"skipping (idempotent)"
            )
            return 0

        # Load active model
        model_record, model_instance = get_active_model(session)

        # Get window_days from model params (typically 30 for weekly)
        window_days = model_record.params.get("window_days", 30)
        logger.info(f"Model requires {window_days} days of historical data")

        # Fetch daily close prices (not hourly)
        prices = get_daily_close_prices(session, window_days)

        # Prepare features
        X = prepare_features(prices)

        # Make prediction
        predicted_price = model_instance.predict(X)
        logger.info(f"Model predicted price (7 days ahead): ${predicted_price:.2f}")

        # Get current price (latest from btc_prices)
        current_price_stmt = (
            select(BtcPrice.close).order_by(BtcPrice.timestamp.desc()).limit(1)
        )
        current_price = session.execute(current_price_stmt).scalar_one()
        logger.info(f"Current BTC price: ${current_price}")

        # Save prediction with timeframe='1w'
        save_prediction(
            session=session,
            model_id=model_record.id,
            predicted_for=predicted_date,
            current_price=current_price,
            predicted_price=predicted_price,
            timeframe="1w",
        )

        logger.info("Weekly predictor job completed successfully")
        return 0

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return 1
    except RuntimeError as e:
        logger.error(f"Runtime error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
