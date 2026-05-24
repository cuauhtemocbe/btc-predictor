"""
Utility functions for walk-forward backtesting.

Functions:
- fetch_training_data: Fetch rolling training window from btc_prices
- generate_prediction: Train model and generate prediction
- save_backtest_result: Save backtest result to database
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.database import SessionLocal
from shared.db.models import BacktestResult, BtcPrice
from workers.daily.models.linear import LinearRegressionModel


def fetch_training_data(
    end_date: date, window_days: int = 30, db: Session | None = None
) -> pd.DataFrame | None:
    """
    Fetch rolling training window from btc_prices table with daily aggregation.

    Uses DATE_TRUNC to aggregate 4-hour data (6 records/day) to daily (1 record/day).
    Takes the latest close price for each day.

    Args:
        end_date: Last date to include in training data
        window_days: Number of days to fetch (default 30)
        db: Database session (optional, will create if None)

    Returns:
        DataFrame with columns: timestamp, close (aggregated daily)
        None if insufficient data

    Example:
        >>> df = fetch_training_data(date(2024, 5, 15), window_days=30)
        >>> print(len(df))  # Should be ~30 rows (30 days, daily aggregated)
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # Calculate start date for training window
        start_date = end_date - timedelta(days=window_days)

        # Subquery: Get the latest timestamp for each day
        from datetime import datetime, timezone as tz
        from sqlalchemy import func

        # Convert dates to datetime with timezone for proper comparison
        start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=tz.utc)
        end_datetime = datetime.combine(end_date, datetime.min.time()).replace(tzinfo=tz.utc) + timedelta(days=1)

        latest_per_day = (
            select(
                func.date_trunc("day", BtcPrice.timestamp).label("day"),
                func.max(BtcPrice.timestamp).label("latest_timestamp"),
            )
            .where(BtcPrice.timestamp >= start_datetime)
            .where(BtcPrice.timestamp < end_datetime)
            .group_by("day")
            .order_by(func.date_trunc("day", BtcPrice.timestamp))
            .subquery()
        )

        # Main query: Join to get all OHLCV data for the latest timestamp each day
        stmt = (
            select(BtcPrice)
            .join(
                latest_per_day,
                BtcPrice.timestamp == latest_per_day.c.latest_timestamp,
            )
            .order_by(latest_per_day.c.day)
        )

        results = db.execute(stmt).scalars().all()

        if not results:
            return None

        # Convert to DataFrame
        data = []
        for price in results:
            data.append(
                {
                    "timestamp": price.timestamp,
                    "open": float(price.open),
                    "high": float(price.high),
                    "low": float(price.low),
                    "close": float(price.close),
                    "volume": float(price.volume),
                }
            )

        df = pd.DataFrame(data)

        # Validate we have enough data (daily aggregated)
        # Expect at least window_days of daily data
        min_expected_rows = window_days
        if len(df) < min_expected_rows:
            return None

        return df

    finally:
        if close_db:
            db.close()


def generate_prediction(
    training_data: pd.DataFrame,
    prediction_date: date,
    price_at_prediction: Decimal,
    db: Session | None = None,
) -> tuple[Decimal, dict]:
    """
    Train model and generate next-day price prediction.

    Args:
        training_data: DataFrame from fetch_training_data with daily OHLCV data
        prediction_date: Date to predict for
        price_at_prediction: Current BTC price at prediction time
        db: Database session (optional)

    Returns:
        Tuple of (predicted_price, model_params)
        model_params is a dict with training metadata

    Raises:
        ValueError: If training fails
    """
    import numpy as np

    # Initialize model
    window_days = 30
    model = LinearRegressionModel(window_days=window_days)

    # Prepare training data: data already comes in daily frequency
    # Sort by timestamp and extract close prices
    training_data = training_data.sort_values("timestamp")
    training_data["date"] = pd.to_datetime(training_data["timestamp"]).dt.date

    # Convert close prices to numpy array
    close_prices = training_data["close"].values

    # Check if we have enough data
    if len(close_prices) < window_days + 1:
        raise ValueError(
            f"Insufficient data for training: need at least {window_days + 1} "
            f"daily prices, got {len(close_prices)}"
        )

    # Create sliding windows for training
    # For window_days=30, we need 30 prices to predict the 31st
    # If we have 60 prices, we can create 30 training samples
    X_list = []
    y_list = []

    for i in range(len(close_prices) - window_days):
        X_list.append(close_prices[i : i + window_days])
        y_list.append(close_prices[i + window_days])

    X = np.array(X_list, dtype=np.float64)
    y = np.array(y_list, dtype=np.float64)

    # Train model
    try:
        model.train(X, y)
    except Exception as e:
        raise ValueError(f"Model training failed: {e!s}") from e

    # Generate prediction: use last window_days prices
    X_pred = close_prices[-window_days:].reshape(1, -1).astype(np.float64)

    try:
        predicted_price = model.predict(X_pred)
    except Exception as e:
        raise ValueError(f"Model prediction failed: {e!s}") from e

    # Extract model parameters for storage
    model_params = {
        "model_name": "linear_v1",
        "window_days": window_days,
        "train_from": training_data["date"].min().strftime("%Y-%m-%d"),
        "train_to": training_data["date"].max().strftime("%Y-%m-%d"),
        "training_samples": len(X),
        "training_days": len(close_prices),
    }

    return Decimal(str(predicted_price)), model_params


def save_backtest_result(
    backtest_run_id: UUID,
    predicted_for: date,
    predicted_at: datetime,
    price_at_prediction: Decimal,
    predicted_price: Decimal,
    actual_price: Decimal,
    pnl_simple: Decimal | None,
    pnl_long_short: Decimal | None,
    pnl_threshold: Decimal | None,
    pnl_realistic: Decimal | None,
    model_params: dict,
    db: Session | None = None,
) -> BacktestResult:
    """
    Save backtest result to database.

    Args:
        backtest_run_id: UUID identifying this backtest run
        predicted_for: Date being predicted
        predicted_at: Timestamp when prediction was made (simulated)
        price_at_prediction: BTC price at prediction time
        predicted_price: Predicted BTC price
        actual_price: Actual BTC price for that day
        pnl_simple: PnL from simple strategy
        pnl_long_short: PnL from long/short strategy
        pnl_threshold: PnL from threshold strategy
        pnl_realistic: PnL from realistic strategy
        model_params: Model training parameters dict
        db: Database session (optional, will create if None)

    Returns:
        BacktestResult instance (committed to database)

    Raises:
        Exception: If database insert fails
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        result = BacktestResult(
            backtest_run_id=backtest_run_id,
            predicted_for=predicted_for,
            predicted_at=predicted_at,
            price_at_prediction=price_at_prediction,
            predicted_price=predicted_price,
            actual_price=actual_price,
            pnl_simple=pnl_simple,
            pnl_long_short=pnl_long_short,
            pnl_threshold=pnl_threshold,
            pnl_realistic=pnl_realistic,
            model_params=model_params,
        )

        db.add(result)
        db.commit()
        db.refresh(result)

        return result

    except Exception as e:
        db.rollback()
        raise Exception(f"Failed to save backtest result: {e!s}") from e
    finally:
        if close_db:
            db.close()


def get_actual_price_for_date(
    target_date: date, db: Session | None = None
) -> Decimal | None:
    """
    Get actual BTC closing price for a specific date.

    Fetches the last closing price for the target date from btc_prices.

    Args:
        target_date: Date to get price for
        db: Database session (optional, will create if None)

    Returns:
        Decimal closing price, or None if no data for that date
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        from datetime import datetime, timezone as tz

        # Convert date to datetime with UTC timezone for comparison
        start_datetime = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=tz.utc)
        end_datetime = start_datetime + timedelta(days=1)

        # Get last price of the day
        stmt = (
            select(BtcPrice)
            .where(BtcPrice.timestamp >= start_datetime)
            .where(BtcPrice.timestamp < end_datetime)
            .order_by(BtcPrice.timestamp.desc())
            .limit(1)
        )

        result = db.execute(stmt).scalar_one_or_none()

        if result is None:
            return None

        return result.close

    finally:
        if close_db:
            db.close()
