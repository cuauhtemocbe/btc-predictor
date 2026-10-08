"""Daily evaluator job: settles the predictions that are due.

Scores every pending daily prediction against the close of the bar it predicted
(the bar opened the day before ``predicted_for``, which closes at 00:00 UTC on
that date) and stores the errors, direction and simulated PnL. A prediction
whose bar is not stored stays pending for a later run.

Entry point: ``python -m workers.daily.evaluator``, also run by ``workers.daily``.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def find_pending_predictions(session: Session, up_to: date) -> list[Prediction]:
    """Every unevaluated daily prediction with ``predicted_for`` on or before ``up_to``.

    Includes those an earlier run could not score because their bar was missing.
    Ordered by ``predicted_for`` and model.
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
    """Close that settles a prediction made for ``target_date``.

    Daily bars are stored at their 00:00 UTC open. The predictor, at 00:10 UTC on D,
    predicts the bar opened on D, which closes at 00:00 UTC on D+1 (``predicted_for``);
    the 00:05 UTC fetch-price job ingests it on D+1, before this evaluator runs.

    Returns:
        Close of the bar opened on ``target_date - 1 day``, or None if not stored.
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
    """Whether the predicted direction matched the actual one.

    Predicted UP (``predicted_price > price_at_prediction``) is correct if
    ``actual_price >= price_at_prediction``; predicted DOWN or flat is correct if
    ``actual_price < price_at_prediction``.
    """
    if predicted_price > price_at_prediction:
        return actual_price >= price_at_prediction
    else:
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
    """Error, direction and the four simulated PnLs of a prediction.

    ``error_pct`` is ``|actual - predicted| / actual * 100``. The PnLs come from
    ``shared.utils`` (long-only, long/short, threshold, realistic).

    Raises:
        ValueError: If ``actual_price`` is zero.
    """
    if actual_price == 0:
        raise ValueError("actual_price cannot be zero (division by zero)")

    error_abs = abs(actual_price - prediction.predicted_price)

    error_pct = (error_abs / actual_price) * Decimal("100")

    direction_correct = calculate_direction_correct(
        prediction.predicted_price,
        prediction.price_at_prediction,
        actual_price,
    )

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
    """Write ``actual_price`` and ``metrics`` on the prediction and commit (phase 2)."""
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
    return evaluated


def main(today: date | None = None) -> int:
    """Run the evaluator job over every pending prediction due up to ``today``.

    Args:
        today: Day the job runs on; defaults to ``utc_today()``.

    Returns:
        0 on success (predictions without a bar stay pending), 1 on failure.
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
