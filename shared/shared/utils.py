"""
Utility functions for BTC Predictor.

Functions:
- calculate_pnl: Calculate simulated profit/loss from prediction strategy
- calculate_pnl_long_short: Calculate PnL with long/short symmetric strategy
- calculate_pnl_threshold: Calculate PnL with threshold filter
- calculate_pnl_realistic: Calculate PnL with trading fees and stop-loss
- split_train_validation: Split time series data into train/validation sets
- calculate_mape: Calculate Mean Absolute Percentage Error

Model Metrics Functions (for dashboard):
- calculate_accuracy: Calculate % of correct direction predictions for a model
- calculate_model_mape: Calculate MAPE from database predictions for a model
- calculate_total_pnl: Calculate total PnL for a model
- calculate_win_rate: Calculate % of positive PnL predictions for a model
- calculate_sharpe_ratio: Calculate Sharpe ratio for a model
- calculate_max_drawdown: Calculate maximum drawdown for a model
- get_cumulative_pnl: Get daily cumulative PnL time series for a model
- get_all_models_metrics: Get metrics for all models in one call
"""

from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

# Prediction.timeframe values, and the one used when a caller doesn't name
# one explicitly. Applied consistently across every metric function below
# and every API endpoint that doesn't require an explicit timeframe query
# param -- see issue #67.
SUPPORTED_TIMEFRAMES = ("1h", "1d", "1w")
DEFAULT_TIMEFRAME = "1d"


def calculate_pnl(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> Decimal:
    """
    Calculate simulated profit/loss (PnL) from a prediction-based trading strategy.

    Strategy:
    - If predicted_price > price_at_prediction (predicted UP):
      → Go long 1 BTC at price_at_prediction
      → PnL = actual_price - price_at_prediction
    - Else (predicted DOWN or flat):
      → Stay in cash (no trade)
      → PnL = 0

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time

    Returns:
        Simulated PnL in USDT (positive = profit, negative = loss, 0 = no trade)

    Examples:
        >>> calculate_pnl(Decimal("67000"), Decimal("66000"), Decimal("67500"))
        Decimal('1500.00')  # Predicted UP, actual UP → profit

        >>> calculate_pnl(Decimal("67000"), Decimal("66000"), Decimal("65000"))
        Decimal('-1000.00')  # Predicted UP, actual DOWN → loss

        >>> calculate_pnl(Decimal("65000"), Decimal("66000"), Decimal("64000"))
        Decimal('0.00')  # Predicted DOWN → no trade
    """
    # If predicted UP (prediction higher than current), go long
    if predicted_price > price_at_prediction:
        pnl = actual_price - price_at_prediction
    else:
        # Predicted DOWN or flat → stay in cash
        pnl = Decimal("0.00")

    return pnl


def calculate_pnl_long_short(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> Decimal:
    """
    Calculate PnL from long/short symmetric trading strategy.

    Strategy:
    - If predicted_price > price_at_prediction (predicted UP):
      → Go long 1 BTC at price_at_prediction
      → PnL = actual_price - price_at_prediction
    - Else (predicted DOWN):
      → Go short 1 BTC at price_at_prediction
      → PnL = price_at_prediction - actual_price

    This strategy profits from correct predictions in BOTH directions.

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time

    Returns:
        PnL in USDT (positive = profit, negative = loss)
    """
    if predicted_price > price_at_prediction:
        # Long position
        pnl = actual_price - price_at_prediction
    else:
        # Short position
        pnl = price_at_prediction - actual_price

    return pnl


def calculate_pnl_threshold(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
    threshold: Decimal = Decimal("1.0"),
) -> Decimal:
    """
    Calculate PnL with threshold filter: only trade if predicted change > threshold %.

    Strategy:
    - Calculate predicted change percentage
    - If abs(change) < threshold → no trade, PnL = 0
    - Else → apply long/short symmetric strategy

    This avoids trading on weak signals and reduces transaction costs.

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time
        threshold: Minimum predicted change % to trigger trade (default 1.0%)

    Returns:
        PnL in USDT (positive = profit, negative = loss, 0 = no trade)
    """
    # Calculate predicted change percentage
    change_pct = abs(
        (predicted_price - price_at_prediction) / price_at_prediction * 100
    )

    # If change below threshold, no trade
    if change_pct < threshold:
        return Decimal("0.00")

    # Otherwise, use long/short symmetric strategy
    return calculate_pnl_long_short(predicted_price, price_at_prediction, actual_price)


def calculate_pnl_realistic(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
    fee_pct: Decimal = Decimal("0.1"),
    stop_loss_pct: Decimal = Decimal("2.0"),
) -> Decimal:
    """
    Calculate PnL with realistic trading conditions: fees and stop-loss.

    Strategy:
    - Apply long/short symmetric strategy
    - Deduct trading fees: fee_pct * price_at_prediction * 2 (entry + exit)
    - Apply stop-loss: cap loss at stop_loss_pct * price_at_prediction

    This simulates real trading with transaction costs and risk management.

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time
        fee_pct: Trading fee percentage per trade (default 0.1%)
        stop_loss_pct: Maximum loss percentage before stop-loss triggers (default 2%)

    Returns:
        PnL in USDT after fees and stop-loss (positive = profit, negative = loss)
    """
    # Calculate gross PnL using long/short symmetric strategy
    gross_pnl = calculate_pnl_long_short(
        predicted_price, price_at_prediction, actual_price
    )

    # Calculate trading fees (entry + exit = 2 trades)
    fees = price_at_prediction * (fee_pct / 100) * 2

    # Calculate maximum loss (stop-loss limit)
    max_loss = price_at_prediction * (stop_loss_pct / 100)

    # Apply stop-loss: cap gross loss at max_loss
    if gross_pnl < -max_loss:
        gross_pnl = -max_loss

    # Net PnL after fees
    net_pnl = gross_pnl - fees

    return net_pnl


def split_train_validation(
    prices: np.ndarray,
    train_pct: float = 0.7,
    val_pct: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Split time series price data into training and validation sets.

    Uses 70% for training, 20% for validation, and discards remaining 10%
    (buffer for time series continuity).

    Args:
        prices: 1D array of historical prices (chronological order)
        train_pct: Percentage of data for training (default 0.7 = 70%)
        val_pct: Percentage of data for validation (default 0.2 = 20%)

    Returns:
        Tuple of (train_data, val_data) as numpy arrays

    Raises:
        ValueError: If train_pct + val_pct > 1.0 or if not enough data

    Examples:
        >>> prices = np.array([50000, 51000, 52000, ..., 67000])  # 100 days
        >>> train, val = split_train_validation(prices)
        >>> len(train)  # 70 days
        70
        >>> len(val)  # 20 days
        20
    """
    if train_pct + val_pct > 1.0:
        raise ValueError(
            f"train_pct ({train_pct}) + val_pct ({val_pct}) must be <= 1.0"
        )

    n = len(prices)
    if n < 10:
        raise ValueError(f"Need at least 10 data points, got {n}")

    # Calculate split indices
    train_size = int(n * train_pct)
    val_size = int(n * val_pct)

    if train_size < 1 or val_size < 1:
        raise ValueError(
            f"Not enough data: train_size={train_size}, val_size={val_size}"
        )

    # Split chronologically
    train_data = prices[:train_size]
    val_data = prices[train_size : train_size + val_size]
    # Buffer (remaining 10%) is discarded

    return train_data, val_data


def calculate_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Calculate Mean Absolute Percentage Error (MAPE).

    MAPE = mean(|y_true - y_pred| / |y_true|) * 100

    Args:
        y_true: Array of true values
        y_pred: Array of predicted values

    Returns:
        MAPE as percentage (0-100 scale)

    Raises:
        ValueError: If arrays have different lengths or contain zeros

    Examples:
        >>> y_true = np.array([50000, 51000, 52000])
        >>> y_pred = np.array([50500, 50800, 52100])
        >>> calculate_mape(y_true, y_pred)
        1.05  # ~1% average error
    """
    if len(y_true) != len(y_pred):
        raise ValueError(
            f"Arrays must have same length: {len(y_true)} != {len(y_pred)}"
        )

    if len(y_true) == 0:
        raise ValueError("Cannot calculate MAPE on empty arrays")

    # Avoid division by zero
    if np.any(y_true == 0):
        raise ValueError("y_true contains zeros, cannot calculate MAPE")

    # Calculate absolute percentage errors
    abs_errors = np.abs((y_true - y_pred) / y_true)

    # Return mean as percentage
    mape = float(np.mean(abs_errors) * 100)

    return mape


# ============================================================================
# Model Metrics Functions for Dashboard
# ============================================================================


def calculate_accuracy(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate prediction accuracy for a model (% of correct direction predictions).

    Accuracy = COUNT(*) WHERE direction_correct = true / COUNT(*)

    Args:
        db: Database session
        model_id: Model ID to calculate accuracy for
        start_date: Optional start date filter
        end_date: Optional end date filter
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            predictions across every timeframe are mixed together --
            callers that want daily/weekly separated must pass this
            explicitly (see DEFAULT_TIMEFRAME for the API-level default).

    Returns:
        Accuracy as decimal (0.0-1.0), or None if no evaluated predictions

    Examples:
        >>> calculate_accuracy(db, model_id=1, timeframe="1d")
        0.65  # 65% accuracy
    """
    from shared.db.models import Prediction

    # Base query: only evaluated predictions (actual_price IS NOT NULL)
    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters if provided
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Count total and correct predictions
    total_count = query.count()
    if total_count == 0:
        return None

    correct_count = query.filter(Prediction.direction_correct.is_(True)).count()

    accuracy = correct_count / total_count
    return accuracy


def calculate_model_mape(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate Mean Absolute Percentage Error (MAPE) for a model from database.

    MAPE = AVG(ABS((actual_price - predicted_price) / actual_price)) * 100

    Args:
        db: Database session
        model_id: Model ID to calculate MAPE for
        start_date: Optional start date filter
        end_date: Optional end date filter
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together.

    Returns:
        MAPE as percentage (0-100 scale), or None if no evaluated predictions

    Examples:
        >>> calculate_model_mape(db, model_id=1, timeframe="1d")
        2.5  # 2.5% average error
    """
    from shared.db.models import Prediction

    # Base query: only evaluated predictions
    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Get all predictions
    predictions = query.all()
    if not predictions:
        return None

    # Calculate MAPE manually
    errors = []
    for pred in predictions:
        if pred.actual_price and pred.actual_price != 0:
            error = abs((pred.actual_price - pred.predicted_price) / pred.actual_price)
            errors.append(float(error))

    if not errors:
        return None

    mape = np.mean(errors) * 100
    return float(mape)


def calculate_total_pnl(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate total PnL for a model (sum of all PnL values).

    Total PnL = SUM(pnl_simulated)

    Args:
        db: Database session
        model_id: Model ID to calculate total PnL for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to sum (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together.

    Returns:
        Total PnL in USDT, or None if no evaluated predictions

    Examples:
        >>> calculate_total_pnl(db, model_id=1, timeframe="1d")
        1200.50  # Total profit of $1,200.50
    """
    from shared.db.models import Prediction

    # Base query
    query = db.query(func.sum(getattr(Prediction, pnl_column))).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Execute query
    result = query.scalar()
    if result is None:
        return None

    return float(result)


def calculate_win_rate(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate win rate for a model (% of predictions with positive PnL).

    Win Rate = COUNT(*) WHERE pnl > 0 / COUNT(*)

    Args:
        db: Database session
        model_id: Model ID to calculate win rate for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together.

    Returns:
        Win rate as decimal (0.0-1.0), or None if no evaluated predictions

    Examples:
        >>> calculate_win_rate(db, model_id=1, timeframe="1d")
        0.60  # 60% win rate
    """
    from shared.db.models import Prediction

    # Base query
    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Count total and winning predictions
    total_count = query.count()
    if total_count == 0:
        return None

    win_count = query.filter(getattr(Prediction, pnl_column) > 0).count()

    win_rate = win_count / total_count
    return win_rate


def calculate_sharpe_ratio(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    risk_free_rate: float = 0.0,
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate annualized Sharpe ratio for a model.

    Sharpe Ratio = (MEAN(daily_returns) - risk_free_rate)
                   / STDEV(daily_returns) * sqrt(365)

    Daily returns = pnl / price_at_prediction

    Args:
        db: Database session
        model_id: Model ID to calculate Sharpe ratio for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        risk_free_rate: Annual risk-free rate (default: 0.0)
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together -- combining daily and
            weekly returns would distort both the mean and the stdev.

    Returns:
        Annualized Sharpe ratio, or None if insufficient data

    Examples:
        >>> calculate_sharpe_ratio(db, model_id=1, timeframe="1d")
        1.25  # Sharpe ratio of 1.25
    """
    from shared.db.models import Prediction

    # Base query
    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Get all predictions
    predictions = query.order_by(Prediction.predicted_for).all()
    if len(predictions) < 2:
        return None  # Need at least 2 data points for stdev

    # Calculate daily returns
    returns = []
    for pred in predictions:
        pnl = getattr(pred, pnl_column)
        if pnl is not None and pred.price_at_prediction > 0:
            daily_return = float(pnl) / float(pred.price_at_prediction)
            returns.append(daily_return)

    if len(returns) < 2:
        return None

    # Calculate Sharpe ratio
    mean_return = np.mean(returns)
    std_return = np.std(returns, ddof=1)  # Sample standard deviation

    if std_return == 0:
        return None  # Avoid division by zero

    # Annualize (assuming daily predictions)
    sharpe = (mean_return - risk_free_rate / 365) / std_return * np.sqrt(365)

    return float(sharpe)


def calculate_max_drawdown(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate maximum drawdown for a model (largest cumulative loss).

    Max Drawdown = MIN(cumulative_pnl - running_max(cumulative_pnl))

    Args:
        db: Database session
        model_id: Model ID to calculate max drawdown for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together in one cumulative series.

    Returns:
        Maximum drawdown in USDT (negative value), or None if no data

    Examples:
        >>> calculate_max_drawdown(db, model_id=1, timeframe="1d")
        -450.0  # Max drawdown of -$450
    """
    from shared.db.models import Prediction

    # Base query
    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Get all predictions ordered by date
    predictions = query.order_by(Prediction.predicted_for).all()
    if not predictions:
        return None

    # Calculate cumulative PnL
    cumulative_pnl = []
    cumsum = 0.0
    for pred in predictions:
        pnl = getattr(pred, pnl_column)
        if pnl is not None:
            cumsum += float(pnl)
            cumulative_pnl.append(cumsum)

    if not cumulative_pnl:
        return None

    # Calculate running maximum and drawdown
    cumulative_pnl_arr = np.array(cumulative_pnl)
    running_max = np.maximum.accumulate(cumulative_pnl_arr)
    drawdown = cumulative_pnl_arr - running_max

    max_drawdown = float(np.min(drawdown))

    return max_drawdown


def get_cumulative_pnl(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get daily cumulative PnL time series for a model (for chart visualization).

    Returns list of {date, cumulative_pnl} dictionaries ordered by date.

    Args:
        db: Database session
        model_id: Model ID to get cumulative PnL for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            daily and weekly records are combined into one series.

    Returns:
        List of {"date": "YYYY-MM-DD", "cumulative_pnl": float} dictionaries

    Examples:
        >>> get_cumulative_pnl(db, model_id=1, timeframe="1d")
        [
            {"date": "2024-05-01", "cumulative_pnl": 100.0},
            {"date": "2024-05-02", "cumulative_pnl": 250.0},
            ...
        ]
    """
    from shared.db.models import Prediction

    # Base query
    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    # Get all predictions ordered by date
    predictions = query.order_by(Prediction.predicted_for).all()

    # Calculate cumulative PnL
    result = []
    cumsum = 0.0
    for pred in predictions:
        pnl = getattr(pred, pnl_column)
        if pnl is not None:
            cumsum += float(pnl)
            result.append(
                {
                    "date": pred.predicted_for.isoformat(),
                    "cumulative_pnl": round(cumsum, 2),
                }
            )

    return result


def get_all_models_metrics(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get performance metrics for all models in one call.

    Returns list of dictionaries with model metadata and calculated metrics.

    Args:
        db: Database session
        start_date: Optional start date filter for metrics calculation
        end_date: Optional end date filter for metrics calculation
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together for every metric below.

    Returns:
        List of dictionaries with structure:
        {
            "id": int,
            "name": str,
            "version": str,
            "is_active": bool,
            "trained_at": datetime,
            "predictions_count": int,
            "accuracy": float | None,
            "avg_error_pct": float | None,
            "total_pnl": float | None,
            "win_rate": float | None,
            "sharpe_ratio": float | None,
            "max_drawdown": float | None,
        }

    Examples:
        >>> get_all_models_metrics(db)
        [
            {
                "id": 1,
                "name": "linear_v1",
                "version": "1.0.0",
                "accuracy": 0.65,
                "total_pnl": 1200.50,
                ...
            },
            ...
        ]
    """
    from shared.db.models import Model, Prediction

    # Get all models
    models = db.query(Model).all()

    results = []
    for model in models:
        # Count evaluated predictions
        query = db.query(Prediction).filter(
            Prediction.model_id == model.id, Prediction.actual_price.isnot(None)
        )

        if start_date:
            query = query.filter(Prediction.predicted_for >= start_date)
        if end_date:
            query = query.filter(Prediction.predicted_for <= end_date)
        if timeframe:
            query = query.filter(Prediction.timeframe == timeframe)

        predictions_count = query.count()

        # Calculate metrics (only if there are predictions)
        if predictions_count > 0:
            accuracy = calculate_accuracy(db, model.id, start_date, end_date, timeframe)
            mape = calculate_model_mape(db, model.id, start_date, end_date, timeframe)
            total_pnl = calculate_total_pnl(
                db, model.id, start_date, end_date, pnl_column, timeframe
            )
            win_rate = calculate_win_rate(
                db, model.id, start_date, end_date, pnl_column, timeframe
            )
            sharpe = calculate_sharpe_ratio(
                db, model.id, start_date, end_date, pnl_column, timeframe=timeframe
            )
            max_dd = calculate_max_drawdown(
                db, model.id, start_date, end_date, pnl_column, timeframe
            )
        else:
            accuracy = None
            mape = None
            total_pnl = None
            win_rate = None
            sharpe = None
            max_dd = None

        results.append(
            {
                "id": model.id,
                "name": model.name,
                "version": model.version,
                "is_active": model.is_active,
                "trained_at": model.trained_at,
                "predictions_count": predictions_count,
                "accuracy": round(accuracy, 4) if accuracy is not None else None,
                "avg_error_pct": round(mape, 2) if mape is not None else None,
                "total_pnl": round(total_pnl, 2) if total_pnl is not None else None,
                "win_rate": round(win_rate, 4) if win_rate is not None else None,
                "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
                "max_drawdown": round(max_dd, 2) if max_dd is not None else None,
            }
        )

    return results
