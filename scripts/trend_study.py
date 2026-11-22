#!/usr/bin/env python3
"""
Validation and test protocol of the trend-following spike (#181).

Candidates are SMA rules over a grid of lookbacks and a Donchian ensemble with
volatility sizing. Parameters are chosen on the validation slice only (every day
before 2024-01-01), by net Sharpe at the headline cost; the winner then runs once on
the test slice together with its neighbors, buy-and-hold and every other candidate
(the others only feed the deflated Sharpe ratio and the tables). The go or no-go is
``decide`` applied to the winner, at each slippage level.

Usage:
    python -m scripts.trend_study > report.md
"""

import logging
import math
import sys
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt
from sqlalchemy.orm import Session

from scripts.backtest_engine import load_daily_history
from scripts.trend_following import (
    TRADING_DAYS_PER_YEAR,
    WINDOW_PERCENTILES,
    Costs,
    Metrics,
    WindowSummary,
    compute_metrics,
    deflated_sharpe_probability,
    donchian_positions,
    simulate,
    sma_positions,
    summarize_windows,
)
from shared.db.database import SessionLocal
from shared.db.models import DEFAULT_SYMBOL

logger = logging.getLogger(__name__)

Floats = npt.NDArray[np.float64]

SMA = "sma"
DONCHIAN = "donchian"

VALIDATION_END = date(2023, 12, 31)
TEST_START = date(2024, 1, 1)
MIN_SLICE_DAYS = 365

FEE = 0.001
SLIPPAGE_LEVELS = (0.0005, 0.001, 0.002)
HEADLINE_SLIPPAGE = 0.001

FIXED_SMA_LOOKBACKS = (50, 100, 200)  # fixed before the audit script printed anything
GRID_LOW, GRID_HIGH, GRID_RATIO = 20, 300, 1.1
DONCHIAN_LOOKBACKS = (10, 20, 40, 80, 160)  # the author's choice, not the paper's
DONCHIAN_TARGET_VOLS: tuple[float | None, ...] = (None, 0.30, 0.45, 0.60)
VOL_WINDOW = 30
NEIGHBOR_SCALES = (0.8, 1.2)  # "neighboring lookbacks (within 20%)"

AUDIT_START = date(2019, 1, 1)  # the audit script of 2026-10-03 covered 2019-2026
WINDOWS = (("1 month", 30), ("3 months", 91))
DEFLATION_TRIALS = (1, 2, 5, 10, 20)  # trial counts the sensitivity table also shows

MAX_DRAWDOWN_LIMIT = -0.40  # docs/STRATEGY.md, answer 1: the hard limit
DRAWDOWN_WARNING = -0.30
DEFLATED_SHARPE_MIN = 0.95
COLLAPSE_SHARE = 0.5  # a neighbor collapses below half of the winner's Sharpe

AUDIT_COSTS = Costs(fee=FEE, slippage=0.0)


# ---------------------------------------------------------------------------
# Rule configurations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleConfig:
    """One trend rule with its parameters.

    Attributes:
        family: ``sma`` (one lookback) or ``donchian`` (an ensemble of lookbacks).
        lookbacks: Lookbacks in days.
        target_vol: Annualized volatility target of a Donchian ensemble, or None for
            no volatility sizing. Unused by ``sma``.
    """

    family: str
    lookbacks: tuple[int, ...]
    target_vol: float | None = None

    @property
    def name(self) -> str:
        """Short label for tables."""
        if self.family == SMA:
            return f"SMA{self.lookbacks[0]}"
        sizing = (
            "no sizing" if self.target_vol is None else f"vol {self.target_vol:.0%}"
        )
        return f"Donchian {'/'.join(str(n) for n in self.lookbacks)}, {sizing}"

    @property
    def warmup_days(self) -> int:
        """Index of the first day on which the rule can be long."""
        if self.family == SMA:
            return self.lookbacks[0] - 1
        return max(max(self.lookbacks), VOL_WINDOW if self.target_vol else 0)

    def positions(self, closes: Floats) -> Floats:
        """Position decided at each close."""
        if self.family == SMA:
            return sma_positions(closes, self.lookbacks[0])
        return donchian_positions(
            closes, self.lookbacks, self.target_vol, vol_window=VOL_WINDOW
        )

    def scaled(self, factor: float) -> "RuleConfig":
        """The same rule with every lookback multiplied by ``factor``."""
        return RuleConfig(
            self.family,
            tuple(max(2, round(n * factor)) for n in self.lookbacks),
            self.target_vol,
        )

    def neighbors(self) -> tuple["RuleConfig", ...]:
        """Rules whose lookbacks are 20% below and above, without duplicates."""
        found = (self.scaled(factor) for factor in NEIGHBOR_SCALES)
        return tuple(dict.fromkeys(c for c in found if c != self))


def lookback_grid(
    low: int = GRID_LOW, high: int = GRID_HIGH, ratio: float = GRID_RATIO
) -> list[int]:
    """
    Distinct integer lookbacks from ``low`` to ``high``, each about ``ratio`` times
    the previous, plus the fixed SMA lookbacks, sorted.
    """
    values: set[int] = set(FIXED_SMA_LOOKBACKS)
    x = float(low)
    while round(x) <= high:
        values.add(round(x))
        x *= ratio
    return sorted(values)


def candidate_configs() -> list[RuleConfig]:
    """Every configuration the selection looks at: the SMA grid, then Donchian."""
    configs = [RuleConfig(SMA, (n,)) for n in lookback_grid()]
    configs += [
        RuleConfig(DONCHIAN, DONCHIAN_LOOKBACKS, vol) for vol in DONCHIAN_TARGET_VOLS
    ]
    return configs


# ---------------------------------------------------------------------------
# Decision rule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One condition of the decision rule."""

    name: str
    passed: bool


@dataclass(frozen=True)
class Verdict:
    """The go or no-go of one rule at one cost level."""

    go: bool
    checks: tuple[Check, ...]
    drawdown_warning: bool  # drawdown between -30% and -40%: reported, not failing


def _beats(strategy: float | None, benchmark: float | None) -> bool:
    return strategy is not None and benchmark is not None and strategy > benchmark


def decide(
    strategy: Metrics,
    benchmark: Metrics,
    neighbor_sharpes: Sequence[float],
    deflated_sharpe: float,
) -> Verdict:
    """
    Go only if all of these hold on the test slice, net of costs.

    The conditions are the ones of ``docs/STRATEGY.md`` (v1) and #181: Sharpe and
    Calmar above buy-and-hold's, max drawdown no worse than -40%, positive net
    return, every neighbor lookback keeps at least half of the rule's Sharpe, and a
    deflated Sharpe probability above 0.95.
    """
    plateau = (
        len(neighbor_sharpes) > 0
        and strategy.sharpe > 0
        and all(s >= COLLAPSE_SHARE * strategy.sharpe for s in neighbor_sharpes)
    )
    checks = (
        Check("Net Sharpe above buy-and-hold", strategy.sharpe > benchmark.sharpe),
        Check(
            "Net Calmar above buy-and-hold", _beats(strategy.calmar, benchmark.calmar)
        ),
        Check(
            f"Max drawdown no worse than {MAX_DRAWDOWN_LIMIT:.0%}",
            strategy.max_drawdown >= MAX_DRAWDOWN_LIMIT,
        ),
        Check("Net return positive", strategy.total_return > 0),
        Check(
            "Neighbors within 20% keep at least half of the Sharpe (plateau)", plateau
        ),
        Check(
            f"Deflated Sharpe probability above {DEFLATED_SHARPE_MIN}",
            deflated_sharpe > DEFLATED_SHARPE_MIN,
        ),
    )
    return Verdict(
        go=all(c.passed for c in checks),
        checks=checks,
        drawdown_warning=MAX_DRAWDOWN_LIMIT <= strategy.max_drawdown < DRAWDOWN_WARNING,
    )


# ---------------------------------------------------------------------------
# Study
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigResult:
    """A configuration at the headline cost on both slices."""

    config: RuleConfig
    validation: Metrics
    test: Metrics


@dataclass(frozen=True)
class CostLevel:
    """The test-slice outcome of the winner at one slippage level."""

    slippage: float
    strategy: Metrics
    benchmark: Metrics
    neighbors: tuple[tuple[RuleConfig, Metrics], ...]
    deflated_sharpe: float
    verdict: Verdict


@dataclass(frozen=True)
class WindowComparison:
    """Rolling-window distribution of the winner and of buy-and-hold."""

    label: str
    scope: str
    strategy: WindowSummary
    benchmark: WindowSummary


@dataclass(frozen=True)
class Study:
    """Everything the report prints."""

    first_date: date
    validation_end: date
    test_start: date
    last_date: date
    n_trials: int
    winner: RuleConfig
    family_best: tuple[ConfigResult, ...]
    results: tuple[ConfigResult, ...]
    levels: tuple[CostLevel, ...]
    deflation: tuple[tuple[int, float], ...]
    audit: tuple[tuple[str, Metrics], ...]
    years: tuple[tuple[int, Metrics, Metrics], ...]
    windows: tuple[WindowComparison, ...]

    @property
    def headline(self) -> CostLevel:
        """The level of the headline slippage."""
        return next(x for x in self.levels if x.slippage == HEADLINE_SLIPPAGE)

    @property
    def go(self) -> bool:
        """The decision: the verdict at the headline cost."""
        return self.headline.verdict.go


@dataclass(frozen=True)
class DaySlice:
    """First and last return day, as indexes into the closes, inclusive."""

    first: int
    last: int

    @property
    def n_days(self) -> int:
        return self.last - self.first + 1


class _Simulator:
    """Positions are computed once per configuration and reused at every cost."""

    def __init__(self, closes: Floats) -> None:
        self.closes = closes
        self._positions: dict[RuleConfig, Floats] = {}

    def positions(self, config: RuleConfig | None) -> Floats:
        """Positions of a rule; ``None`` is buy-and-hold."""
        if config is None:
            return np.ones(len(self.closes))
        if config not in self._positions:
            self._positions[config] = config.positions(self.closes)
        return self._positions[config]

    def metrics(
        self, config: RuleConfig | None, costs: Costs, days: DaySlice
    ) -> Metrics:
        return compute_metrics(
            simulate(self.closes, self.positions(config), costs, days.first, days.last)
        )

    def net(self, config: RuleConfig | None, costs: Costs, days: DaySlice) -> Floats:
        return simulate(
            self.closes, self.positions(config), costs, days.first, days.last
        ).net


def _slices(
    dates: Sequence[date],
    warmup: int,
    validation_end: date,
    test_start: date,
) -> tuple[DaySlice, DaySlice]:
    validation = DaySlice(warmup + 1, bisect_right(dates, validation_end) - 1)
    test = DaySlice(max(bisect_left(dates, test_start), 1), len(dates) - 1)
    for name, days in (("validation", validation), ("test", test)):
        if days.n_days < MIN_SLICE_DAYS:
            raise ValueError(
                f"The {name} slice has {max(days.n_days, 0)} days after the "
                f"warm-up; at least {MIN_SLICE_DAYS} are needed"
            )
    if test.first <= validation.last:
        raise ValueError("The test slice must start after the validation slice ends")
    return validation, test


def _first_on_or_after(dates: Sequence[date], day: date) -> int:
    return max(bisect_left(dates, day), 1)


def _years(
    sim: _Simulator,
    dates: Sequence[date],
    winner: RuleConfig,
    costs: Costs,
    first: int,
    last: int,
) -> tuple[tuple[int, Metrics, Metrics], ...]:
    rows = []
    for year in range(dates[first].year, dates[last].year + 1):
        days = DaySlice(
            max(first, _first_on_or_after(dates, date(year, 1, 1))),
            min(last, bisect_left(dates, date(year + 1, 1, 1)) - 1),
        )
        if days.n_days >= 30:
            rows.append(
                (
                    year,
                    sim.metrics(winner, costs, days),
                    sim.metrics(None, costs, days),
                )
            )
    return tuple(rows)


def run_study(
    dates: Sequence[date],
    closes: Floats,
    validation_end: date = VALIDATION_END,
    test_start: date = TEST_START,
) -> Study:
    """
    Run the whole protocol on one daily series.

    Selection reads only validation days: a close dated after ``validation_end``
    cannot change which configuration wins.

    Raises:
        ValueError: If the series and the dates differ in length, or a slice has
            fewer than 365 days.
    """
    if len(dates) != len(closes):
        raise ValueError("dates and closes must have the same length")
    configs = candidate_configs()
    warmup = max(c.warmup_days for c in configs)
    validation, test = _slices(dates, warmup, validation_end, test_start)
    sim = _Simulator(closes)
    headline = Costs(FEE, HEADLINE_SLIPPAGE)

    # 1. Selection, on validation days only.
    validation_metrics = {c: sim.metrics(c, headline, validation) for c in configs}
    family_winners = []
    for family in (SMA, DONCHIAN):
        in_family = [c for c in configs if c.family == family]
        family_winners.append(
            max(in_family, key=lambda c: validation_metrics[c].sharpe)
        )
    winner = max(family_winners, key=lambda c: validation_metrics[c].sharpe)

    # 2. The one run on the test slice: the winner, its neighbors, everyone else.
    neighbors = winner.neighbors()
    tried = list(dict.fromkeys([*configs, *neighbors]))
    n_trials = len(tried)

    def test_metrics(costs: Costs) -> dict[RuleConfig, Metrics]:
        return {c: sim.metrics(c, costs, test) for c in tried}

    headline_test = test_metrics(headline)
    results = tuple(
        ConfigResult(c, validation_metrics[c], headline_test[c]) for c in configs
    )
    family_best = tuple(r for r in results if r.config in family_winners)

    levels = []
    for slippage in SLIPPAGE_LEVELS:
        costs = Costs(FEE, slippage)
        at_cost = test_metrics(costs)
        daily_sharpes = np.array([m.sharpe for m in at_cost.values()]) / math.sqrt(
            TRADING_DAYS_PER_YEAR
        )
        deflated = deflated_sharpe_probability(
            sim.net(winner, costs, test),
            n_trials,
            float(np.var(daily_sharpes, ddof=1)),
        )
        benchmark = sim.metrics(None, costs, test)
        neighbor_metrics = tuple((c, at_cost[c]) for c in neighbors)
        levels.append(
            CostLevel(
                slippage=slippage,
                strategy=at_cost[winner],
                benchmark=benchmark,
                neighbors=neighbor_metrics,
                deflated_sharpe=deflated,
                verdict=decide(
                    at_cost[winner],
                    benchmark,
                    [m.sharpe for _, m in neighbor_metrics],
                    deflated,
                ),
            )
        )

    # How much the verdict leans on the number of trials counted.
    headline_variance = float(
        np.var(
            np.array([m.sharpe for m in headline_test.values()])
            / math.sqrt(TRADING_DAYS_PER_YEAR),
            ddof=1,
        )
    )
    deflation = tuple(
        (
            n,
            deflated_sharpe_probability(
                sim.net(winner, headline, test), n, headline_variance
            ),
        )
        for n in sorted({*(n for n in DEFLATION_TRIALS if n < n_trials), n_trials})
    )

    # 3. Context: sub-periods, rolling windows and the replication of the audit.
    whole = DaySlice(validation.first, test.last)
    windows = []
    for scope, days in (("test slice", test), ("validation and test", whole)):
        for label, length in WINDOWS:
            windows.append(
                WindowComparison(
                    label,
                    scope,
                    summarize_windows(sim.net(winner, headline, days), length),
                    summarize_windows(sim.net(None, headline, days), length),
                )
            )
    audit_days = DaySlice(_first_on_or_after(dates, AUDIT_START), len(dates) - 1)
    audit_rules: list[tuple[str, RuleConfig | None]] = [("Buy and hold", None)]
    audit_rules += [
        (f"Long if close > SMA{n}", RuleConfig(SMA, (n,))) for n in FIXED_SMA_LOOKBACKS
    ]
    audit = tuple(
        (name, sim.metrics(rule, AUDIT_COSTS, audit_days)) for name, rule in audit_rules
    )

    return Study(
        first_date=dates[validation.first],
        validation_end=validation_end,
        test_start=dates[test.first],
        last_date=dates[-1],
        n_trials=n_trials,
        winner=winner,
        family_best=family_best,
        results=results,
        levels=tuple(levels),
        deflation=deflation,
        audit=audit,
        years=_years(sim, dates, winner, headline, validation.first, test.last),
        windows=tuple(windows),
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _metrics_row(label: str, m: Metrics) -> str:
    return (
        f"| {label} | {_pct(m.cagr)} | {_num(m.sharpe)} | {_pct(m.max_drawdown, 0)} "
        f"| {_num(m.calmar)} | {m.trades} | {_num(m.trades_per_year, 1)} "
        f"| {_pct(m.exposure, 0)} |"
    )


METRICS_HEADER = (
    "| | CAGR | Sharpe | Max drawdown | Calmar | Trades | Trades/year | Exposure |\n"
    "|---|---:|---:|---:|---:|---:|---:|---:|"
)


def _windows_rows(study: Study) -> list[str]:
    rows = []
    for w in study.windows:
        for name, summary in (("winner", w.strategy), ("buy and hold", w.benchmark)):
            cells = " | ".join(
                _pct(summary.percentiles.get(p), 1) for p in WINDOW_PERCENTILES
            )
            rows.append(
                f"| {w.scope}, {w.label} | {name} | {summary.n_windows} | {cells} "
                f"| {_pct(summary.share_negative, 0)} |"
            )
    return rows


def format_study(study: Study) -> str:
    """The report as markdown."""
    head = study.headline
    lines = [
        "## Setup",
        "",
        f"- Evaluation days: {study.first_date} to {study.last_date}. Validation up "
        f"to {study.validation_end}, test from {study.test_start}.",
        f"- Configurations tried (the trials of the deflated Sharpe ratio): "
        f"{study.n_trials}.",
        f"- Costs: {FEE:.1%} fee per side plus slippage of "
        f"{', '.join(f'{s:.2%}' for s in SLIPPAGE_LEVELS)}; headline slippage "
        f"{HEADLINE_SLIPPAGE:.2%}.",
        "",
        "## Replication of the audit of 2026-10-03 (fee 0.1%, no slippage)",
        "",
        f"From {AUDIT_START} to {study.last_date}.",
        "",
        METRICS_HEADER,
        *(_metrics_row(name, m) for name, m in study.audit),
        "",
        "## Selection on the validation slice",
        "",
        METRICS_HEADER,
        *(_metrics_row(r.config.name, r.validation) for r in study.family_best),
        "",
        f"Winner: **{study.winner.name}**.",
        "",
        f"## Test slice, headline cost (slippage {HEADLINE_SLIPPAGE:.2%})",
        "",
        METRICS_HEADER,
        _metrics_row(f"{study.winner.name} (winner)", head.strategy),
        _metrics_row("Buy and hold", head.benchmark),
        *(_metrics_row(f"{c.name} (neighbor)", m) for c, m in head.neighbors),
        "",
        "## Test slice at each slippage",
        "",
        "| Slippage | Winner CAGR | Winner Sharpe | Winner Calmar "
        "| Winner max drawdown | Buy-and-hold Sharpe | Buy-and-hold Calmar "
        "| Deflated Sharpe probability | Go |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
        *(
            f"| {x.slippage:.2%} | {_pct(x.strategy.cagr)} | {_num(x.strategy.sharpe)} "
            f"| {_num(x.strategy.calmar)} | {_pct(x.strategy.max_drawdown, 0)} "
            f"| {_num(x.benchmark.sharpe)} | {_num(x.benchmark.calmar)} "
            f"| {_num(x.deflated_sharpe, 3)} | {'yes' if x.verdict.go else 'no'} |"
            for x in study.levels
        ),
        "",
        "## Decision rule at the headline cost",
        "",
        "| Condition | Result |",
        "|---|:---:|",
        *(
            f"| {c.name} | {'pass' if c.passed else 'FAIL'} |"
            for c in head.verdict.checks
        ),
        "",
        f"Drawdown warning (between -30% and -40%): "
        f"{'yes' if head.verdict.drawdown_warning else 'no'}.",
        "",
        f"**Decision: {'GO' if study.go else 'NO-GO'}.**",
        "",
        "## Deflated Sharpe probability by number of trials counted",
        "",
        "Headline cost. The study counted every configuration as an independent "
        "trial, which overstates the number of independent trials when neighboring "
        "lookbacks move together.",
        "",
        "| Trials | Probability |",
        "|---:|---:|",
        *(f"| {n} | {_num(p, 3)} |" for n, p in study.deflation),
        "",
        "## Sub-periods of the winner at the headline cost",
        "",
        "| Year | Winner CAGR | Winner Sharpe | Winner max drawdown "
        "| Buy-and-hold CAGR | Buy-and-hold Sharpe | Buy-and-hold max drawdown |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        *(
            f"| {year} | {_pct(s.cagr)} | {_num(s.sharpe)} | {_pct(s.max_drawdown, 0)} "
            f"| {_pct(b.cagr)} | {_num(b.sharpe)} | {_pct(b.max_drawdown, 0)} |"
            for year, s, b in study.years
        ),
        "",
        "## Rolling windows at the headline cost (compounded return of each window)",
        "",
        "| Windows | | Count | p5 | p25 | p50 | p75 | p95 | Losing |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        *_windows_rows(study),
        "",
        "## Every configuration at the headline cost",
        "",
        "Selection used the validation columns only; the test columns are shown to "
        "judge plateau or spike.",
        "",
        "| Rule | Validation Sharpe | Test Sharpe | Test CAGR | Test max drawdown "
        "| Test trades |",
        "|---|---:|---:|---:|---:|---:|",
        *(
            f"| {r.config.name} | {_num(r.validation.sharpe)} | {_num(r.test.sharpe)} "
            f"| {_pct(r.test.cagr)} | {_pct(r.test.max_drawdown, 0)} "
            f"| {r.test.trades} |"
            for r in study.results
        ),
    ]
    return "\n".join(lines)


def main(
    session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
    symbol: str = DEFAULT_SYMBOL,
) -> int:
    """
    Load the stored daily closes of ``symbol``, run the study and print the report.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    try:
        with session_factory() as db:
            history = load_daily_history(db, symbol)
        closes = np.array([float(c) for c in history.closes], dtype=np.float64)
        study = run_study(history.dates, closes)
        print(f"# Trend-following study on {symbol}\n")
        print(format_study(study))
        return 0
    except ValueError as e:
        logger.error(f"Study failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
