"""
Weekly predictor job - predicts BTC price 7 days ahead.

This job:
1. Loads the active ML model from the database
2. Fetches recent historical DAILY closes and volumes (not hourly)
3. Builds the return features and predicts the 7-day log return; the stored
   price is ``last close * exp(predicted return)``
4. Stores the prediction with timeframe='1w' for later evaluation

Entry point: python -m weekly.predictor
Runs: Every Monday at 7am UTC (Railway cron: 0 7 * * 1)
"""

import logging
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, Model, Prediction, Price
from shared.features import price_from_return, required_history_days
from workers.daily.predictor import (
    get_recent_series,
    prepare_features,
    require_return_model,
)
from workers.weekly.models import BaseModel, LinearRegressionModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_active_model(session: Session) -> tuple[Model, BaseModel]:
    """
    Load the active weekly (timeframe='1w') model from the database.

    Scoped to timeframe='1w' so this never picks up the active daily
    model -- a '1d' and a '1w' model can be active at the same time (see
    ix_models_one_active_version_per_name_timeframe).

    Args:
        session: Database session

    Returns:
        Tuple of (Model record, deserialized BaseModel instance)

    Raises:
        ValueError: If no active weekly model found
        RuntimeError: If deserialization fails
    """
    stmt = select(Model).where(
        Model.is_active == True,  # noqa: E712
        Model.timeframe == "1w",
    )
    model_record = session.execute(stmt).scalars().first()

    if model_record is None:
        raise ValueError("No active weekly model found in database")

    # Deserialize based on model name
    try:
        if model_record.name.startswith("linear"):
            model_instance = LinearRegressionModel.deserialize(model_record.artifact)
        else:
            raise ValueError(f"Unknown model type: {model_record.name}")
    except Exception as e:
        raise RuntimeError(f"Failed to deserialize model: {e}") from e

    logger.info(
        f"Loaded active model: {model_record.name} v{model_record.version} "
        f"(trained {model_record.trained_at})"
    )

    return model_record, model_instance


def check_existing_prediction(
    session: Session, predicted_for: date, timeframe: str
) -> bool:
    """
    Check if a prediction already exists for the given date and timeframe.

    Args:
        session: Database session
        predicted_for: Date to check
        timeframe: Timeframe to check ('1d', '1w')

    Returns:
        True if prediction exists, False otherwise
    """
    stmt = select(Prediction).where(
        Prediction.predicted_for == predicted_for,
        Prediction.timeframe == timeframe,
    )
    existing = session.execute(stmt).scalar_one_or_none()

    return existing is not None


def save_prediction(
    session: Session,
    model_id: int,
    predicted_for: date,
    current_price: Decimal,
    predicted_price: float,
    timeframe: str,
) -> Prediction:
    """
    Save a new prediction to the database.

    Args:
        session: Database session
        model_id: ID of the model used for prediction
        predicted_for: Date being predicted (7 days ahead)
        current_price: BTC price at prediction time
        predicted_price: Predicted BTC price
        timeframe: Prediction timeframe ('1w')

    Returns:
        Created Prediction record
    """
    prediction = Prediction(
        model_id=model_id,
        predicted_for=predicted_for,
        timeframe=timeframe,
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
        f"Saved weekly prediction #{prediction.id}: "
        f"for={predicted_for}, predicted=${predicted_price:.2f}, "
        f"current=${current_price}, timeframe={timeframe}"
    )

    return prediction


def main() -> int:
    """
    Main entry point for the weekly predictor job.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("Starting weekly predictor job")

    session = SessionLocal()

    try:
        # Calculate date 7 days ahead (next Monday in ISO week)
        today = date.today()
        days_ahead = 7
        predicted_date = today + timedelta(days=days_ahead)
        logger.info(f"Predicting for date: {predicted_date} (7 days ahead)")

        # Check if prediction already exists (idempotency)
        if check_existing_prediction(session, predicted_date, timeframe="1w"):
            logger.warning(
                f"Weekly prediction for {predicted_date} already exists, "
                f"skipping (idempotent)"
            )
            return 0

        # Load active model
        model_record, model_instance = get_active_model(session)

        require_return_model(model_record)

        # Get window_days from model params
        window_days = model_record.params.get("window_days", 30)
        logger.info(f"Model requires {window_days} days of returns")

        # Fetch daily closes and volumes (not hourly)
        series = get_recent_series(session, required_history_days(window_days))

        # Prepare features
        X = prepare_features(series, window_days)

        # Get current price (latest from prices)
        current_price_stmt = (
            select(Price.close)
            .where(Price.symbol == DEFAULT_SYMBOL)
            .order_by(Price.timestamp.desc())
            .limit(1)
        )
        current_price = session.execute(current_price_stmt).scalar_one()
        logger.info(f"Current BTC price: ${current_price}")

        # The model predicts the 7-day log return; the price follows from it
        predicted_return = model_instance.predict(X)
        predicted_price = price_from_return(current_price, predicted_return)
        logger.info(
            f"Model predicted 7-day return {predicted_return:+.4%}, "
            f"price: ${predicted_price:.2f}"
        )

        # Save prediction with timeframe='1w'
        save_prediction(
            session=session,
            model_id=model_record.id,
            predicted_for=predicted_date,
            current_price=current_price,
            predicted_price=predicted_price,
            timeframe="1w",
        )

        logger.info("Weekly predictor job completed successfully")
        return 0

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
        session.close()


if __name__ == "__main__":
    sys.exit(main())
