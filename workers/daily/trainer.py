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

from shared.db.crud import activate_model as crud_activate_model
from shared.db.database import SessionLocal
from shared.db.models import BtcPrice, Model
from shared.utils import calculate_mape, split_train_validation
from workers.daily.models import (
    ARIMAModel,
    BaseModel,
    LinearRegressionModel,
    LSTMModel,
    XGBoostModel,
)

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


def train_single_model(
    model_class: type[BaseModel],
    model_name: str,
    X_train: npt.NDArray[np.float64],
    y_train: npt.NDArray[np.float64],
    X_val: npt.NDArray[np.float64],
    y_val: npt.NDArray[np.float64],
    window_days: int,
) -> tuple[BaseModel, float] | None:
    """
    Train a single model with validation data and calculate validation error.

    Args:
        model_class: Model class to instantiate (e.g., LSTMModel)
        model_name: Model name (e.g., "lstm")
        X_train: Training features
        y_train: Training targets
        X_val: Validation features
        y_val: Validation targets
        window_days: Window size for model

    Returns:
        Tuple of (trained_model, validation_error_pct) or None if training fails

    Example:
        >>> model, error = train_single_model(
        ...     LSTMModel, "lstm", X_train, y_train, X_val, y_val, 30
        ... )
        >>> print(f"LSTM validation error: {error:.2f}%")
    """
    import time

    logger.info(f"Training {model_name}Model...")
    start_time = time.time()

    try:
        # Instantiate model (ARIMA has different parameters)
        if model_name == "arima":
            model = model_class(order=(5, 1, 0))
        else:
            model = model_class(window_days=window_days)

        # Train model
        model.train(X_train, y_train)

        # Validate model - predict on validation set
        y_val_pred = np.array([model.predict(X_val[i : i + 1]) for i in range(len(X_val))])

        # Calculate MAPE validation error
        validation_error = calculate_mape(y_val, y_val_pred)

        # Calculate training duration
        duration = time.time() - start_time

        logger.info(
            f"✓ {model_name}Model completed in {duration:.1f}s, "
            f"validation error: {validation_error:.2f}%"
        )

        return model, validation_error

    except Exception as e:
        logger.error(f"✗ {model_name}Model training failed: {e}")
        return None


def train_all_models(
    session: Session,
    window_days: int = 30,
    min_days: int = 90,
) -> list[Model]:
    """
    Train all available ML models with the same training data.

    This function:
    1. Fetches historical price data
    2. Splits into train/validation sets (70/20/10)
    3. Trains all 4 models sequentially
    4. Calculates validation error (MAPE) for each
    5. Saves all models to database with is_active=False
    6. Activates the model with lowest validation error

    Args:
        session: Database session
        window_days: Size of sliding window for features
        min_days: Minimum days needed (default 90 for ARIMA)

    Returns:
        List of created Model records

    Raises:
        ValueError: If insufficient data available
    """
    logger.info("Starting multi-model training...")

    # Model registry - all available models
    MODEL_CLASSES = {
        "linear": LinearRegressionModel,
        "lstm": LSTMModel,
        "xgboost": XGBoostModel,
        "arima": ARIMAModel,
    }

    # Fetch training data
    logger.info(f"Fetching last {min_days} days of historical prices...")
    prices = fetch_training_data(session, window_days, min_days)

    # Convert to numpy array
    prices_array = np.array([float(p) for p in prices])

    # Split into train/validation (70/20/10)
    logger.info("Splitting data: 70% train, 20% validation, 10% buffer")
    train_prices, val_prices = split_train_validation(
        prices_array, train_pct=0.7, val_pct=0.2
    )

    logger.info(
        f"Train set: {len(train_prices)} days, Validation set: {len(val_prices)} days"
    )

    # Create sliding windows for train set
    X_train, y_train = create_sliding_windows(
        [Decimal(str(p)) for p in train_prices], window_days
    )

    # Create sliding windows for validation set
    X_val, y_val = create_sliding_windows(
        [Decimal(str(p)) for p in val_prices], window_days
    )

    logger.info(
        f"Training samples: {len(X_train)}, Validation samples: {len(X_val)}"
    )

    # Train all models
    successful_models: list[tuple[str, BaseModel, float]] = []

    for model_name, model_class in MODEL_CLASSES.items():
        result = train_single_model(
            model_class=model_class,
            model_name=model_name,
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            window_days=window_days,
        )

        if result is not None:
            model_instance, validation_error = result
            successful_models.append((model_name, model_instance, validation_error))

    if not successful_models:
        raise ValueError("All models failed to train")

    logger.info(f"Successfully trained {len(successful_models)}/{len(MODEL_CLASSES)} models")

    # Calculate training date range
    train_to = date.today()
    train_from = train_to - timedelta(days=len(prices))

    # Get next version number for each model
    # Query max version for each model name
    saved_models = []

    for model_name, model_instance, validation_error in successful_models:
        # Get existing versions for this model name
        stmt = (
            select(Model)
            .where(Model.name.like(f"{model_name}%"))
            .order_by(Model.trained_at.desc())
            .limit(1)
        )
        latest = session.execute(stmt).scalar_one_or_none()

        if latest and latest.version:
            # Extract version number and increment
            try:
                version_num = int(latest.version.split("v")[-1]) + 1
            except (ValueError, IndexError):
                version_num = 1
        else:
            version_num = 1

        version = f"v{version_num}"
        full_name = f"{model_name}_{version}"

        # Serialize model
        model_artifact = model_instance.serialize()

        # Create model record (is_active=False initially)
        model_record = Model(
            name=full_name,
            version=version,
            params={
                "window_days": window_days,
                "validation_error_pct": round(validation_error, 2),
                "training_samples": len(X_train),
                "validation_samples": len(X_val),
            },
            artifact=model_artifact,
            trained_at=datetime.now(UTC),
            train_from=train_from,
            train_to=train_to,
            is_active=False,  # All start inactive
        )

        session.add(model_record)
        saved_models.append((model_record, validation_error))

    # Commit all models
    session.commit()

    # Refresh to get IDs
    for model_record, _ in saved_models:
        session.refresh(model_record)

    logger.info(f"Saved {len(saved_models)} models to database")

    # Find best model (lowest validation error)
    best_model, best_error = min(saved_models, key=lambda x: x[1])

    logger.info(
        f"Best model: {best_model.name} with {best_error:.2f}% validation error"
    )

    # Activate best model
    crud_activate_model(session, best_model.id)
    session.commit()

    logger.info(f"✓ Activated {best_model.name}")

    # Log summary
    logger.info("=" * 60)
    logger.info("Multi-model training summary:")
    for model_record, val_error in saved_models:
        active_marker = "✓ ACTIVE" if model_record.id == best_model.id else ""
        logger.info(f"  - {model_record.name}: {val_error:.2f}% error {active_marker}")
    logger.info("=" * 60)

    return [m for m, _ in saved_models]


if __name__ == "__main__":
    sys.exit(main())
