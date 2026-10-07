"""
Utility functions for BTC Predictor.

Functions:
- utc_now: Current instant in UTC, the clock of the freshness guard
- utc_today: Current calendar date in UTC, the day boundary of the whole pipeline
- calculate_pnl: Calculate simulated profit/loss from prediction strategy
- calculate_pnl_long_short: Calculate PnL with long/short symmetric strategy
- calculate_pnl_threshold: Calculate PnL with threshold filter
- calculate_pnl_realistic: Calculate PnL with trading fees and stop-loss

Model Metrics Functions (for dashboard):
- calculate_accuracy: Calculate % of correct direction predictions for a model
- calculate_model_mape: Calculate MAPE from database predictions for a model
- calculate_total_pnl: Calculate total PnL for a model
- calculate_win_rate: Calculate % of positive PnL predictions for a model
- calculate_sharpe_ratio: Annualized Sharpe ratio of a model's returns
- calculate_max_drawdown_pct: Max drawdown of a model's compounded equity curve, in %
- get_cumulative_pnl: Get daily cumulative PnL time series for a model
- get_all_models_metrics: Get metrics for all models in one call
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.db.models import PredictionSource
from shared.returns import max_drawdown_pct, returns_from_pnl, sharpe_ratio

# Prediction.timeframe values, and the one used when a caller doesn't name
# one explicitly. Applied consistently across every metric function below
# and every API endpoint that doesn't require an explicit timeframe query
# param -- see issue #67.
SUPPORTED_TIMEFRAMES = ("1d",)
DEFAULT_TIMEFRAME = "1d"


def utc_now() -> datetime:
    """Return the current instant as a timezone-aware UTC datetime.

    The clock the freshness guard of the predictor reads (#175); tests freeze it
    by patching ``datetime`` in this module.
    """
    return datetime.now(UTC)


def utc_today() -> date:
    """Return today's calendar date in UTC, whatever the process time zone is.

    Daily bars open at 00:00 UTC, so every job defines "today" in UTC.
    The container's local date follows its ``TZ`` (America/Mexico_City, UTC-6) and
    is a day behind UTC for part of the day (#173).
    """
    return utc_now().date()


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
        timeframe: Optional timeframe filter ('1d'). If None,
            predictions across every timeframe are mixed together --
            callers that want timeframes separated must pass this
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
        timeframe: Optional timeframe filter ('1d'). If None,
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
        timeframe: Optional timeframe filter ('1d'). If None,
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
        timeframe: Optional timeframe filter ('1d'). If None,
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


def get_model_returns(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> list[float]:
    """
    Per-trade returns of a model's evaluated predictions, oldest first.

    Return = pnl_column / price_at_prediction, so a -$5,000 day at BTC = $100,000 is
    -5%, whatever the price level (#177). Predictions without a PnL or without a
    positive price are skipped. The stored pnl_* columns are not changed.

    Args:
        db: Database session
        model_id: Model ID to read returns for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1d'). If None, every timeframe is
            mixed together in one series.

    Returns:
        Returns as fractions (-0.05 for -5%); empty when there is no data.
    """
    from shared.db.models import Prediction

    query = db.query(getattr(Prediction, pnl_column), Prediction.price_at_prediction)
    query = query.filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )
    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    rows = query.order_by(Prediction.predicted_for).all()
    return returns_from_pnl((pnl, price) for pnl, price in rows)


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
    Calculate the annualized Sharpe ratio of a model's daily returns.

    Sharpe Ratio = (MEAN(returns) - risk_free_rate / 365) / STDEV(returns) * sqrt(365)

    Returns are pnl / price_at_prediction (see get_model_returns) and the daily
    timeframe is the only one, so the factor is always the square root of 365.

    Args:
        db: Database session
        model_id: Model ID to calculate Sharpe ratio for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        risk_free_rate: Annual risk-free rate (default: 0.0)
        timeframe: Optional timeframe filter ('1d'). If None, every timeframe is
            mixed together.

    Returns:
        Annualized Sharpe ratio, or None with fewer than 2 returns or no variance

    Examples:
        >>> calculate_sharpe_ratio(db, model_id=1, timeframe="1d")
        1.25  # Sharpe ratio of 1.25
    """
    returns = get_model_returns(
        db, model_id, start_date, end_date, pnl_column, timeframe
    )
    return sharpe_ratio(returns, risk_free_rate)


def calculate_max_drawdown_pct(
    db: Session,
    model_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
) -> float | None:
    """
    Calculate the max drawdown of a model's compounded equity curve, in percent.

    The curve compounds the per-trade returns (pnl / price_at_prediction) from 1.0
    and the drawdown is the largest fall from a running peak (see
    shared.returns.max_drawdown_pct), so it never goes below -100% (#177).

    Args:
        db: Database session
        model_id: Model ID to calculate max drawdown for
        start_date: Optional start date filter
        end_date: Optional end date filter
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1d'). If None, every timeframe is
            mixed together in one equity curve.

    Returns:
        Maximum drawdown as a negative percentage (e.g. -20.0 for a 20% fall),
        or None if no data

    Examples:
        >>> calculate_max_drawdown_pct(db, model_id=1, timeframe="1d")
        -4.5  # 4.5% drawdown from peak equity
    """
    returns = get_model_returns(
        db, model_id, start_date, end_date, pnl_column, timeframe
    )
    return max_drawdown_pct(returns)


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
        timeframe: Optional timeframe filter ('1d'). If None,
            daily and other-timeframe records are combined into one series.

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


def _round_or_none(value: float | None, digits: int) -> float | None:
    """Round ``value`` to ``digits`` decimals, keeping ``None`` as ``None``."""
    return round(value, digits) if value is not None else None


def _count_evaluated_predictions(
    db: Session,
    model_id: int,
    start_date: date | None,
    end_date: date | None,
    timeframe: str | None,
) -> int:
    """Count the evaluated predictions of a model within the given filters."""
    from shared.db.models import Prediction

    query = db.query(Prediction).filter(
        Prediction.model_id == model_id, Prediction.actual_price.isnot(None)
    )

    if start_date:
        query = query.filter(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.filter(Prediction.predicted_for <= end_date)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)

    return query.count()


def _calculate_model_metrics(
    db: Session,
    model_id: int,
    predictions_count: int,
    start_date: date | None,
    end_date: date | None,
    pnl_column: str,
    timeframe: str | None,
) -> dict[str, float | None]:
    """
    Calculate the raw (unrounded) performance metrics of one model.

    Every metric is None when the model has no evaluated predictions.
    """
    if predictions_count <= 0:
        return {
            "accuracy": None,
            "mape": None,
            "total_pnl": None,
            "win_rate": None,
            "sharpe": None,
            "max_dd_pct": None,
        }

    return {
        "accuracy": calculate_accuracy(db, model_id, start_date, end_date, timeframe),
        "mape": calculate_model_mape(db, model_id, start_date, end_date, timeframe),
        "total_pnl": calculate_total_pnl(
            db, model_id, start_date, end_date, pnl_column, timeframe
        ),
        "win_rate": calculate_win_rate(
            db, model_id, start_date, end_date, pnl_column, timeframe
        ),
        "sharpe": calculate_sharpe_ratio(
            db, model_id, start_date, end_date, pnl_column, timeframe=timeframe
        ),
        "max_dd_pct": calculate_max_drawdown_pct(
            db, model_id, start_date, end_date, pnl_column, timeframe
        ),
    }


def _round_model_metrics(metrics: dict[str, float | None]) -> dict[str, float | None]:
    """Round raw model metrics to the precision exposed by the API."""
    return {
        "accuracy": _round_or_none(metrics["accuracy"], 4),
        "avg_error_pct": _round_or_none(metrics["mape"], 2),
        "total_pnl": _round_or_none(metrics["total_pnl"], 2),
        "win_rate": _round_or_none(metrics["win_rate"], 4),
        "sharpe_ratio": _round_or_none(metrics["sharpe"], 2),
        "max_drawdown_pct": _round_or_none(metrics["max_dd_pct"], 2),
    }


def get_all_models_metrics(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
    symbol: str | None = None,
    source: PredictionSource = PredictionSource.ALL,
) -> list[dict[str, Any]]:
    """
    Get performance metrics for all models in one call.

    Returns list of dictionaries with model metadata and calculated metrics.

    Args:
        db: Database session
        start_date: Optional start date filter for metrics calculation
        end_date: Optional end date filter for metrics calculation
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1d'). If None,
            every timeframe is mixed together for every metric below.
        symbol: Optional asset filter; only models trained for it are returned.
        source: ``live``, ``replay`` or ``all`` (default); only models of that
            source are returned (replay = trained by ``simulate_history``).

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
            "max_drawdown_pct": float | None,
            "symbol": str,
            "is_replay": bool,  # simulated model (history replay), not live
            "baseline": dict | None,  # see get_model_baseline (daily only)
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
    from shared.db.crud import source_filter
    from shared.db.models import Model
    from shared.model_baselines import get_model_baseline

    # Get all models (of one asset when a symbol is given)
    model_query = db.query(Model)
    if symbol:
        model_query = model_query.filter(Model.symbol == symbol)
    models = model_query.filter(source_filter(source)).all()

    results = []
    for model in models:
        predictions_count = _count_evaluated_predictions(
            db, model.id, start_date, end_date, timeframe
        )
        metrics = _calculate_model_metrics(
            db,
            model.id,
            predictions_count,
            start_date,
            end_date,
            pnl_column,
            timeframe,
        )

        results.append(
            {
                "id": model.id,
                "name": model.name,
                "version": model.version,
                "is_active": model.is_active,
                "trained_at": model.trained_at,
                "predictions_count": predictions_count,
                **_round_model_metrics(metrics),
                "symbol": model.symbol,
                "is_replay": model.is_replay,
                "baseline": get_model_baseline(
                    db, model.id, model.symbol, start_date, end_date, timeframe
                ),
            }
        )

    return results
