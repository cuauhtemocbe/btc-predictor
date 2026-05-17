"""
Daily predictor job - predicts tomorrow's BTC price.

This job:
1. Loads the active ML model from the database
2. Fetches recent historical prices
3. Generates a prediction for tomorrow
4. Stores the prediction in the database for later evaluation

Entry point: python -m daily.predictor
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from shared.db.database import SessionLocal
from shared.db.models import BtcPrice, Model, Prediction
from sqlalchemy import select
from sqlalchemy.orm import Session

from workers.daily.models import BaseModel, LinearRegressionModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_active_model(session: Session) -> tuple[Model, BaseModel]:
    """
    Load the active model from the database.

    Args:
        session: Database session

    Returns:
        Tuple of (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active model found
        RuntimeError: If deserialization fails
    """
    stmt = select(Model).where(Model.is_active == True)  # noqa: E712
    model_record = session.execute(stmt).scalar_one_or_none()

    if model_record is None:
        raise ValueError("No active model found in database")

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


def get_recent_prices(session: Session, window_days: int) -> list[Decimal]:
    """
    Fetch the last N close prices from the database.

    Args:
        session: Database session
        window_days: Number of recent prices to fetch

    Returns:
        List of close prices (oldest to newest)

    Raises:
        ValueError: If insufficient historical data available
    """
    stmt = (
        select(BtcPrice.close)
        .order_by(BtcPrice.timestamp.desc())
        .limit(window_days)
    )
    results = session.execute(stmt).scalars().all()

    if len(results) < window_days:
        raise ValueError(
            f"Insufficient data: need {window_days}, have {len(results)}"
        )

    # Reverse to get oldest to newest (chronological order)
    prices = list(reversed(results))

    logger.info(f"Fetched {len(prices)} recent prices for feature preparation")

    return prices


def prepare_features(prices: list[Decimal]) -> npt.NDArray[np.float64]:
    """
    Convert list of close prices to feature vector for prediction.

    Args:
        prices: List of close prices (oldest to newest)

    Returns:
        Numpy array of shape (1, len(prices)) for single prediction
    """
    # Convert Decimal to float
    prices_float = [float(p) for p in prices]
    # Reshape to (1, N) for single sample prediction
    return np.array([prices_float])


def check_existing_prediction(session: Session, predicted_for: date) -> bool:
    """
    Check if a prediction already exists for the given date.

    Args:
        session: Database session
        predicted_for: Date to check

    Returns:
        True if prediction exists, False otherwise
    """
    stmt = select(Prediction).where(Prediction.predicted_for == predicted_for)
    existing = session.execute(stmt).scalar_one_or_none()

    return existing is not None


def save_prediction(
    session: Session,
    model_id: int,
    predicted_for: date,
    current_price: Decimal,
    predicted_price: float,
) -> Prediction:
    """
    Save a new prediction to the database.

    Args:
        session: Database session
        model_id: ID of the model used for prediction
        predicted_for: Date being predicted (tomorrow)
        current_price: BTC price at prediction time
        predicted_price: Predicted BTC price

    Returns:
        Created Prediction record
    """
    prediction = Prediction(
        model_id=model_id,
        predicted_for=predicted_for,
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
        f"Saved prediction #{prediction.id}: "
        f"for={predicted_for}, predicted=${predicted_price:.2f}, "
        f"current=${current_price}"
    )

    return prediction


def main() -> int:
    """
    Main entry point for the predictor job.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting daily predictor job")

    session = SessionLocal()

    try:
        # Calculate tomorrow's date
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
        logger.info(f"Predicting for date: {tomorrow}")

        # Check if prediction already exists (idempotency)
        if check_existing_prediction(session, tomorrow):
            logger.warning(
                f"Prediction for {tomorrow} already exists, skipping (idempotent)"
            )
            return 0

        # Load active model
        model_record, model_instance = get_active_model(session)

        # Get window_days from model params
        window_days = model_record.params.get("window_days", 30)
        logger.info(f"Model requires {window_days} days of historical data")

        # Fetch recent prices
        prices = get_recent_prices(session, window_days)

        # Prepare features
        X = prepare_features(prices)

        # Make prediction
        predicted_price = model_instance.predict(X)
        logger.info(f"Model predicted price: ${predicted_price:.2f}")

        # Get current price (latest from btc_prices)
        current_price_stmt = (
            select(BtcPrice.close).order_by(BtcPrice.timestamp.desc()).limit(1)
        )
        current_price = session.execute(current_price_stmt).scalar_one()
        logger.info(f"Current BTC price: ${current_price}")

        # Save prediction
        save_prediction(
            session=session,
            model_id=model_record.id,
            predicted_for=tomorrow,
            current_price=current_price,
            predicted_price=predicted_price,
        )

        logger.info("Predictor job completed successfully")
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
