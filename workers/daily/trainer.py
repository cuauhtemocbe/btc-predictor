"""
Daily trainer job - trains ML model on historical BTC price data.

This job:
1. Reads the sliding-window size from settings.training_window_days
2. Fetches every stored daily BTCUSDT close price
3. Builds return-based features (shared.features) and the next-day log return target
4. Trains the model on log returns, not on price levels
5. Saves the trained model to the database
6. Sets it as the active model (deactivates previous models)

Training needs at least (window + 1) * 5 daily rows so the 70/20/10 split leaves
the validation set enough samples; with fewer rows the job fails and reports the
required and available counts.

Multi-Model Training:
- ARIMA requires 60+ days (excluded automatically with less data)

Entry point: python -m workers.daily.trainer
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta

import numpy as np
import numpy.typing as npt
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
)
from shared.utils import calculate_mape, split_train_validation
from workers.daily.models import BaseModel, LinearRegressionModel
from workers.daily.models.factory import instantiate_model

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def required_training_days(window_days: int, horizon_days: int = 1) -> int:
    """
    Minimum number of daily rows needed to train.

    The 70/20/10 split gives the validation set 20% of the rows, and it needs
    at least window_days + 1 of them to build one sample: rows >= (window + 1) * 5.
    A horizon longer than one day needs horizon_days - 1 extra rows so the last
    sample still has a target.
    """
    return (window_days + 1) * 5 + horizon_days - 1


def fetch_training_data(
    session: Session,
    window_days: int,
    horizon_days: int = 1,
    symbol: str = DEFAULT_SYMBOL,
) -> DailySeries:
    """
    Fetch every stored DAILY close price and volume of one symbol for training.

    Uses date aggregation to get exactly one row per day (not per hour/4h).
    Takes the latest row (its close and volume) for each day.

    Args:
        session: Database session
        window_days: Size of sliding window for features
        horizon_days: Days past the window the target sits (1 daily, 7 weekly)
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
        select(Price.close, Price.volume)
        .join(
            latest_per_day,
            Price.timestamp == latest_per_day.c.latest_timestamp,
        )
        .where(Price.symbol == symbol)
        .order_by(latest_per_day.c.day)
    )

    rows = session.execute(stmt).all()

    required = required_training_days(window_days, horizon_days)
    if len(rows) < required:
        raise ValueError(
            f"Insufficient training data for {symbol}: need {required} daily rows "
            f"(window={window_days}d, horizon={horizon_days}d), have {len(rows)}"
        )

    logger.info(
        f"Fetched {len(rows)} DAYS of {symbol} prices for training "
        f"(aggregated from multiple records/day)"
    )

    return DailySeries(
        closes=[row.close for row in rows], volumes=[row.volume for row in rows]
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

        # Return features and next-day log return target
        training_set = build_training_set(
            series.closes, series.volumes, window_days, horizon_days=1
        )
        logger.info(f"Created {len(training_set.y)} training samples")

        # Train model
        logger.info("Training LinearRegressionModel on log returns...")
        model = LinearRegressionModel(
            window_days=window_days, n_features=feature_count(window_days)
        )
        model.train(training_set.X, training_set.y)

        # Calculate training date range
        # One row per day, so the series length is the day range
        train_to = date.today()
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


def train_single_model(
    model_class: type[BaseModel],
    model_name: str,
    X_train: npt.NDArray[np.float64],
    y_train: npt.NDArray[np.float64],
    X_val: npt.NDArray[np.float64],
    y_val: npt.NDArray[np.float64],
    window_days: int,
    base_close_val: npt.NDArray[np.float64] | None = None,
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
        base_close_val: Close of the day each validation sample was built at. When
            given, y_val and the predictions are log returns and the error is the
            MAPE of the prices they imply (base_close * exp(return)); when None,
            the MAPE is computed on y_val directly.

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
        # Same construction the walk-forward backtest uses
        model = instantiate_model(
            model_class, model_name, window_days, X_train.shape[1]
        )

        # Train model
        model.train(X_train, y_train)

        # Validate model - predict on validation set
        predictions = [model.predict(X_val[i : i + 1]) for i in range(len(X_val))]
        y_val_pred = np.array(predictions)

        # Calculate MAPE validation error (on prices when targets are returns)
        if base_close_val is None:
            validation_error = calculate_mape(y_val, y_val_pred)
        else:
            validation_error = calculate_mape(
                base_close_val * np.exp(y_val), base_close_val * np.exp(y_val_pred)
            )

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


def model_registry(days_available: int) -> dict[str, type[BaseModel]]:
    """
    Model classes to train for the amount of data available.

    ARIMA requires at least 60 days of data. The LSTM, XGBoost and ARIMA
    classes are imported here, not at module level, because importing them
    loads TensorFlow, XGBoost and statsmodels.
    """
    from workers.daily.models import ARIMAModel, LSTMModel, XGBoostModel

    registry: dict[str, type[BaseModel]] = {
        "linear": LinearRegressionModel,
        "lstm": LSTMModel,
        "xgboost": XGBoostModel,
    }

    if days_available >= 60:
        registry["arima"] = ARIMAModel
        logger.info("ARIMA model included (sufficient data: 60+ days)")
    else:
        logger.info(f"ARIMA model excluded (need 60+ days, have {days_available} days)")

    return registry


def train_all_models(
    session: Session,
    window_days: int | None = None,
) -> list[Model]:
    """
    Train all available ML models with the same training data.

    Uses every stored BTCUSDT daily row; excludes ARIMA if fewer than 60 days.

    This function:
    1. Reads the window from settings.training_window_days (if not provided)
    2. Fetches historical price data
    3. Splits into train/validation sets (70/20/10)
    4. Trains available models (3-4 models depending on data)
    5. Calculates validation error (MAPE) for each
    6. Saves all models to database with is_active=False
    7. Activates the model with lowest validation error

    Args:
        session: Database session
        window_days: Size of sliding window (settings.training_window_days if None)

    Returns:
        List of created Model records

    Raises:
        ValueError: If insufficient data available
    """
    logger.info("Starting multi-model training...")

    if window_days is None:
        window_days = settings.training_window_days
    logger.info(f"Training window: {window_days}d")

    # Fetch training data
    series = fetch_training_data(session, window_days)

    # Model registry - ARIMA needs 60+ days of data
    MODEL_CLASSES = model_registry(len(series))

    # Split into train/validation (70/20/10)
    logger.info("Splitting data: 70% train, 20% validation, 10% buffer")
    closes = np.array([float(c) for c in series.closes])
    volumes = np.array([float(v) for v in series.volumes])
    train_closes, val_closes = split_train_validation(
        closes, train_pct=0.7, val_pct=0.2
    )
    train_volumes, val_volumes = split_train_validation(
        volumes, train_pct=0.7, val_pct=0.2
    )

    logger.info(
        f"Train set: {len(train_closes)} days, Validation set: {len(val_closes)} days"
    )

    # Return features and next-day log return targets for each set
    train_set = build_training_set(train_closes, train_volumes, window_days)
    val_set = build_training_set(val_closes, val_volumes, window_days)
    X_train, y_train = train_set.X, train_set.y
    x_val, y_val = val_set.X, val_set.y

    logger.info(f"Training samples: {len(X_train)}, Validation samples: {len(x_val)}")

    # Train all models
    successful_models: list[tuple[str, BaseModel, float]] = []

    for model_name, model_class in MODEL_CLASSES.items():
        result = train_single_model(
            model_class=model_class,
            model_name=model_name,
            X_train=X_train,
            y_train=y_train,
            X_val=x_val,
            y_val=y_val,
            window_days=window_days,
            base_close_val=val_set.base_close,
        )

        if result is not None:
            model_instance, validation_error = result
            successful_models.append((model_name, model_instance, validation_error))

    if not successful_models:
        raise ValueError("All models failed to train")

    num_success = len(successful_models)
    num_total = len(MODEL_CLASSES)
    logger.info(f"Successfully trained {num_success}/{num_total} models")

    # Calculate training date range
    train_to = date.today()
    train_from = train_to - timedelta(days=len(series))

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
                "horizon_days": 1,
                "target": LOG_RETURN_TARGET,
                "validation_error_pct": round(validation_error, 2),
                "training_samples": len(X_train),
                "validation_samples": len(x_val),
            },
            artifact=model_artifact,
            trained_at=datetime.now(UTC),
            train_from=train_from,
            train_to=train_to,
            timeframe="1d",
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

    # Activate best model (commits internally, scoped to its own timeframe)
    crud_activate_model(session, best_model.id)

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
