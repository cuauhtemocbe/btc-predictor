"""
Daily trainer job - trains ML model on historical BTC price data.

This job:
1. Fetches recent historical prices (60 days minimum)
2. Creates sliding window features for time series prediction
3. Trains a LinearRegressionModel
4. Saves the trained model to the database
5. Sets it as the active model (deactivates previous models)

Entry point: python -m workers.daily.trainer
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice, Model
from workers.daily.models import LinearRegressionModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_training_data(
    session: Session, window_days: int = 30, min_days: int = 60
) -> list[Decimal]:
    """
    Fetch historical BTC prices for training.

    Args:
        session: Database session
        window_days: Size of sliding window for features
        min_days: Minimum number of days needed (window_days * 2)

    Returns:
        List of close prices (oldest to newest)

    Raises:
        ValueError: If insufficient data available
    """
    stmt = (
        select(BtcPrice.close)
        .order_by(BtcPrice.timestamp.desc())
        .limit(min_days)
    )
    results = session.execute(stmt).scalars().all()

    if len(results) < min_days:
        raise ValueError(
            f"Insufficient training data: need {min_days} days, have {len(results)}"
        )

    # Reverse to get oldest to newest (chronological order)
    prices = list(reversed(results))

    logger.info(f"Fetched {len(prices)} days of historical prices for training")

    return prices


def create_sliding_windows(
    prices: list[Decimal], window_days: int = 30
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """
    Create sliding window features and labels from price history.

    For 60 days of prices with a 30-day window:
    - Sample 1: days 1-30 → predict day 31
    - Sample 2: days 2-31 → predict day 32
    - ...
    - Sample 30: days 30-59 → predict day 60

    Args:
        prices: List of close prices (oldest to newest)
        window_days: Size of sliding window

    Returns:
        Tuple (X, y) where:
        - X: Feature matrix of shape (n_samples, window_days)
        - y: Target vector of shape (n_samples,)
    """
    prices_float = [float(p) for p in prices]
    n_samples = len(prices_float) - window_days

    X = np.zeros((n_samples, window_days))
    y = np.zeros(n_samples)

    for i in range(n_samples):
        X[i] = prices_float[i : i + window_days]
        y[i] = prices_float[i + window_days]

    logger.info(
        f"Created {n_samples} training samples "
        f"(feature shape: {X.shape}, target shape: {y.shape})"
    )

    return X, y


def deactivate_existing_models(session: Session, model_name: str) -> int:
    """
    Deactivate all existing models with the given name.

    Args:
        session: Database session
        model_name: Name of models to deactivate

    Returns:
        Number of models deactivated
    """
    stmt = (
        update(Model)
        .where(Model.name == model_name)
        .where(Model.is_active == True)  # noqa: E712
        .values(is_active=False)
    )
    result = session.execute(stmt)
    count = result.rowcount
    session.commit()

    if count > 0:
        logger.info(f"Deactivated {count} existing model(s) named '{model_name}'")

    return count


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
    # Deactivate existing models with same name
    deactivate_existing_models(session, model_name)

    # Serialize model
    model_artifact = model_instance.serialize()

    # Create model record
    model_record = Model(
        name=model_name,
        version=version,
        params={"window_days": window_days},
        artifact=model_artifact,
        trained_at=datetime.now(UTC),
        train_from=train_from,
        train_to=train_to,
        is_active=True,
    )

    session.add(model_record)
    session.commit()
    session.refresh(model_record)

    logger.info(
        f"Saved model {model_name} v{version} as active "
        f"(ID: {model_record.id}, trained on {train_from} to {train_to})"
    )

    return model_record


def main() -> int:
    """
    Main entry point for the trainer job.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting daily trainer job")

    session = SessionLocal()

    try:
        # Configuration
        window_days = 30
        min_days = 60  # Need at least 2x window for meaningful training
        model_name = "linear_v1"
        version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M%S")  # Timestamp version

        logger.info(f"Training configuration: window={window_days}d, min={min_days}d")

        # Fetch training data
        prices = fetch_training_data(session, window_days, min_days)

        # Create sliding windows
        X, y = create_sliding_windows(prices, window_days)

        # Train model
        logger.info("Training LinearRegressionModel...")
        model = LinearRegressionModel(window_days=window_days)
        model.train(X, y)

        # Calculate training date range
        # Assuming hourly data, approximate day range
        train_to = date.today()
        train_from = train_to - timedelta(days=len(prices))

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
