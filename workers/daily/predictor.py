"""Daily predictor job: predicts tomorrow's BTC price with the active model.

Loads the active model, builds the return features of the recent daily closes
(``shared.features``) and stores ``last close * exp(predicted return)`` for the
evaluator. Exits 1 and saves nothing on a stale or gapped series or an old price
anchor (#174, #175).

Entry point: ``python -m workers.daily.predictor``, also run by ``workers.daily``.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def deserialize_model(model_record: Model) -> BaseModel:
    """Rebuild a model from the artifact of its database record.

    Raises:
        RuntimeError: If the name is unknown or deserialization fails.
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
    """Load the active ``1d`` model; the first one if several are active.

    Returns:
        The model record and its deserialized instance.

    Raises:
        ValueError: If no model is active.
        RuntimeError: If deserialization fails.
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
    """Fetch the latest ``days`` daily closes and volumes of ``symbol``.

    Takes the latest stored row of each day.

    Returns:
        Bar dates, closes and volumes, oldest to newest. The caller checks freshness
        and gaps with ``require_fresh_series``.

    Raises:
        ValueError: If fewer than ``days`` days are stored.
    """
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
    """Reject a model not trained on log returns, whose output would be misread.

    Raises:
        ValueError: If ``params["target"]`` is not the log-return marker.
    """
    if model_record.params.get("target") != LOG_RETURN_TARGET:
        raise ValueError(
            f"Model {model_record.name} was not trained on log returns "
            f"(params target={model_record.params.get('target')!r}); "
            f"retrain it before predicting"
        )


def prepare_features(series: DailySeries, window_days: int) -> npt.NDArray[np.float64]:
    """Features of the most recent day, shape (1, feature_count(window_days)).

    ``series`` needs at least ``window_days + 1`` rows.
    """
    return build_prediction_features(series.closes, series.volumes, window_days)


def check_existing_prediction(
    session: Session, predicted_for: date, model_id: int | None = None
) -> bool:
    """True if a prediction exists for ``predicted_for``, of ``model_id`` if given."""
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
    """Insert a prediction with its evaluation fields NULL (phase 1 of the lifecycle).

    Args:
        current_price: Price the prediction anchors on.
        predicted_price: Predicted price for ``predicted_for``.
    """
    prediction = Prediction(
        model_id=model_id,
        predicted_for=predicted_for,
        predicted_at=datetime.now(UTC),
        price_at_prediction=current_price,
        predicted_price=Decimal(str(predicted_price)),
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
    """What one predictor run generated, skipped and failed, by model name."""

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
    """Generate and save the prediction of one model, unless it already exists.

    Records the result in ``outcome``; errors propagate to the caller.
    """
    model_name = model_record.name

    if check_existing_prediction(session, tomorrow, model_id=model_record.id):
        logger.info(
            f"Prediction for {tomorrow} from {model_name} already exists, skipping"
        )
        outcome.skipped.append(model_name)
        return

    window_days = model_record.params.get("window_days", 30)
    logger.info(f"{model_name} requires {window_days} days of historical data")

    require_return_model(model_record)

    series = get_recent_series(session, required_history_days(window_days))

    # Refuse a stale series or one with gaps: no prediction is saved (#174)
    require_fresh_series(series.dates, today=tomorrow - timedelta(days=1))

    # Refuse a bar that closed too long ago: the price anchor must be tradable (#175)
    require_recent_close(
        series.dates[-1], now, timedelta(hours=settings.max_bar_age_hours)
    )

    X = prepare_features(series, window_days)

    # The model predicts tomorrow's log return; the price follows from it
    predicted_return = model_instance.predict(X)
    predicted_price = price_from_return(current_price, predicted_return)
    logger.info(
        f"{model_name} predicted return {predicted_return:+.4%}, "
        f"price: ${predicted_price:.2f}"
    )

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
    """Predict with the active model; log, record and re-raise any failure.

    ``main`` turns the re-raised error into a non-zero exit code.
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
    """0 if a prediction was generated or already existed, else 1."""
    if outcome.generated:
        logger.info(
            f"Predictor job completed successfully: "
            f"{len(outcome.generated)} prediction(s) generated"
        )
        return 0
    if outcome.skipped:
        logger.info(
            "Predictor job completed: all predictions already existed (idempotent)"
        )
        return 0

    logger.error("Predictor job failed: no predictions generated")
    return 1


def main(session: Session | None = None, now: datetime | None = None) -> int:
    """Run the predictor job.

    Args:
        session: Database session; tests pass one, otherwise a new one is opened.
        now: Clock; tests pass one. The last closed bar must be at most
            ``max_bar_age_hours`` old (#175).

    Returns:
        Exit code, 0 on success and 1 on failure.
    """
    logger.info("Starting daily predictor job")

    session_provided = session is not None
    if session is None:
        session = SessionLocal()

    try:
        run_at = now if now is not None else utc_now()
        tomorrow = utc_today() + timedelta(days=1)
        logger.info(f"Predicting for date: {tomorrow}")

        model_record, model_instance = get_active_model(session)

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
        if not session_provided:
            session.close()


if __name__ == "__main__":
    sys.exit(main())
