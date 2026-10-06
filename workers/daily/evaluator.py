"""
Daily evaluator job - evaluates the BTC price predictions that are due.

This job:
1. Finds ALL daily predictions due today or earlier that haven't been evaluated
2. Fetches the close of the daily bar each prediction was about (the bar opened
   the day before ``predicted_for``, which closes at 00:00 UTC on that date)
3. Calculates error metrics (absolute, percentage, direction correctness)
4. Calculates simulated PnL based on prediction strategy
5. Updates the prediction records with evaluation results

A prediction whose bar is not stored yet stays pending and is picked up by a
later run, so a missed or late ingest never leaves it unevaluated for good.

Supports multi-model predictions (evaluates predictions from all models).

Entry point: python -m workers.daily.evaluator
"""

import logging
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from itertools import groupby
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, Prediction, Price
from shared.utils import (
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
    utc_today,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def find_unevaluated_predictions(
    session: Session, predicted_for: date
) -> list[Prediction]:
    """
    Find ALL predictions for the given date that haven't been evaluated yet.

    Supports multi-model predictions (returns predictions from all models).

    Args:
        session: Database session
        predicted_for: Date to find predictions for (usually today)

    Returns:
        List of unevaluated Prediction records (may be empty)
    """
    stmt = (
        select(Prediction)
        .where(Prediction.predicted_for == predicted_for)
        .where(Prediction.actual_price.is_(None))
        .order_by(Prediction.model_id.asc())  # Order by model_id for consistent logging
    )
    predictions = session.execute(stmt).scalars().all()

    if predictions:
        logger.info(
            f"Found {len(predictions)} unevaluated prediction(s) for {predicted_for}"
        )
    else:
        logger.info(f"No unevaluated predictions for {predicted_for}")

    return list(predictions)


def find_unevaluated_prediction(
    session: Session, predicted_for: date
) -> Prediction | None:
    """
    Find a prediction for the given date that hasn't been evaluated yet.

    DEPRECATED: Use find_unevaluated_predictions() for multi-model support.
    This function returns only the first unevaluated prediction.

    Args:
        session: Database session
        predicted_for: Date to find prediction for (usually today)

    Returns:
        Prediction record if found, None otherwise
    """
    predictions = find_unevaluated_predictions(session, predicted_for)
    return predictions[0] if predictions else None


def find_pending_predictions(session: Session, up_to: date) -> list[Prediction]:
    """
    Find every daily prediction due on or before ``up_to`` that is not evaluated.

    Includes predictions an earlier run could not score because their bar was
    not stored yet.

    Args:
        session: Database session
        up_to: Last ``predicted_for`` date to include (usually today)

    Returns:
        Pending predictions ordered by ``predicted_for`` and model (may be empty)
    """
    stmt = (
        select(Prediction)
        .where(Prediction.timeframe == "1d")
        .where(Prediction.predicted_for <= up_to)
        .where(Prediction.actual_price.is_(None))
        .order_by(Prediction.predicted_for.asc(), Prediction.model_id.asc())
    )
    return list(session.execute(stmt).scalars().all())


def fetch_actual_price(
    session: Session, target_date: date, symbol: str = DEFAULT_SYMBOL
) -> Decimal | None:
    """
    Fetch the close that settles a prediction made for ``target_date``.

    Daily bars are stored at their 00:00 UTC open. The predictor, running at
    07:00 UTC on day D, uses the close of the bar opened on D-1 and predicts
    the next bar, the one opened on D, which closes at 00:00 UTC on D+1 (the
    prediction's ``predicted_for``). That bar is ingested by the 06:00 UTC
    fetch-price job on D+1, before this evaluator runs.

    Args:
        session: Database session
        target_date: The prediction's ``predicted_for`` date
        symbol: Asset symbol

    Returns:
        Close of the bar opened on ``target_date - 1 day``, None if not stored
    """
    bar_open = datetime.combine(target_date - timedelta(days=1), time(0, 0), tzinfo=UTC)
    bar_close = datetime.combine(target_date, time(0, 0), tzinfo=UTC)

    stmt = (
        select(Price.close, Price.timestamp)
        .where(Price.symbol == symbol)
        .where(Price.timestamp >= bar_open)
        .where(Price.timestamp < bar_close)
        .order_by(Price.timestamp.asc())
        .limit(1)
    )
    result = session.execute(stmt).first()

    if result:
        price: Decimal
        timestamp: datetime
        price, timestamp = result
        logger.info(
            f"Fetched actual price for {target_date}: ${price} (timestamp: {timestamp})"
        )
        return price

    logger.warning(
        f"No {symbol} daily bar opened {bar_open.date()} stored yet "
        f"(needed to settle predictions for {target_date})"
    )
    return None


def calculate_direction_correct(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> bool:
    """
    Determine if the predicted direction matches the actual direction.

    Direction logic:
    - If predicted_price > price_at_prediction (predicted UP):
      → Correct if actual_price >= price_at_prediction
    - If predicted_price <= price_at_prediction (predicted DOWN/flat):
      → Correct if actual_price < price_at_prediction

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time

    Returns:
        True if direction prediction was correct, False otherwise

    Examples:
        >>> calculate_direction_correct(
        ...     Decimal("67000"), Decimal("66000"), Decimal("67500")
        ... )
        True  # Predicted UP, actual UP

        >>> calculate_direction_correct(
        ...     Decimal("67000"), Decimal("66000"), Decimal("65000")
        ... )
        False  # Predicted UP, actual DOWN

        >>> calculate_direction_correct(
        ...     Decimal("65000"), Decimal("66000"), Decimal("64000")
        ... )
        True  # Predicted DOWN, actual DOWN

        >>> calculate_direction_correct(
        ...     Decimal("65000"), Decimal("66000"), Decimal("67000")
        ... )
        False  # Predicted DOWN, actual UP
    """
    if predicted_price > price_at_prediction:
        # Predicted UP → correct if actual >= price_at_prediction
        return actual_price >= price_at_prediction
    else:
        # Predicted DOWN or flat → correct if actual < price_at_prediction
        return actual_price < price_at_prediction


class EvaluationMetrics(TypedDict):
    """The values ``update_prediction`` writes on an evaluated prediction."""

    error_abs: Decimal
    error_pct: Decimal
    direction_correct: bool
    pnl_simulated: Decimal
    pnl_long_short: Decimal
    pnl_threshold: Decimal
    pnl_realistic: Decimal


def calculate_metrics(
    prediction: Prediction, actual_price: Decimal
) -> EvaluationMetrics:
    """
    Calculate all evaluation metrics for a prediction.

    Metrics:
    - error_abs: Absolute error = |actual_price - predicted_price|
    - error_pct: Percentage error = (error_abs / actual_price) * 100
    - direction_correct: Whether predicted direction matches actual
    - pnl_simulated: Simulated profit/loss from trading strategy
    - pnl_long_short: PnL from long/short symmetric strategy
    - pnl_threshold: PnL with threshold filter (only trade if change > 1%)
    - pnl_realistic: PnL with trading fees and stop-loss

    Args:
        prediction: Prediction record to evaluate
        actual_price: Actual BTC price at evaluation time

    Returns:
        Dictionary with all calculated metrics

    Raises:
        ValueError: If actual_price is zero (defensive check)
    """
    if actual_price == 0:
        raise ValueError("actual_price cannot be zero (division by zero)")

    # Absolute error
    error_abs = abs(actual_price - prediction.predicted_price)

    # Percentage error
    error_pct = (error_abs / actual_price) * Decimal("100")

    # Direction correctness
    direction_correct = calculate_direction_correct(
        prediction.predicted_price,
        prediction.price_at_prediction,
        actual_price,
    )

    # Calculate all 4 PnL strategies
    pnl_simulated = calculate_pnl(
        prediction.predicted_price,
        prediction.price_at_prediction,
        actual_price,
    )

    pnl_long_short = calculate_pnl_long_short(
        prediction.predicted_price,
        prediction.price_at_prediction,
        actual_price,
    )

    pnl_threshold = calculate_pnl_threshold(
        prediction.predicted_price,
        prediction.price_at_prediction,
        actual_price,
    )

    pnl_realistic = calculate_pnl_realistic(
        prediction.predicted_price,
        prediction.price_at_prediction,
        actual_price,
    )

    logger.info(
        f"Calculated metrics: error_abs=${error_abs:.2f}, "
        f"error_pct={error_pct:.2f}%, "
        f"direction_correct={direction_correct}, "
        f"pnl_simulated=${pnl_simulated:.2f}, "
        f"pnl_long_short=${pnl_long_short:.2f}, "
        f"pnl_threshold=${pnl_threshold:.2f}, "
        f"pnl_realistic=${pnl_realistic:.2f}"
    )

    return {
        "error_abs": error_abs,
        "error_pct": error_pct,
        "direction_correct": direction_correct,
        "pnl_simulated": pnl_simulated,
        "pnl_long_short": pnl_long_short,
        "pnl_threshold": pnl_threshold,
        "pnl_realistic": pnl_realistic,
    }


def update_prediction(
    session: Session,
    prediction: Prediction,
    actual_price: Decimal,
    metrics: EvaluationMetrics,
) -> None:
    """
    Update a prediction record with evaluation results.

    Args:
        session: Database session
        prediction: Prediction record to update
        actual_price: Actual BTC price
        metrics: Dictionary of calculated metrics

    Raises:
        Exception: If database update fails
    """
    prediction.actual_price = actual_price
    prediction.evaluated_at = datetime.now(UTC)
    prediction.error_abs = metrics["error_abs"]
    prediction.error_pct = metrics["error_pct"]
    prediction.direction_correct = metrics["direction_correct"]
    prediction.pnl_simulated = metrics["pnl_simulated"]
    prediction.pnl_long_short = metrics["pnl_long_short"]
    prediction.pnl_threshold = metrics["pnl_threshold"]
    prediction.pnl_realistic = metrics["pnl_realistic"]

    session.commit()

    logger.info(
        f"Updated prediction #{prediction.id} with evaluation results "
        f"(actual=${actual_price}, evaluated_at={prediction.evaluated_at})"
    )


def evaluate_predictions(
    session: Session, predictions: list[Prediction], actual_price: Decimal
) -> int:
    """Score each prediction against ``actual_price``; return how many succeeded."""
    evaluated = 0
    for prediction in predictions:
        try:
            logger.info(
                f"Evaluating prediction #{prediction.id} "
                f"(model_id={prediction.model_id})"
            )
            metrics = calculate_metrics(prediction, actual_price)
            update_prediction(session, prediction, actual_price, metrics)
            evaluated += 1
        except Exception as e:
            logger.error(
                f"Failed to evaluate prediction #{prediction.id}: {e}",
                exc_info=True,
            )
            # Continue with other predictions
    return evaluated


def main(today: date | None = None) -> int:
    """
    Main entry point for the evaluator job.

    Evaluates ALL pending daily predictions due up to ``today`` (supports
    multi-model), each against the bar it predicted.

    Args:
        today: Date the job runs on (defaults to the current date)

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting daily evaluator job")

    session = SessionLocal()

    try:
        today = today or utc_today()
        logger.info(f"Evaluating pending predictions due up to {today}")

        predictions = find_pending_predictions(session, today)

        if not predictions:
            logger.info("No predictions to evaluate, exiting successfully")
            return 0

        logger.info(f"Found {len(predictions)} pending prediction(s)")
        evaluated = 0
        waiting = 0

        for predicted_for, group in groupby(predictions, key=lambda p: p.predicted_for):
            due = list(group)
            actual_price = fetch_actual_price(session, predicted_for)

            if actual_price is None:
                waiting += len(due)
                logger.info(
                    f"Skipping {len(due)} prediction(s) for {predicted_for}: "
                    f"settling bar not available yet, they stay pending"
                )
                continue

            evaluated += evaluate_predictions(session, due, actual_price)

        logger.info(
            f"Evaluator job completed: {evaluated} prediction(s) evaluated, "
            f"{waiting} waiting for their bar"
        )
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
