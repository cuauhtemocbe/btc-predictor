"""
Baselines for a stored model's evaluated predictions (#105, shown by #107).

``shared.baselines`` scores a list of evaluated days; this module builds that list
from the ``predictions`` table, adds the close of D-2 from ``prices`` for the
persistence baseline, and turns the report into plain values the API and templates
can serialize.

Baselines are daily-only: persistence compares D-1 with D-2, which says nothing
about a weekly horizon, so other timeframes get no baseline (None), never a
misleading number.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.baselines import BaselineReport, EvaluatedDay, evaluate_baselines
from shared.db.models import Prediction, Price

BASELINE_TIMEFRAME = "1d"

BEATS = "beats"
INCONCLUSIVE = "inconclusive"
NOT_BEATING = "not_beating"


def verdict(report: BaselineReport) -> str | None:
    """
    Classify the model's edge over its best baseline.

    - ``not_beating``: accuracy at or below the best baseline.
    - ``beats``: above it, and the one-sided binomial test is significant.
    - ``inconclusive``: above it, but a lucky streak could explain the gap.

    Returns None when the edge cannot be computed.
    """
    if report.edge is None or report.significant is None:
        return None
    if report.edge <= 0:
        return NOT_BEATING
    return BEATS if report.significant else INCONCLUSIVE


def daily_closes(db: Session, symbol: str, from_day: date) -> dict[date, Decimal]:
    """
    Close of each stored day of ``symbol`` on or after ``from_day``.

    Same aggregation as the trainer: the latest row of each day supplies its close.
    """
    first_timestamp = datetime.combine(from_day, time.min, tzinfo=UTC)
    latest_per_day = (
        select(
            func.date_trunc("day", Price.timestamp).label("day"),
            func.max(Price.timestamp).label("latest_timestamp"),
        )
        .where(Price.symbol == symbol, Price.timestamp >= first_timestamp)
        .group_by("day")
        .subquery()
    )
    rows = db.execute(
        select(latest_per_day.c.day, Price.close)
        .join(latest_per_day, Price.timestamp == latest_per_day.c.latest_timestamp)
        .where(Price.symbol == symbol)
    ).all()
    return {row.day.date(): row.close for row in rows}


def get_model_baseline(
    db: Session,
    model_id: int,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    timeframe: str | None = None,
) -> dict[str, Any] | None:
    """
    Baselines and edge of one model over its evaluated predictions.

    The days scored are exactly the evaluated predictions of ``model_id`` inside
    the filters, so baseline and model accuracy always cover the same period.

    Args:
        db: Database session
        model_id: Model whose evaluated predictions are scored
        symbol: Asset the model predicts; its prices give the close of D-2
        start_date: Optional first ``predicted_for`` (inclusive)
        end_date: Optional last ``predicted_for`` (inclusive)
        timeframe: Only ``"1d"`` has baselines; anything else returns None

    Returns:
        None when the timeframe has no baselines or nothing was evaluated.
        Otherwise a JSON-friendly dict: ``n_days``, ``always_up_accuracy``,
        ``persistence_accuracy``, ``persistence_n_days``, ``best_baseline``,
        ``buy_and_hold_pnl``, ``edge``, ``p_value``, ``significant`` and
        ``verdict`` (``beats`` / ``inconclusive`` / ``not_beating``).
    """
    if timeframe != BASELINE_TIMEFRAME:
        return None

    query = select(Prediction).where(
        Prediction.model_id == model_id,
        Prediction.actual_price.isnot(None),
        Prediction.timeframe == BASELINE_TIMEFRAME,
    )
    if start_date:
        query = query.where(Prediction.predicted_for >= start_date)
    if end_date:
        query = query.where(Prediction.predicted_for <= end_date)
    predictions = list(db.execute(query).scalars())
    if not predictions:
        return None

    first_day = min(p.predicted_for for p in predictions) - timedelta(days=2)
    closes = daily_closes(db, symbol, first_day)
    days = [
        EvaluatedDay(
            predicted_for=p.predicted_for,
            previous_close=closes.get(p.predicted_for - timedelta(days=2)),
            price_at_prediction=p.price_at_prediction,
            actual_price=p.actual_price,
            predicted_price=p.predicted_price,
        )
        for p in predictions
        if p.actual_price is not None
    ]
    report = evaluate_baselines(days)
    return {
        "n_days": report.n_days,
        "always_up_accuracy": report.always_up_accuracy,
        "persistence_accuracy": report.persistence_accuracy,
        "persistence_n_days": report.persistence_n_days,
        "best_baseline": report.best_baseline,
        "buy_and_hold_pnl": (
            float(report.buy_and_hold_pnl)
            if report.buy_and_hold_pnl is not None
            else None
        ),
        "edge": report.edge,
        "p_value": report.p_value,
        "significant": report.significant,
        "verdict": verdict(report),
    }
