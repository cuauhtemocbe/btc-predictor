"""Day boundary, simulated-PnL strategies and per-family model metrics."""

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

# Prediction.timeframe values and the default for callers that name none (#67).
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
    """Long-only PnL in USDT of 1 unit: long if predicted UP, else cash (PnL 0).

    Args:
        predicted_price: Predicted price.
        price_at_prediction: Price when the prediction was made (the entry).
        actual_price: Price at evaluation time (the exit).
    """
    if predicted_price > price_at_prediction:
        pnl = actual_price - price_at_prediction
    else:
        pnl = Decimal("0.00")

    return pnl


def calculate_pnl_long_short(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> Decimal:
    """Long/short PnL in USDT of 1 unit: long if predicted UP, else short.

    Args: same as ``calculate_pnl``.
    """
    if predicted_price > price_at_prediction:
        pnl = actual_price - price_at_prediction
    else:
        pnl = price_at_prediction - actual_price

    return pnl


def calculate_pnl_threshold(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
    threshold: Decimal = Decimal("1.0"),
) -> Decimal:
    """Long/short PnL, but 0 when the predicted change is under ``threshold`` %.

    Args: same as ``calculate_pnl``, plus ``threshold``, the minimum absolute
        predicted change in percent that triggers a trade.
    """
    change_pct = abs(
        (predicted_price - price_at_prediction) / price_at_prediction * 100
    )

    if change_pct < threshold:
        return Decimal("0.00")

    return calculate_pnl_long_short(predicted_price, price_at_prediction, actual_price)


def calculate_pnl_realistic(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
    fee_pct: Decimal = Decimal("0.1"),
    stop_loss_pct: Decimal = Decimal("2.0"),
) -> Decimal:
    """Long/short PnL after fees, with the gross loss capped by a stop-loss.

    Fees are ``fee_pct`` of ``price_at_prediction`` on entry and on exit; the
    gross loss is capped at ``stop_loss_pct`` of ``price_at_prediction``.

    Args: same as ``calculate_pnl``, plus ``fee_pct`` (per trade, percent) and
        ``stop_loss_pct`` (percent).
    """
    gross_pnl = calculate_pnl_long_short(
        predicted_price, price_at_prediction, actual_price
    )

    fees = price_at_prediction * (fee_pct / 100) * 2

    max_loss = price_at_prediction * (stop_loss_pct / 100)

    if gross_pnl < -max_loss:
        gross_pnl = -max_loss

    net_pnl = gross_pnl - fees

    return net_pnl


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
    """Group the models by (symbol, family, timeframe) with their evaluated predictions.

    Two queries however many model rows exist: the trainer saves one per day
    (#178). Families are ordered by symbol and name; predictions by
    ``predicted_for`` then id, across every version of the family.
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
    """Unrounded metrics over the evaluated predictions of one family.

    ``predictions`` must be in ``predicted_for`` order: Sharpe ratio and drawdown
    run over the whole history of the family. Every metric is None without predictions.
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
    """Cumulative PnL series per model family, keyed by family name.

    Same filters and days as ``get_all_models_metrics``; each series covers all
    versions of the family in ``predicted_for`` order, in two queries. Without
    ``symbol``, two assets sharing a family name collapse into one key, so callers
    pass one.
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
    """Performance metrics per model family, one row per (symbol, family, timeframe).

    The trainer saves a new row (``linear_v<N>``) every run and each makes a handful
    of predictions, so a metric per row means nothing (#178). A family row pools
    all its versions' evaluated predictions in ``predicted_for`` order; every model
    row stays in the database. Queries: two (``_load_families``) plus one prices
    query per family for the baselines.

    Args:
        db: Database session.
        start_date: Optional lower bound on ``predicted_for``.
        end_date: Optional upper bound on ``predicted_for``.
        pnl_column: PnL column to use.
        timeframe: Optional filter; ``None`` mixes every timeframe.
        symbol: Optional asset filter.
        source: ``live``, ``replay`` or ``all``; filters the models and so their
            predictions (replay = trained by ``simulate_history``).

    Returns:
        One dict per family, ordered by symbol and name. ``id`` and ``version``
        are those of the active version, else the newest; ``is_active`` is true if
        any version is; ``is_replay`` if every version is; ``baseline`` is None
        unless ``timeframe`` is the baseline one (see ``baseline_for_predictions``).
        The remaining keys are ``name``, ``trained_at``, ``versions_count``,
        ``first_train_to``, ``last_train_to``, ``predictions_count``, ``accuracy``,
        ``avg_error_pct``, ``total_pnl``, ``win_rate``, ``sharpe_ratio``,
        ``max_drawdown_pct`` and ``symbol``.
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
