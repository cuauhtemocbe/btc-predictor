#!/usr/bin/env python3
"""
Report of a stored walk-forward backtest run.

Puts the model next to the trivial baselines (``shared.baselines``) over exactly
the days it was evaluated on, with the sample size and the edge over the best
baseline. The headline is the ``test`` slice only: the ``validation`` slice (the
only data allowed to inform choices) is reported separately and labelled, and rows
stored before the split existed are shown as ``unsplit``.

Usage:
    python scripts/backtest_report.py --run-id=<uuid>
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.backtest_engine import TEST, VALIDATION, load_daily_history
from shared.baselines import (
    DEFAULT_SIGNIFICANCE_LEVEL,
    BaselineReport,
    EvaluatedDay,
    evaluate_baselines,
)
from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL, BacktestResult

logger = logging.getLogger(__name__)

UNSPLIT = "unsplit"


@dataclass(frozen=True)
class SliceReport:
    """The model and the baselines over one slice of a run."""

    name: str
    baselines: BaselineReport
    model_pnl: Decimal | None


@dataclass(frozen=True)
class RunReport:
    """Everything the report shows about one run."""

    run_id: UUID
    params: dict[str, Any]
    first_day: date
    last_day: date
    sections: dict[str, SliceReport]

    @property
    def headline(self) -> SliceReport:
        """The out-of-sample result: the test slice (possibly empty)."""
        return self.sections[TEST]


def _slice_report(
    name: str, rows: list[BacktestResult], closes: dict[date, Decimal]
) -> SliceReport:
    days = [
        EvaluatedDay(
            predicted_for=row.predicted_for,
            previous_close=closes.get(row.predicted_for - timedelta(days=2)),
            price_at_prediction=row.price_at_prediction,
            actual_price=row.actual_price,
            predicted_price=row.predicted_price,
        )
        for row in rows
    ]
    model_pnl = (
        sum((r.pnl_simple for r in rows if r.pnl_simple is not None), Decimal(0))
        if rows
        else None
    )
    return SliceReport(name, evaluate_baselines(days), model_pnl)


def build_report(db: Session, run_id: UUID) -> RunReport:
    """
    Build the report of a stored run.

    ``previous_close`` of each day (the close of D-2, for persistence) comes from
    ``prices``, so persistence covers every evaluated day, not only those that
    follow another stored row.

    Raises:
        ValueError: If the run has no stored results.
    """
    rows = list(
        db.execute(
            select(BacktestResult)
            .where(BacktestResult.backtest_run_id == run_id)
            .order_by(BacktestResult.predicted_for)
        ).scalars()
    )
    if not rows:
        raise ValueError(f"No backtest results for run {run_id}")

    params = rows[0].model_params or {}
    history = load_daily_history(db, params.get("symbol", DEFAULT_SYMBOL))
    closes = dict(zip(history.dates, history.closes, strict=True))

    by_slice: dict[str, list[BacktestResult]] = {TEST: [], VALIDATION: [], UNSPLIT: []}
    for row in rows:
        by_slice[row.evaluation_slice or UNSPLIT].append(row)

    sections = {
        name: _slice_report(name, slice_rows, closes)
        for name, slice_rows in by_slice.items()
        if slice_rows or name == TEST
    }
    return RunReport(
        run_id=run_id,
        params=params,
        first_day=rows[0].predicted_for,
        last_day=rows[-1].predicted_for,
        sections=sections,
    )


def _percent(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.2f}%"


def _money(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


def _block(section: SliceReport) -> list[str]:
    b = section.baselines
    lines = [
        f"  Model accuracy:          {_percent(b.model_accuracy)}",
        f"  Always-up accuracy:      {_percent(b.always_up_accuracy)}",
        f"  Persistence accuracy:    {_percent(b.persistence_accuracy)}"
        f" ({b.persistence_n_days} days)",
        f"  Best baseline:           {b.best_baseline or 'unavailable'}",
    ]
    if b.edge is None or b.p_value is None:
        lines.append("  Edge over best baseline: unavailable")
    else:
        verdict = "significant" if b.significant else "not significant"
        lines.append(
            f"  Edge over best baseline: {b.edge * 100:+.2f} pp "
            f"(p = {b.p_value:.4f}, {verdict} at {DEFAULT_SIGNIFICANCE_LEVEL})"
        )
    lines += [
        f"  Model PnL (simple):      {_money(section.model_pnl)}",
        f"  Always-up PnL:           {_money(b.always_up_pnl)}",
        f"  Persistence PnL:         {_money(b.persistence_pnl)}",
        f"  Buy-and-hold PnL:        {_money(b.buy_and_hold_pnl)}",
    ]
    return lines


def _title(section: SliceReport) -> str:
    n = section.baselines.n_days
    count = f"{n} evaluated days" if n else "unavailable (0 evaluated days)"
    if section.name == TEST:
        return f"== Headline: test slice (out-of-sample), {count} =="
    if section.name == VALIDATION:
        return f"-- Validation slice (tuning only, never a result), {count} --"
    return (
        f"-- Unsplit (stored without a validation/test split; not out-of-sample), "
        f"{count} --"
    )


def format_report(report: RunReport) -> str:
    """Render a RunReport as text: configuration, headline, then the other slices."""
    p = report.params
    lines = [
        f"Backtest report for run {report.run_id}",
        f"Model: {p.get('model_name', '?')}  window: {p.get('window_days', '?')}d  "
        f"seed: {p.get('seed', '?')}  retrain every: {p.get('retrain_every', '?')} "
        f"day(s)",
        f"Range: {report.first_day} to {report.last_day}",
    ]
    if p.get("test_start_date"):
        lines.append(f"Test slice starts: {p['test_start_date']}")
    for name in (TEST, VALIDATION, UNSPLIT):
        section = report.sections.get(name)
        if section is None:
            continue
        lines += ["", _title(section)]
        if section.baselines.n_days:
            lines += _block(section)
    lines += [
        "",
        "p-value: one-sided binomial test against the best baseline's accuracy "
        "(an approximation: the baseline's accuracy is treated as fixed and the "
        "choice of the best of two baselines is not corrected for).",
    ]
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
) -> int:
    """Print the report of a stored run. Returns the exit code (0 = success)."""
    parser = argparse.ArgumentParser(description="Report of a stored backtest run")
    parser.add_argument("--run-id", type=UUID, required=True, help="Backtest run UUID")
    args = parser.parse_args(argv)
    try:
        with session_factory() as db:
            print(format_report(build_report(db, args.run_id)))
        return 0
    except ValueError as e:
        logger.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
