"""
Daily predictor job - predicts tomorrow's BTC price.

This job:
1. Loads the active ML model(s) from the database
2. Fetches the recent daily closes and volumes
3. Builds the return features (shared.features) and predicts tomorrow's log return
4. Stores the predicted price, ``last close * exp(predicted return)``, in the
   database for later evaluation

Modes:
- Single-model mode (default): Uses only the primary active model
- Multi-model mode (--multi-model): Generates predictions from ALL active models

Entry point: python -m daily.predictor [--multi-model]
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, Model, Prediction, Price
from shared.features import (
    LOG_RETURN_TARGET,
    DailySeries,
    build_prediction_features,
    price_from_return,
    required_history_days,
)
from workers.daily.models import BaseModel, LinearRegressionModel

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
        help="Generate predictions from ALL active models "
        "(default: single primary model)",
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
        # Map model name prefixes to their classes. The heavy ones are imported
        # on demand: loading them pulls in TensorFlow/XGBoost/statsmodels.
        if model_record.name.startswith("linear"):
            return LinearRegressionModel.deserialize(model_record.artifact)
        elif model_record.name.startswith("xgboost"):
            from workers.daily.models import XGBoostModel

            return XGBoostModel.deserialize(model_record.artifact)
        elif model_record.name.startswith("lstm"):
            from workers.daily.models import LSTMModel

            return LSTMModel.deserialize(model_record.artifact)
        elif model_record.name.startswith("arima"):
            from workers.daily.models import ARIMAModel

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
    Load active daily (timeframe='1d') model(s) from the database.

    Scoped to timeframe='1d' so this never picks up the active weekly
    model -- a '1d' and a '1w' model can be active at the same time (see
    ix_models_one_active_per_timeframe).

    Args:
        session: Database session
        multi_model: If True, load ALL active models. If False, load only primary model.

    Returns:
        List of tuples: (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active models found
    """
    stmt = select(Model).where(
        Model.is_active == True,  # noqa: E712
        Model.timeframe == "1d",
    )

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


def get_recent_series(
    session: Session, days: int, symbol: str = DEFAULT_SYMBOL
) -> DailySeries:
    """
    Fetch the most recent N DAYS of close prices and volumes of one symbol.

    Uses date aggregation to get exactly one row per day (not per hour/4h).
    Takes the latest row (its close and volume) for each day.

    Args:
        session: Database session
        days: Number of DAYS to fetch
        symbol: Asset whose prices are read (default BTCUSDT)

    Returns:
        Daily closes and volumes (oldest to newest)

    Raises:
        ValueError: If insufficient historical data available
    """
    # Subquery: Get the latest timestamp for each day
    latest_per_day = (
        select(
            func.date_trunc("day", Price.timestamp).label("day"),
            func.max(Price.timestamp).label("latest_timestamp"),
        )
        .where(Price.symbol == symbol)
        .group_by("day")
        .order_by(func.date_trunc("day", Price.timestamp).desc())
        .limit(days)
        .subquery()
    )

    # Main query: Join to get the close and volume for the latest timestamp each day
    stmt = (
        select(Price.close, Price.volume)
        .join(
            latest_per_day,
            Price.timestamp == latest_per_day.c.latest_timestamp,
        )
        .where(Price.symbol == symbol)
        .order_by(latest_per_day.c.day.desc())
    )

    rows = session.execute(stmt).all()

    if len(rows) < days:
        raise ValueError(f"Insufficient data: need {days} days, have {len(rows)}")

    # Reverse to get oldest to newest (chronological order)
    rows.reverse()

    logger.info(
        f"Fetched {len(rows)} DAYS of recent prices for feature preparation "
        f"(aggregated from multiple records/day)"
    )

    return DailySeries(
        closes=[row.close for row in rows], volumes=[row.volume for row in rows]
    )


def require_return_model(model_record: Model) -> None:
    """
    Reject a model that was not trained on log returns.

    A model trained on price levels would have its output read as a return, so
    the predictor refuses it until the trainer replaces it.

    Raises:
        ValueError: If the model's params do not mark a log-return target
    """
    if model_record.params.get("target") != LOG_RETURN_TARGET:
        raise ValueError(
            f"Model {model_record.name} was not trained on log returns "
            f"(params target={model_record.params.get('target')!r}); "
            f"retrain it before predicting"
        )


def prepare_features(series: DailySeries, window_days: int) -> npt.NDArray[np.float64]:
    """
    Build the return features of the most recent day for a single prediction.

    Args:
        series: Daily closes and volumes (oldest to newest), at least
            window_days + 1 rows
        window_days: Window the model was trained with

    Returns:
        Numpy array of shape (1, feature_count(window_days))
    """
    return build_prediction_features(series.closes, series.volumes, window_days)


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


@dataclass
class PredictionOutcome:
    """Results of one predictor run, one entry per model."""

    generated: list[tuple[str, float]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _predict_one(
    session: Session,
    model_record: Model,
    model_instance: BaseModel,
    tomorrow: date,
    current_price: Decimal,
    outcome: PredictionOutcome,
) -> None:
    """
    Generate and save the prediction of one model, unless it already exists.

    Records the result in ``outcome`` (skipped or generated). Any error
    propagates to the caller, which decides whether to continue.
    """
    model_name = model_record.name

    # Check if prediction already exists for this model (idempotency)
    if check_existing_prediction(session, tomorrow, model_id=model_record.id):
        logger.info(
            f"Prediction for {tomorrow} from {model_name} already exists, skipping"
        )
        outcome.skipped.append(model_name)
        return

    # Get window_days from model params
    window_days = model_record.params.get("window_days", 30)
    logger.info(f"{model_name} requires {window_days} days of historical data")

    require_return_model(model_record)

    # Fetch recent prices (window_days returns need window_days + 1 closes)
    series = get_recent_series(session, required_history_days(window_days))

    # Prepare features
    X = prepare_features(series, window_days)

    # The model predicts tomorrow's log return; the price follows from it
    predicted_return = model_instance.predict(X)
    predicted_price = price_from_return(current_price, predicted_return)
    logger.info(
        f"{model_name} predicted return {predicted_return:+.4%}, "
        f"price: ${predicted_price:.2f}"
    )

    # Save prediction
    save_prediction(
        session=session,
        model_id=model_record.id,
        predicted_for=tomorrow,
        current_price=current_price,
        predicted_price=predicted_price,
    )

    outcome.generated.append((model_name, predicted_price))


def _predict_single_model(
    session: Session,
    models: list[tuple[Model, BaseModel]],
    tomorrow: date,
    current_price: Decimal,
    outcome: PredictionOutcome,
) -> None:
    """
    Single-model mode: predict with the primary model and fail immediately.

    A failure is logged, recorded in ``outcome`` and re-raised so ``main``
    turns it into a non-zero exit code.
    """
    for model_record, model_instance in models:
        try:
            _predict_one(
                session, model_record, model_instance, tomorrow, current_price, outcome
            )
        except Exception as e:
            logger.error(f"Failed to generate prediction for {model_record.name}: {e}")
            outcome.failed.append((model_record.name, str(e)))
            raise


def _predict_multi_model(
    session: Session,
    models: list[tuple[Model, BaseModel]],
    tomorrow: date,
    current_price: Decimal,
    outcome: PredictionOutcome,
) -> None:
    """
    Multi-model mode: predict with every active model, continuing after errors.

    A failure is logged and recorded in ``outcome``; the other models still run.
    """
    for model_record, model_instance in models:
        try:
            _predict_one(
                session, model_record, model_instance, tomorrow, current_price, outcome
            )
        except Exception as e:
            logger.error(f"Failed to generate prediction for {model_record.name}: {e}")
            outcome.failed.append((model_record.name, str(e)))


def _log_prediction_summary(tomorrow: date, outcome: PredictionOutcome) -> None:
    """Log what the run generated, skipped and failed."""
    logger.info("=" * 60)
    logger.info(f"Predictions for {tomorrow}:")
    for model_name, predicted_price in outcome.generated:
        logger.info(f"  ✓ {model_name}: ${predicted_price:,.2f}")

    if outcome.skipped:
        logger.info(f"Skipped (already exist): {', '.join(outcome.skipped)}")

    if outcome.failed:
        logger.warning(f"Failed: {len(outcome.failed)} model(s)")
        for model_name, error in outcome.failed:
            logger.warning(f"  ✗ {model_name}: {error}")

    logger.info("=" * 60)


def _exit_code(outcome: PredictionOutcome) -> int:
    """Exit code of the run: 0 if anything was generated or already existed."""
    # Success if at least one prediction was generated
    if outcome.generated:
        logger.info(
            f"Predictor job completed successfully: "
            f"{len(outcome.generated)} prediction(s) generated"
        )
        return 0
    if outcome.skipped:
        # All predictions already existed (idempotent re-run)
        logger.info(
            "Predictor job completed: all predictions already existed (idempotent)"
        )
        return 0

    # No predictions generated and none skipped = all failed
    logger.error("Predictor job failed: no predictions generated")
    return 1


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
            select(Price.close)
            .where(Price.symbol == DEFAULT_SYMBOL)
            .order_by(Price.timestamp.desc())
            .limit(1)
        )
        current_price = session.execute(current_price_stmt).scalar_one()
        logger.info(f"Current BTC price: ${current_price}")

        outcome = PredictionOutcome()

        # Generate prediction for each active model
        if args.multi_model:
            _predict_multi_model(session, models, tomorrow, current_price, outcome)
        else:
            _predict_single_model(session, models, tomorrow, current_price, outcome)

        _log_prediction_summary(tomorrow, outcome)

        return _exit_code(outcome)

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
