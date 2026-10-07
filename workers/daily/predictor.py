"""
Daily predictor job - predicts tomorrow's BTC price.

This job:
1. Loads the active ML model from the database
2. Fetches the recent daily closes and volumes
3. Builds the return features (shared.features) and predicts tomorrow's log return
4. Stores the predicted price, ``last close * exp(predicted return)``, in the
   database for later evaluation

Entry point: python -m workers.daily.predictor
"""

import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.config import settings
from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, Model, Prediction, Price
from shared.features import (
    LOG_RETURN_TARGET,
    DailySeries,
    build_prediction_features,
    price_from_return,
    require_fresh_series,
    require_recent_close,
    required_history_days,
)
from shared.utils import utc_now, utc_today
from workers.daily.models import BaseModel, LinearRegressionModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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
        if model_record.name.startswith("linear"):
            return LinearRegressionModel.deserialize(model_record.artifact)
        else:
            raise ValueError(f"Unknown model type: {model_record.name}")
    except Exception as e:
        raise RuntimeError(
            f"Failed to deserialize model {model_record.name}: {e}"
        ) from e


def get_active_model(session: Session) -> tuple[Model, BaseModel]:
    """
    Load the active daily (timeframe='1d') model from the database.

    Scoped to timeframe='1d', the only timeframe the models table accepts. If
    several models are active, the first one is used.

    Args:
        session: Database session

    Returns:
        Tuple of (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active model found
        RuntimeError: If deserialization fails
    """
    stmt = select(Model).where(
        Model.is_active == True,  # noqa: E712
        Model.timeframe == "1d",
    )
    model_record = session.execute(stmt.limit(1)).scalar_one_or_none()
    if model_record is None:
        raise ValueError("No active model found in database")

    model_instance = deserialize_model(model_record)
    logger.info(
        f"Loaded model: {model_record.name} v{model_record.version} "
        f"(trained {model_record.trained_at})"
    )
    return model_record, model_instance


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
        Bar dates, closes and volumes (oldest to newest). Freshness and gaps are
        checked by the caller with ``require_fresh_series``.

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
        select(latest_per_day.c.day, Price.close, Price.volume)
        .join(
            latest_per_day,
            Price.timestamp == latest_per_day.c.latest_timestamp,
        )
        .where(Price.symbol == symbol)
        .order_by(latest_per_day.c.day.desc())
    )

    rows = list(session.execute(stmt).all())

    if len(rows) < days:
        raise ValueError(f"Insufficient data: need {days} days, have {len(rows)}")

    # Reverse to get oldest to newest (chronological order)
    rows.reverse()

    logger.info(
        f"Fetched {len(rows)} DAYS of recent prices for feature preparation "
        f"(aggregated from multiple records/day)"
    )

    return DailySeries(
        dates=[row.day.date() for row in rows],
        closes=[row.close for row in rows],
        volumes=[row.volume for row in rows],
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
    now: datetime,
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

    # Refuse a stale series or one with gaps: no prediction is saved (#174)
    require_fresh_series(series.dates, today=tomorrow - timedelta(days=1))

    # Refuse a bar that closed too long ago: the price anchor must be tradable (#175)
    require_recent_close(
        series.dates[-1], now, timedelta(hours=settings.max_bar_age_hours)
    )

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
    model_record: Model,
    model_instance: BaseModel,
    tomorrow: date,
    current_price: Decimal,
    outcome: PredictionOutcome,
    now: datetime,
) -> None:
    """
    Predict with the active model and fail immediately.

    A failure is logged, recorded in ``outcome`` and re-raised so ``main``
    turns it into a non-zero exit code.
    """
    try:
        _predict_one(
            session,
            model_record,
            model_instance,
            tomorrow,
            current_price,
            outcome,
            now,
        )
    except Exception as e:
        logger.exception(f"Failed to generate prediction for {model_record.name}: {e}")
        outcome.failed.append((model_record.name, str(e)))
        raise


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


def main(session: Session | None = None, now: datetime | None = None) -> int:
    """
    Main entry point for the predictor job.

    Args:
        session: Optional database session (for testing). If None, creates new session.
        now: Optional clock (for testing). If None, the current UTC instant. The
            last closed bar must be at most ``max_bar_age_hours`` old (#175).

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting daily predictor job")

    # Use provided session or create new one
    session_provided = session is not None
    if session is None:
        session = SessionLocal()

    try:
        # Calculate tomorrow's date
        run_at = now if now is not None else utc_now()
        tomorrow = utc_today() + timedelta(days=1)
        logger.info(f"Predicting for date: {tomorrow}")

        model_record, model_instance = get_active_model(session)

        # Get the current price
        current_price_stmt = (
            select(Price.close)
            .where(Price.symbol == DEFAULT_SYMBOL)
            .order_by(Price.timestamp.desc())
            .limit(1)
        )
        current_price = session.execute(current_price_stmt).scalar_one()
        logger.info(f"Current BTC price: ${current_price}")

        outcome = PredictionOutcome()

        _predict_single_model(
            session,
            model_record,
            model_instance,
            tomorrow,
            current_price,
            outcome,
            run_at,
        )

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
