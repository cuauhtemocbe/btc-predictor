"""
Daily trainer job - trains ML model on historical BTC price data.

This job:
1. Detects available historical data and calculates optimal window size
2. Fetches recent historical prices (adapts to available data: 30-200+ days)
3. Creates sliding window features for time series prediction
4. Trains ML models (adapts model selection based on data availability)
5. Saves the trained model to the database
6. Sets it as the active model (deactivates previous models)

Dynamic Window Strategy:
- < 30 days: Not enough data to train
- 30-44 days: window=5, min=30 (Phase 1: Initial - limited data)
- 45-59 days: window=7, min=40 (Phase 2: Growth)
- 60-89 days: window=10, min=55 (Phase 3: Intermediate)
- 90-144 days: window=14, min=75 (Phase 4: Mature)
- 145+ days: window=21, min=110 (Phase 5: Optimal)

Multi-Model Training:
- ARIMA requires 60+ days (excluded automatically with less data)
- Linear, LSTM, XGBoost work with any phase

Entry point: python -m workers.daily.trainer
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select
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


def calculate_dynamic_window(days_available: int) -> tuple[int, int]:
    """
    Calculate optimal window_days and min_days based on available historical data.

    This allows the system to start training with limited data and automatically
    improve as more data accumulates over time.

    The min_days calculation ensures enough data for train/validation split (70/20/10):
    - Validation set needs at least (window_days + 1) samples
    - With 20% for validation: min_days >= (window_days + 1) * 5

    Args:
        days_available: Number of days of historical data available in database

    Returns:
        Tuple of (window_days, min_days) where:
        - window_days: Size of sliding window for features
        - min_days: Minimum days needed (accounts for train/val split)

    Raises:
        ValueError: If less than 30 days available (insufficient for training)

    Strategy:
    - Phase 1 (30-44 days): window=5, min=30 - Initial phase (limited data)
    - Phase 2 (45-59 days): window=7, min=40 - Growth phase
    - Phase 3 (60-89 days): window=10, min=55 - Intermediate phase
    - Phase 4 (90-144 days): window=14, min=75 - Mature phase
    - Phase 5 (145+ days): window=21, min=110 - Optimal configuration

    Example:
        >>> calculate_dynamic_window(30)
        (5, 30)  # Initial phase
        >>> calculate_dynamic_window(200)
        (21, 110)  # Optimal phase
    """
    # With 70/20/10 split, validation set is 20% of total
    # Need at least (window + 1) elements in validation to create 1 sample
    # Therefore: min_days * 0.2 >= window + 1
    # Solving: min_days >= (window + 1) * 5

    if days_available < 30:
        raise ValueError(
            f"Insufficient data for training: {days_available} days available, "
            f"need at least 30 days. Wait for more data to accumulate."
        )
    elif days_available < 45:
        return (5, 30)  # Phase 1: window=5 -> min = 6*5 = 30
    elif days_available < 60:
        return (7, 40)  # Phase 2: window=7 -> min = 8*5 = 40
    elif days_available < 90:
        return (10, 55)  # Phase 3: window=10 -> min = 11*5 = 55
    elif days_available < 145:
        return (14, 75)  # Phase 4: window=14 -> min = 15*5 = 75
    else:
        return (21, 110)  # Phase 5: window=21 -> min = 22*5 = 110


def count_available_days(session: Session) -> int:
    """
    Count how many distinct days of price data are available in the database.

    Returns:
        Number of distinct days with price data
    """
    stmt = select(func.count(func.distinct(func.date_trunc("day", BtcPrice.timestamp))))
    count = session.execute(stmt).scalar_one()
    return count


def _get_phase_name(days_available: int) -> str:
    """
    Get human-readable phase name for logging.

    Args:
        days_available: Number of days of historical data

    Returns:
        Phase name (e.g., "Initial", "Optimal")
    """
    if days_available < 30:
        return "Insufficient"
    elif days_available < 45:
        return "Phase 1 - Initial"
    elif days_available < 60:
        return "Phase 2 - Growth"
    elif days_available < 90:
        return "Phase 3 - Intermediate"
    elif days_available < 145:
        return "Phase 4 - Mature"
    else:
        return "Phase 5 - Optimal"


def fetch_training_data(
    session: Session, window_days: int = 30, min_days: int = 60
) -> list[Decimal]:
    """
    Fetch historical DAILY BTC close prices for training.

    Uses date aggregation to get exactly one price per day (not per hour/4h).
    Takes the latest close price for each day.

    Args:
        session: Database session
        window_days: Size of sliding window for features
        min_days: Minimum number of DAYS needed (window_days * 2)

    Returns:
        List of daily close prices (oldest to newest)

    Raises:
        ValueError: If insufficient data available
    """
    # Subquery: Get the latest timestamp for each day
    latest_per_day = (
        select(
            func.date_trunc("day", BtcPrice.timestamp).label("day"),
            func.max(BtcPrice.timestamp).label("latest_timestamp"),
        )
        .group_by("day")
        .order_by(func.date_trunc("day", BtcPrice.timestamp).desc())
        .limit(min_days)
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

    if len(results) < min_days:
        raise ValueError(
            f"Insufficient training data: need {min_days} days, have {len(results)}"
        )

    # Reverse to get oldest to newest (chronological order)
    prices = list(reversed(results))

    logger.info(
        f"Fetched {len(prices)} DAYS of historical prices for training "
        f"(aggregated from multiple records/day)"
    )

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
        params={"window_days": window_days},
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
        # Detect available data and calculate optimal window
        days_available = count_available_days(session)
        logger.info(f"Available historical data: {days_available} days")

        window_days, min_days = calculate_dynamic_window(days_available)
        logger.info(
            f"Dynamic configuration: window={window_days}d, min={min_days}d "
            f"(Phase: {_get_phase_name(days_available)})"
        )

        # Configuration
        model_name = "linear_v1"
        version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M%S")  # Timestamp version

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
        predictions = [model.predict(X_val[i : i + 1]) for i in range(len(X_val))]
        y_val_pred = np.array(predictions)

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
    window_days: int | None = None,
    min_days: int | None = None,
) -> list[Model]:
    """
    Train all available ML models with the same training data.

    Dynamically adapts training strategy based on available historical data:
    - Detects available data and calculates optimal window size
    - Excludes ARIMA if less than 60 days (ARIMA needs more data)
    - Automatically scales to optimal configuration as data accumulates

    This function:
    1. Detects available data and calculates optimal window (if not provided)
    2. Fetches historical price data
    3. Splits into train/validation sets (70/20/10)
    4. Trains available models (3-4 models depending on data)
    5. Calculates validation error (MAPE) for each
    6. Saves all models to database with is_active=False
    7. Activates the model with lowest validation error

    Args:
        session: Database session
        window_days: Size of sliding window (auto-calculated if None)
        min_days: Minimum days needed (auto-calculated if None)

    Returns:
        List of created Model records

    Raises:
        ValueError: If insufficient data available
    """
    logger.info("Starting multi-model training...")

    # Auto-detect configuration if not provided
    if window_days is None or min_days is None:
        days_available = count_available_days(session)
        logger.info(f"Available historical data: {days_available} days")
        window_days, min_days = calculate_dynamic_window(days_available)
        logger.info(
            f"Dynamic configuration: window={window_days}d, min={min_days}d "
            f"(Phase: {_get_phase_name(days_available)})"
        )
    else:
        # If provided, count days to determine model selection
        days_available = count_available_days(session)

    # Model registry - adapt based on available data
    # ARIMA requires at least 60 days of data
    MODEL_CLASSES = {
        "linear": LinearRegressionModel,
        "lstm": LSTMModel,
        "xgboost": XGBoostModel,
    }

    if days_available >= 60:
        MODEL_CLASSES["arima"] = ARIMAModel
        logger.info("ARIMA model included (sufficient data: 60+ days)")
    else:
        logger.info(f"ARIMA model excluded (need 60+ days, have {days_available} days)")

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

    logger.info(f"Training samples: {len(X_train)}, Validation samples: {len(X_val)}")

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

    num_success = len(successful_models)
    num_total = len(MODEL_CLASSES)
    logger.info(f"Successfully trained {num_success}/{num_total} models")

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
