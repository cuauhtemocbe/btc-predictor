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
- get_all_models_metrics: Metrics per model family (all versions), fixed query count
- get_family_cumulative_pnl: Cumulative PnL series per model family, in one query
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session, defer

from shared.db.crud import source_filter
from shared.db.models import Model, Prediction, PredictionSource, model_family
from shared.model_baselines import BASELINE_TIMEFRAME, baseline_for_predictions
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


def _round_or_none(value: float | None, digits: int) -> float | None:
    """Round ``value`` to ``digits`` decimals, keeping ``None`` as ``None``."""
    return round(value, digits) if value is not None else None


@dataclass
class _Family:
    """Versions of one model family for one asset and timeframe, and their days."""

    symbol: str
    name: str
    timeframe: str
    models: list[Model] = field(default_factory=list)
    predictions: list[Prediction] = field(default_factory=list)

    @property
    def representative(self) -> Model:
        """The active version, else the newest one (by ``trained_at``, then id)."""
        active = [m for m in self.models if m.is_active]
        return max(active or self.models, key=lambda m: (m.trained_at, m.id))


def _model_conditions(
    symbol: str | None, source: PredictionSource
) -> list[ColumnElement[bool]]:
    """WHERE conditions on ``models`` selecting one asset (if given) and source."""
    conditions = [source_filter(source)]
    if symbol:
        conditions.append(Model.symbol == symbol)
    return conditions


def _load_families(
    db: Session,
    start_date: date | None,
    end_date: date | None,
    timeframe: str | None,
    symbol: str | None,
    source: PredictionSource,
) -> list[_Family]:
    """
    Group the models by (symbol, family, timeframe) with their evaluated predictions.

    Always two queries (the models, then every evaluated prediction of those
    models), however many model rows exist: the trainer saves one per day (#178).
    Families come back ordered by symbol and name; predictions by ``predicted_for``
    (then id), across every version of the family.
    """

    families: dict[tuple[str, str, str], _Family] = {}
    family_of_model: dict[int, _Family] = {}
    conditions = _model_conditions(symbol, source)
    models_query = select(Model).options(defer(Model.artifact)).where(*conditions)
    for model in db.execute(models_query).scalars():
        name = model_family(model.name)
        key = (model.symbol, name, model.timeframe)
        family = families.setdefault(key, _Family(model.symbol, name, model.timeframe))
        family.models.append(model)
        family_of_model[model.id] = family

    if family_of_model:
        query = (
            select(Prediction)
            .join(Model, Prediction.model_id == Model.id)
            .where(Prediction.actual_price.isnot(None))
            .where(*conditions)
            .order_by(Prediction.predicted_for, Prediction.id)
        )
        if start_date:
            query = query.where(Prediction.predicted_for >= start_date)
        if end_date:
            query = query.where(Prediction.predicted_for <= end_date)
        if timeframe:
            query = query.where(Prediction.timeframe == timeframe)
        for prediction in db.execute(query).scalars():
            family_of_model[prediction.model_id].predictions.append(prediction)

    return [families[key] for key in sorted(families)]


def _family_metrics(
    predictions: Sequence[Prediction], pnl_column: str
) -> dict[str, float | None]:
    """
    Raw (unrounded) performance metrics over the predictions of one family.

    ``predictions`` are evaluated and in ``predicted_for`` order, so the Sharpe
    ratio and the drawdown run over the whole history of the family, across its
    versions. Every metric is None when there are no predictions.
    """
    pnls = [getattr(p, pnl_column) for p in predictions]
    valid_pnls = [float(pnl) for pnl in pnls if pnl is not None]
    errors = [
        abs(float((p.actual_price - p.predicted_price) / p.actual_price))
        for p in predictions
        if p.actual_price
    ]
    returns = returns_from_pnl(
        (pnl, p.price_at_prediction) for pnl, p in zip(pnls, predictions, strict=True)
    )
    count = len(predictions)
    return {
        "accuracy": (
            sum(p.direction_correct is True for p in predictions) / count
            if count
            else None
        ),
        "mape": float(np.mean(errors)) * 100 if errors else None,
        "total_pnl": sum(valid_pnls) if valid_pnls else None,
        "win_rate": (
            sum(pnl is not None and pnl > 0 for pnl in pnls) / count if count else None
        ),
        "sharpe": sharpe_ratio(returns),
        "max_dd_pct": max_drawdown_pct(returns),
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


def get_family_cumulative_pnl(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    pnl_column: str = "pnl_simulated",
    timeframe: str | None = None,
    symbol: str | None = None,
    source: PredictionSource = PredictionSource.ALL,
) -> dict[str, list[dict[str, Any]]]:
    """
    Cumulative PnL series of every model family, keyed by family name.

    Same filters and the same days as ``get_all_models_metrics``; each series
    runs over all the versions of the family in ``predicted_for`` order. Two
    queries in total, however many model rows exist. With no ``symbol`` two assets
    that share a family name collapse into one key, so callers pass one.
    """
    series: dict[str, list[dict[str, Any]]] = {}
    for family in _load_families(db, start_date, end_date, timeframe, symbol, source):
        cumsum = 0.0
        points = series.setdefault(family.name, [])
        for prediction in family.predictions:
            pnl = getattr(prediction, pnl_column)
            if pnl is not None:
                cumsum += float(pnl)
                points.append(
                    {
                        "date": prediction.predicted_for.isoformat(),
                        "cumulative_pnl": round(cumsum, 2),
                    }
                )
    return series


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
    Get performance metrics per model family, one row per (symbol, family, timeframe).

    The trainer saves a new model row (``linear_v<N>``) every run and each one makes
    a handful of predictions, so a metric per row means nothing (#178). A row here
    covers every version of the family: counts, accuracy, MAPE, PnL, win rate,
    Sharpe ratio, drawdown and baselines run over all their evaluated predictions
    together, in ``predicted_for`` order. Every model row stays in the database
    with its version and ``train_to``; the family row summarizes them.

    The number of queries does not depend on how many model rows exist: two to
    load the models and predictions (``_load_families``) plus one prices query per
    family for the baselines.

    Args:
        db: Database session
        start_date: Optional start date filter for metrics calculation
        end_date: Optional end date filter for metrics calculation
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Optional timeframe filter ('1d'). If None,
            every timeframe is mixed together for every metric below.
        symbol: Optional asset filter; only models trained for it are returned.
        source: ``live``, ``replay`` or ``all`` (default); only the models, and
            the predictions of the models, of that source count (replay = trained
            by ``simulate_history``).

    Returns:
        List of dictionaries, ordered by symbol and family name, with structure:
        {
            "id": int,  # the active version, else the newest one
            "name": str,  # the family: "linear" for linear_v1, linear_v2, ...
            "version": str,  # version string of the model in "id"
            "is_active": bool,  # any version is active
            "trained_at": datetime,  # latest training of the family
            "versions_count": int,
            "first_train_to": date,  # earliest ``train_to`` among the versions
            "last_train_to": date,  # latest ``train_to`` among the versions
            "predictions_count": int,
            "accuracy": float | None,
            "avg_error_pct": float | None,
            "total_pnl": float | None,
            "win_rate": float | None,
            "sharpe_ratio": float | None,
            "max_drawdown_pct": float | None,
            "symbol": str,
            "is_replay": bool,  # every version is simulated (history replay)
            "baseline": dict | None,  # see baseline_for_predictions (daily only)
        }

    Examples:
        >>> get_all_models_metrics(db)
        [
            {
                "id": 7,
                "name": "linear",
                "versions_count": 40,
                "predictions_count": 40,
                "accuracy": 0.65,
                ...
            },
        ]
    """
    results = []
    for family in _load_families(db, start_date, end_date, timeframe, symbol, source):
        model = family.representative
        results.append(
            {
                "id": model.id,
                "name": family.name,
                "version": model.version,
                "is_active": any(m.is_active for m in family.models),
                "trained_at": max(m.trained_at for m in family.models),
                "versions_count": len(family.models),
                "first_train_to": min(m.train_to for m in family.models),
                "last_train_to": max(m.train_to for m in family.models),
                "predictions_count": len(family.predictions),
                **_round_model_metrics(_family_metrics(family.predictions, pnl_column)),
                "symbol": family.symbol,
                "is_replay": all(m.is_replay for m in family.models),
                "baseline": (
                    baseline_for_predictions(db, family.symbol, family.predictions)
                    if timeframe == BASELINE_TIMEFRAME
                    else None
                ),
            }
        )

    return results
