"""
Daily predictor job - predicts tomorrow's BTC price.

This job:
1. Loads the active ML model(s) from the database
2. Fetches recent historical prices
3. Generates prediction(s) for tomorrow
4. Stores the prediction(s) in the database for later evaluation

Modes:
- Single-model mode (default): Uses only the primary active model
- Multi-model mode (--multi-model): Generates predictions from ALL active models

Entry point: python -m daily.predictor [--multi-model]
"""

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice, Model, Prediction
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


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments with multi_model flag
    """
    parser = argparse.ArgumentParser(
        description="BTC Predictor - Generate price predictions for tomorrow"
    )
    parser.add_argument(
        "--multi-model",
        action="store_true",
        help="Generate predictions from ALL active models (default: single primary model)",
    )
    return parser.parse_args()


def deserialize_model(model_record: Model) -> BaseModel:
    """
    Deserialize a model from its binary artifact.

    Args:
        model_record: Model database record with artifact bytes

    Returns:
        Deserialized BaseModel instance

    Raises:
        ValueError: If model type is unknown
        RuntimeError: If deserialization fails
    """
    try:
        # Map model name prefixes to their classes
        if model_record.name.startswith("linear"):
            return LinearRegressionModel.deserialize(model_record.artifact)
        elif model_record.name.startswith("xgboost"):
            return XGBoostModel.deserialize(model_record.artifact)
        elif model_record.name.startswith("lstm"):
            return LSTMModel.deserialize(model_record.artifact)
        elif model_record.name.startswith("arima"):
            return ARIMAModel.deserialize(model_record.artifact)
        else:
            raise ValueError(f"Unknown model type: {model_record.name}")
    except Exception as e:
        raise RuntimeError(
            f"Failed to deserialize model {model_record.name}: {e}"
        ) from e


def get_active_models(
    session: Session, multi_model: bool = False
) -> list[tuple[Model, BaseModel]]:
    """
    Load active model(s) from the database.

    Args:
        session: Database session
        multi_model: If True, load ALL active models. If False, load only primary model.

    Returns:
        List of tuples: (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active models found
    """
    stmt = select(Model).where(Model.is_active == True)  # noqa: E712

    if multi_model:
        # Fetch all active models
        model_records = session.execute(stmt).scalars().all()
        mode_str = "multi-model"
    else:
        # Fetch only the first active model (primary)
        # Use limit(1) to handle case where multiple models are active
        model_record = session.execute(stmt.limit(1)).scalar_one_or_none()
        model_records = [model_record] if model_record else []
        mode_str = "single-model"

    if not model_records:
        raise ValueError(f"No active models found in database ({mode_str} mode)")

    # Deserialize all models
    models = []
    for model_record in model_records:
        try:
            model_instance = deserialize_model(model_record)
            models.append((model_record, model_instance))
            logger.info(
                f"Loaded model: {model_record.name} v{model_record.version} "
                f"(trained {model_record.trained_at})"
            )
        except RuntimeError as e:
            # Log error but continue with other models in multi-model mode
            logger.error(f"Failed to load model {model_record.name}: {e}")
            if not multi_model:
                # In single-model mode, fail immediately
                raise

    if not models:
        raise ValueError(f"All active models failed to deserialize ({mode_str} mode)")

    logger.info(f"Loaded {len(models)} active model(s) in {mode_str} mode")
    return models


def get_active_model(session: Session) -> tuple[Model, BaseModel]:
    """
    Load the active model from the database (backward compatibility wrapper).

    DEPRECATED: Use get_active_models() instead.

    Args:
        session: Database session

    Returns:
        Tuple of (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active model found
        RuntimeError: If deserialization fails
    """
    models = get_active_models(session, multi_model=False)
    return models[0]


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
    stmt = select(BtcPrice.close).order_by(BtcPrice.timestamp.desc()).limit(window_days)
    results = session.execute(stmt).scalars().all()

    if len(results) < window_days:
        raise ValueError(f"Insufficient data: need {window_days}, have {len(results)}")

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


def check_existing_prediction(
    session: Session, predicted_for: date, model_id: int | None = None
) -> bool:
    """
    Check if a prediction already exists for the given date and model.

    Args:
        session: Database session
        predicted_for: Date to check
        model_id: Model ID to check (optional, for idempotency per model)

    Returns:
        True if prediction exists, False otherwise
    """
    stmt = select(Prediction).where(Prediction.predicted_for == predicted_for)

    if model_id is not None:
        stmt = stmt.where(Prediction.model_id == model_id)

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


def main(session: Session | None = None) -> int:
    """
    Main entry point for the predictor job.

    Supports two modes:
    - Single-model (default): Predict with one primary model
    - Multi-model (--multi-model): Predict with all active models

    Args:
        session: Optional database session (for testing). If None, creates new session.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    # Parse command-line arguments
    args = parse_args()

    mode_str = "multi-model" if args.multi_model else "single-model"
    logger.info(f"Starting daily predictor job in {mode_str} mode")

    # Use provided session or create new one
    session_provided = session is not None
    if session is None:
        session = SessionLocal()

    try:
        # Calculate tomorrow's date
        tomorrow = date.today() + timedelta(days=1)
        logger.info(f"Predicting for date: {tomorrow}")

        # Load active model(s) based on mode
        models = get_active_models(session, multi_model=args.multi_model)

        # Get current price once (same for all models)
        current_price_stmt = (
            select(BtcPrice.close).order_by(BtcPrice.timestamp.desc()).limit(1)
        )
        current_price = session.execute(current_price_stmt).scalar_one()
        logger.info(f"Current BTC price: ${current_price}")

        # Track predictions generated
        predictions_generated = []
        predictions_skipped = []
        predictions_failed = []

        # Generate prediction for each active model
        for model_record, model_instance in models:
            model_name = model_record.name

            try:
                # Check if prediction already exists for this model (idempotency)
                if check_existing_prediction(
                    session, tomorrow, model_id=model_record.id
                ):
                    logger.info(
                        f"Prediction for {tomorrow} from {model_name} already exists, skipping"
                    )
                    predictions_skipped.append(model_name)
                    continue

                # Get window_days from model params
                window_days = model_record.params.get("window_days", 30)
                logger.info(
                    f"{model_name} requires {window_days} days of historical data"
                )

                # Fetch recent prices
                prices = get_recent_prices(session, window_days)

                # Prepare features
                X = prepare_features(prices)

                # Make prediction
                predicted_price = model_instance.predict(X)
                logger.info(f"{model_name} predicted price: ${predicted_price:.2f}")

                # Save prediction
                save_prediction(
                    session=session,
                    model_id=model_record.id,
                    predicted_for=tomorrow,
                    current_price=current_price,
                    predicted_price=predicted_price,
                )

                predictions_generated.append((model_name, predicted_price))

            except Exception as e:
                # In multi-model mode, log error and continue with other models
                # In single-model mode, this exception will propagate to outer try/except
                logger.error(f"Failed to generate prediction for {model_name}: {e}")
                predictions_failed.append((model_name, str(e)))

                if not args.multi_model:
                    # In single-model mode, fail immediately
                    raise

        # Log summary
        logger.info("=" * 60)
        logger.info(f"Predictions for {tomorrow}:")
        for model_name, predicted_price in predictions_generated:
            logger.info(f"  ✓ {model_name}: ${predicted_price:,.2f}")

        if predictions_skipped:
            logger.info(f"Skipped (already exist): {', '.join(predictions_skipped)}")

        if predictions_failed:
            logger.warning(f"Failed: {len(predictions_failed)} model(s)")
            for model_name, error in predictions_failed:
                logger.warning(f"  ✗ {model_name}: {error}")

        logger.info("=" * 60)

        # Success if at least one prediction was generated
        if predictions_generated:
            logger.info(
                f"Predictor job completed successfully: "
                f"{len(predictions_generated)} prediction(s) generated"
            )
            return 0
        elif predictions_skipped:
            # All predictions already existed (idempotent re-run)
            logger.info(
                "Predictor job completed: all predictions already existed (idempotent)"
            )
            return 0
        else:
            # No predictions generated and none skipped = all failed
            logger.error("Predictor job failed: no predictions generated")
            return 1

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
        # Only close session if we created it
        if not session_provided:
            session.close()


if __name__ == "__main__":
    sys.exit(main())
