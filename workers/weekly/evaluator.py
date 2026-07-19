"""
Weekly evaluator job - evaluates weekly BTC price predictions 7 days later.

This job:
1. Finds weekly predictions (timeframe='1w') for today that haven't been evaluated
2. Fetches today's 7am BTC close price from the database
3. Calculates error metrics (absolute, percentage, direction correctness)
4. Calculates simulated PnL based on prediction strategy (same formulas as daily)
5. Updates the prediction record with evaluation results

Entry point: python -m workers.weekly.evaluator
Runs: Every Monday (as part of weekly job orchestration)
"""

import logging
import sys
from datetime import UTC, date, datetime, time
from decimal import Decimal

from shared.db.database import SessionLocal
from shared.db.models import BtcPrice, Prediction
from shared.utils import (
    calculate_pnl,
    calculate_pnl_long_short,
    calculate_pnl_realistic,
    calculate_pnl_threshold,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def find_unevaluated_weekly_prediction(
    session: Session, predicted_for: date
) -> Prediction | None:
    """
    Find a weekly prediction for the given date that hasn't been evaluated yet.

    Args:
        session: Database session
        predicted_for: Date to find prediction for (today = 7 days after prediction)

    Returns:
        Prediction record if found, None otherwise
    """
    stmt = (
        select(Prediction)
        .where(Prediction.predicted_for == predicted_for)
        .where(Prediction.timeframe == "1w")
        .where(Prediction.actual_price.is_(None))
        .order_by(Prediction.predicted_at.desc())  # Most recent if multiple
    )
    prediction = session.execute(stmt).scalars().first()

    if prediction:
        logger.info(
            f"Found unevaluated weekly prediction #{prediction.id} for {predicted_for}"
        )
    else:
        logger.info(f"No unevaluated weekly predictions for {predicted_for}")

    return prediction


def fetch_actual_price(session: Session, target_date: date) -> Decimal | None:
    """
    Fetch the 7am BTC close price for the given date.

    Args:
        session: Database session
        target_date: Date to fetch price for

    Returns:
        Close price if found, None otherwise
    """
    # Construct 7am timestamp in UTC
    target_datetime = datetime.combine(target_date, time(7, 0), tzinfo=UTC)

    stmt = select(BtcPrice.close).where(BtcPrice.timestamp == target_datetime)
    price = session.execute(stmt).scalar_one_or_none()

    if price:
        logger.info(f"Fetched actual price for {target_date} 7am: ${price}")
    else:
        logger.warning(
            f"No price data available for {target_date} 7am (will retry next Monday)"
        )

    return price


def calculate_direction_correct(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> bool:
    """
    Determine if the predicted direction matches the actual direction.

    Direction logic (same as daily):
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
    """
    if predicted_price > price_at_prediction:
        # Predicted UP → correct if actual >= price_at_prediction
        return actual_price >= price_at_prediction
    else:
        # Predicted DOWN or flat → correct if actual < price_at_prediction
        return actual_price < price_at_prediction


def calculate_metrics(
    prediction: Prediction, actual_price: Decimal
) -> dict[str, Decimal | bool]:
    """
    Calculate all evaluation metrics for a weekly prediction.

    Metrics (same as daily - PnL formulas are timeframe-agnostic):
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

    # Calculate all 4 PnL strategies (same formulas as daily)
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
        f"Calculated weekly metrics: error_abs=${error_abs:.2f}, "
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
    metrics: dict[str, Decimal | bool],
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
        f"Updated weekly prediction #{prediction.id} with evaluation results "
        f"(actual=${actual_price}, evaluated_at={prediction.evaluated_at})"
    )


def main() -> int:
    """
    Main entry point for the weekly evaluator job.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting weekly evaluator job")

    session = SessionLocal()

    try:
        # Evaluate weekly prediction for today (7 days after it was made)
        today = date.today()
        logger.info(f"Evaluating weekly prediction for date: {today}")

        # Find unevaluated weekly prediction
        prediction = find_unevaluated_weekly_prediction(session, today)

        if prediction is None:
            logger.info("No weekly predictions to evaluate, exiting successfully")
            return 0

        # Fetch actual price (7am close)
        actual_price = fetch_actual_price(session, today)

        if actual_price is None:
            logger.info(
                "Actual price not available yet, skipping evaluation "
                "(will retry next Monday)"
            )
            return 0

        # Calculate metrics (same formulas as daily, timeframe-agnostic)
        metrics = calculate_metrics(prediction, actual_price)

        # Update prediction record
        update_prediction(session, prediction, actual_price, metrics)

        logger.info("Weekly evaluator job completed successfully")
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
