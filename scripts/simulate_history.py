#!/usr/bin/env python3
"""
Replay the daily job over past days so the dashboard has history to show.

For every run date D of the range it does what the 07:00 UTC cron does on day D,
using only the bars opened before D:

1. Train the linear model on the stored daily rows (``workers.daily.trainer`` data
   and feature code) and store it as the active ``1d`` model.
2. Predict the bar opened on D, ``predicted_for = D + 1`` (``workers.daily.predictor``).
3. Settle it against the close of that bar (``workers.daily.evaluator``), as the
   evaluator does once ``fetch-price`` has ingested it.

The rows land in ``models`` and ``predictions`` like real ones. They are told apart
by ``models.params["simulated"] = true``, since a prediction reaches its model
through ``model_id``. Nothing is written unless the whole range succeeds, and a
range that already has daily predictions is refused. With ``--keep-active`` the
simulated models stay inactive, so the model that is active when the script runs
(the real one, in production) remains the active one.

Usage:
    docker compose exec api python scripts/simulate_history.py
    docker compose exec api python scripts/simulate_history.py \
        --start 2026-08-01 --end 2026-08-31
    docker compose exec api python scripts/simulate_history.py --keep-active
"""

import argparse
import logging
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scripts.backtest_engine import DailyHistory, load_daily_history
from shared.config import settings
from shared.db.crud import activate_model
from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, Model, Prediction
from shared.features import (
    LOG_RETURN_TARGET,
    build_prediction_features,
    build_training_set,
    feature_count,
    price_from_return,
)
from workers.daily.evaluator import calculate_metrics
from workers.daily.models import LinearRegressionModel
from workers.daily.trainer import required_training_days

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_NAME = "linear_v1"
PREDICTOR_HOUR_UTC = 7  # hour stamped on replayed rows; the live cron runs at 00:10 UTC
PRICE_QUANTUM = Decimal("0.01")
DEFAULT_DAYS = 31


class SimulationError(ValueError):
    """The requested range cannot be simulated."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay the daily train -> predict -> evaluate cycle over past days"
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        help=f"First run date (default: {DEFAULT_DAYS - 1} days before --end)",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        help="Last run date (default: the last stored daily bar)",
    )
    parser.add_argument(
        "--keep-active",
        action="store_true",
        help="Leave the currently active model active (use against a live database)",
    )
    return parser.parse_args(argv)


def resolve_range(
    history: DailyHistory, start: date | None, end: date | None
) -> tuple[date, date]:
    """
    Fill the defaults: end on the last stored bar, start ``DEFAULT_DAYS`` days back.

    Run date D settles against the bar opened on D, so ``end`` cannot go past the
    last stored bar.

    Raises:
        SimulationError: No history, or the range is empty or past the stored bars.
    """
    if not history.dates:
        raise SimulationError(f"No {DEFAULT_SYMBOL} prices are loaded")
    last_bar = history.dates[-1]
    end = end or last_bar
    start = start or end - timedelta(days=DEFAULT_DAYS - 1)
    if end > last_bar:
        raise SimulationError(
            f"End date {end} is past the last stored bar {last_bar}: "
            f"the run on {end} could not be settled"
        )
    if start > end:
        raise SimulationError(f"Start date {start} is after end date {end}")
    return start, end


def check_enough_history(history: DailyHistory, start: date, window_days: int) -> None:
    """Fail when the first run date has fewer rows before it than training needs."""
    needed = required_training_days(window_days)
    available = sum(1 for day in history.dates if day < start)
    if available < needed:
        raise SimulationError(
            f"Start date {start} has only {available} daily rows before it, "
            f"training needs {needed} (window={window_days}d)"
        )


def check_range_is_empty(session: Session, start: date, end: date) -> None:
    """Refuse a range that already holds daily predictions (real or simulated)."""
    existing = session.scalar(
        select(func.count())
        .select_from(Prediction)
        .where(Prediction.timeframe == "1d")
        .where(Prediction.predicted_for >= start + timedelta(days=1))
        .where(Prediction.predicted_for <= end + timedelta(days=1))
    )
    if existing:
        raise SimulationError(
            f"{existing} daily prediction(s) already exist for {start} to {end}; "
            f"refusing to mix them with a simulation"
        )


def _at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=UTC)


def simulate_day(
    session: Session,
    history: DailyHistory,
    run_date: date,
    window_days: int,
    keep_active: bool = False,
) -> Prediction:
    """
    Train, predict and settle the run of ``run_date`` from the bars before it.

    The rows are added to ``session`` but not committed.

    Raises:
        SimulationError: The bar that settles the prediction is not stored.
    """
    end = sum(1 for day in history.dates if day < run_date)
    if run_date not in history.dates:
        raise SimulationError(f"No daily bar opened on {run_date} to settle the run")
    closes, volumes = history.closes[:end], history.volumes[:end]

    training_set = build_training_set(closes, volumes, window_days, horizon_days=1)
    model = LinearRegressionModel(
        window_days=window_days, n_features=feature_count(window_days)
    )
    model.train(training_set.X, training_set.y)

    record = Model(
        name=MODEL_NAME,
        version=f"sim-{run_date:%Y.%m.%d}",
        params={
            "window_days": window_days,
            "horizon_days": 1,
            "target": LOG_RETURN_TARGET,
            "simulated": True,
        },
        artifact=model.serialize(),
        trained_at=_at(run_date, PREDICTOR_HOUR_UTC - 1),
        train_from=history.dates[0],
        train_to=history.dates[end - 1],
        timeframe="1d",
        is_active=False,
    )
    session.add(record)
    session.flush()
    if not keep_active:
        activate_model(session, record.id)

    price_at_prediction = closes[-1]
    predicted_return = model.predict(
        build_prediction_features(closes, volumes, window_days)
    )
    prediction = Prediction(
        model_id=record.id,
        predicted_for=run_date + timedelta(days=1),
        timeframe="1d",
        predicted_at=_at(run_date, PREDICTOR_HOUR_UTC),
        price_at_prediction=price_at_prediction,
        predicted_price=Decimal(
            str(price_from_return(price_at_prediction, predicted_return))
        ).quantize(PRICE_QUANTUM),
    )

    actual_price = history.closes[history.dates.index(run_date)]
    metrics = calculate_metrics(prediction, actual_price)
    prediction.actual_price = actual_price
    prediction.evaluated_at = _at(run_date + timedelta(days=1), PREDICTOR_HOUR_UTC)
    prediction.error_abs = metrics["error_abs"]
    prediction.error_pct = metrics["error_pct"]
    prediction.direction_correct = metrics["direction_correct"]
    prediction.pnl_simulated = metrics["pnl_simulated"]
    prediction.pnl_long_short = metrics["pnl_long_short"]
    prediction.pnl_threshold = metrics["pnl_threshold"]
    prediction.pnl_realistic = metrics["pnl_realistic"]
    session.add(prediction)
    session.flush()
    return prediction


def simulate_range(
    session: Session,
    start: date | None = None,
    end: date | None = None,
    keep_active: bool = False,
) -> int:
    """
    Simulate every run date from ``start`` to ``end`` and commit once at the end.

    Returns:
        How many predictions were stored.

    Raises:
        SimulationError: Empty range, not enough history, or a range that already
            has predictions. Nothing is written in that case.
    """
    window_days = settings.training_window_days
    history = load_daily_history(session)
    start, end = resolve_range(history, start, end)
    check_enough_history(history, start, window_days)
    check_range_is_empty(session, start, end)

    predictions: list[Prediction] = []
    try:
        run_date = start
        while run_date <= end:
            predictions.append(
                simulate_day(session, history, run_date, window_days, keep_active)
            )
            run_date += timedelta(days=1)
        hits = sum(1 for p in predictions if p.direction_correct)  # before the commit
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        f"Stored {len(predictions)} simulated predictions ({start} to {end}), "
        f"direction hit rate {hits}/{len(predictions)}"
    )
    return len(predictions)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session = SessionLocal()
    try:
        simulate_range(session, args.start, args.end, args.keep_active)
    except SimulationError as error:
        logger.error(f"Cannot simulate: {error}")
        return 1
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
