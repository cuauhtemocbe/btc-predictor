"""Tests for the trend-following study protocol (#181)."""

import dataclasses
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
import pytest
from sqlalchemy.orm import Session

from scripts import trend_study
from scripts.trend_following import Metrics
from scripts.trend_study import (
    DONCHIAN,
    SMA,
    RuleConfig,
    candidate_configs,
    decide,
    format_study,
    lookback_grid,
    run_study,
)
from shared.db.models import Price

START = date(2019, 1, 1)
END = date(2025, 6, 30)
DAYS = (END - START).days + 1
DATES = [START + timedelta(days=i) for i in range(DAYS)]


def random_walk(seed: int = 7) -> npt.NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.03, DAYS)))


def metrics(**overrides: float | int | None) -> Metrics:
    base = Metrics(
        n_days=900,
        total_return=0.8,
        cagr=0.25,
        sharpe=1.2,
        max_drawdown=-0.25,
        calmar=1.0,
        trades=30,
        trades_per_year=12.0,
        turnover_per_year=12.0,
        exposure=0.6,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


BENCHMARK = metrics(sharpe=0.9, calmar=0.5, max_drawdown=-0.6, total_return=1.0)


# --- Grid and configurations -------------------------------------------------


def test_the_lookback_grid_is_sorted_distinct_and_keeps_the_fixed_lookbacks() -> None:
    grid = lookback_grid()

    assert grid == sorted(set(grid))
    assert {50, 100, 200} <= set(grid)
    assert grid[0] == 20
    assert grid[-1] <= 300
    steps = [b / a for a, b in zip(grid, grid[1:], strict=False)]
    assert max(steps) <= 1.2  # fine enough for a plateau within 20%


def test_candidates_are_the_sma_grid_then_the_donchian_variants() -> None:
    configs = candidate_configs()

    assert [c.lookbacks[0] for c in configs if c.family == SMA] == lookback_grid()
    assert len([c for c in configs if c.family == DONCHIAN]) == 4
    assert len(set(configs)) == len(configs)


def test_neighbors_scale_every_lookback_by_20_percent() -> None:
    sma = RuleConfig(SMA, (100,))
    ensemble = RuleConfig(DONCHIAN, (10, 20, 40), 0.4)

    assert sma.neighbors() == (RuleConfig(SMA, (80,)), RuleConfig(SMA, (120,)))
    assert ensemble.neighbors() == (
        RuleConfig(DONCHIAN, (8, 16, 32), 0.4),
        RuleConfig(DONCHIAN, (12, 24, 48), 0.4),
    )


def test_neighbors_leave_out_the_rule_itself_and_duplicates() -> None:
    tiny = RuleConfig(SMA, (2,))  # 2 * 0.8 rounds to 2, 2 * 1.2 rounds to 2

    assert tiny.neighbors() == ()


def test_warm_up_is_the_first_day_a_rule_can_be_long() -> None:
    assert RuleConfig(SMA, (200,)).warmup_days == 199
    assert RuleConfig(DONCHIAN, (10, 160)).warmup_days == 160
    assert RuleConfig(DONCHIAN, (10, 20), 0.4).warmup_days == 30


def test_names_say_what_the_rule_is() -> None:
    assert RuleConfig(SMA, (100,)).name == "SMA100"
    assert RuleConfig(DONCHIAN, (10, 20), None).name == "Donchian 10/20, no sizing"
    assert RuleConfig(DONCHIAN, (10, 20), 0.45).name == "Donchian 10/20, vol 45%"


# --- Decision rule -----------------------------------------------------------


def verdict(**overrides: float | int | None) -> trend_study.Verdict:
    return decide(metrics(**overrides), BENCHMARK, [1.0, 0.9], 0.97)


def failed(v: trend_study.Verdict) -> list[str]:
    return [c.name for c in v.checks if not c.passed]


def test_a_rule_that_meets_every_condition_is_a_go() -> None:
    v = verdict()

    assert v.go
    assert failed(v) == []
    assert not v.drawdown_warning


@pytest.mark.parametrize(
    ("overrides", "failing"),
    [
        ({"sharpe": 0.9}, "Net Sharpe above buy-and-hold"),
        ({"calmar": 0.5}, "Net Calmar above buy-and-hold"),
        ({"calmar": None}, "Net Calmar above buy-and-hold"),
        ({"max_drawdown": -0.41}, "Max drawdown no worse than -40%"),
        ({"total_return": 0.0}, "Net return positive"),
    ],
)
def test_each_metric_condition_alone_makes_it_a_no_go(
    overrides: dict[str, float | None], failing: str
) -> None:
    v = verdict(**overrides)

    assert not v.go
    assert failed(v) == [failing]


def test_the_drawdown_limit_is_inclusive_and_the_warning_starts_at_30_percent() -> None:
    assert verdict(max_drawdown=-0.40).go
    assert verdict(max_drawdown=-0.40).drawdown_warning
    assert verdict(max_drawdown=-0.30).go
    assert not verdict(max_drawdown=-0.30).drawdown_warning
    assert not verdict(max_drawdown=-0.29).drawdown_warning


def test_a_collapsing_neighbor_is_a_spike_and_a_no_go() -> None:
    # The winner's Sharpe is 1.2: half is 0.6.
    on_the_edge = decide(metrics(), BENCHMARK, [0.6, 1.2], 0.97)
    collapsed = decide(metrics(), BENCHMARK, [0.59, 1.2], 0.97)

    assert on_the_edge.go
    assert not collapsed.go
    assert failed(collapsed) == [
        "Neighbors within 20% keep at least half of the Sharpe (plateau)"
    ]


def test_without_neighbors_or_with_a_negative_sharpe_there_is_no_plateau() -> None:
    assert not decide(metrics(), BENCHMARK, [], 0.97).go
    losing = decide(metrics(sharpe=-0.5), BENCHMARK, [-0.1], 0.97)
    assert "Neighbors within 20% keep at least half of the Sharpe (plateau)" in failed(
        losing
    )


def test_the_deflated_sharpe_probability_must_be_above_95_percent() -> None:
    assert not decide(metrics(), BENCHMARK, [1.0], 0.95).go
    assert decide(metrics(), BENCHMARK, [1.0], 0.951).go


# --- Study -------------------------------------------------------------------


def test_the_study_reports_three_slippage_levels_and_counts_every_trial() -> None:
    study = run_study(DATES, random_walk())

    assert [x.slippage for x in study.levels] == [0.0005, 0.001, 0.002]
    assert study.headline.slippage == 0.001
    tried = set(candidate_configs()) | set(study.winner.neighbors())
    assert study.n_trials == len(tried)
    assert len(study.results) == len(candidate_configs())
    assert study.go == study.headline.verdict.go


def test_the_winner_is_the_best_validation_sharpe_of_the_family_winners() -> None:
    study = run_study(DATES, random_walk())

    best_of_each = {
        family: max(
            (r for r in study.results if r.config.family == family),
            key=lambda r: r.validation.sharpe,
        )
        for family in (SMA, DONCHIAN)
    }
    expected = max(best_of_each.values(), key=lambda r: r.validation.sharpe)
    assert study.winner == expected.config
    assert {r.config for r in study.family_best} == {
        r.config for r in best_of_each.values()
    }


def test_the_deflation_table_ends_at_the_headline_and_falls_with_trials() -> None:
    study = run_study(DATES, random_walk())

    trials = [n for n, _ in study.deflation]
    probabilities = [p for _, p in study.deflation]
    assert trials == sorted(set(trials))
    assert trials[0] == 1
    assert trials[-1] == study.n_trials
    assert probabilities == sorted(probabilities, reverse=True)
    assert probabilities[-1] == pytest.approx(study.headline.deflated_sharpe)


def test_slippage_only_lowers_the_winner_and_leaves_buy_and_hold_with_one_entry() -> (
    None
):
    study = run_study(DATES, random_walk())

    cagrs = [x.strategy.cagr for x in study.levels]
    assert cagrs == sorted(cagrs, reverse=True)
    assert all(x.benchmark.trades == 1 for x in study.levels)


def test_closes_after_the_validation_slice_never_change_the_selection() -> None:
    closes = random_walk()
    study = run_study(DATES, closes)
    boundary = DATES.index(trend_study.TEST_START)
    other = closes.copy()
    other[boundary:] *= np.random.default_rng(99).uniform(0.4, 2.5, DAYS - boundary)

    changed = run_study(DATES, other)

    assert changed.winner == study.winner
    assert [r.validation for r in changed.results] == [
        r.validation for r in study.results
    ]
    # The test slice does change, so the check above is not vacuous.
    assert [r.test for r in changed.results] != [r.test for r in study.results]


def test_the_winner_runs_on_the_test_slice_from_cash_and_buy_and_hold_enters_once() -> (
    None
):
    study = run_study(DATES, random_walk())

    test_days = (END - trend_study.TEST_START).days + 1
    assert study.headline.strategy.n_days == test_days
    assert study.headline.benchmark.n_days == test_days
    assert study.headline.benchmark.exposure == 1.0


def test_sub_periods_cover_whole_years_of_the_evaluation_and_windows_are_reported() -> (
    None
):
    study = run_study(DATES, random_walk())

    years = [year for year, _, _ in study.years]
    assert years == list(range(years[0], 2026))
    assert years[0] in (2019, 2020)
    assert {(w.scope, w.label) for w in study.windows} == {
        ("test slice", "1 month"),
        ("test slice", "3 months"),
        ("validation and test", "1 month"),
        ("validation and test", "3 months"),
    }
    assert all(w.strategy.n_windows > 0 for w in study.windows)


def test_the_audit_replication_covers_buy_and_hold_and_the_three_fixed_smas() -> None:
    study = run_study(DATES, random_walk())

    assert [name for name, _ in study.audit] == [
        "Buy and hold",
        "Long if close > SMA50",
        "Long if close > SMA100",
        "Long if close > SMA200",
    ]
    assert study.audit[0][1].trades == 1


def test_a_series_too_short_for_the_validation_slice_fails() -> None:
    with pytest.raises(ValueError, match=r"validation slice has \d+ days"):
        run_study(DATES[:400], random_walk()[:400])


def test_a_series_that_ends_before_the_test_slice_fails() -> None:
    with pytest.raises(ValueError, match="test slice has 0 days"):
        run_study(DATES[:800], random_walk()[:800])


def test_a_test_slice_that_overlaps_the_validation_slice_fails() -> None:
    with pytest.raises(ValueError, match="test slice must start after"):
        run_study(DATES, random_walk(), test_start=date(2023, 6, 1))


def test_a_test_slice_of_less_than_a_year_fails() -> None:
    with pytest.raises(ValueError, match="test slice"):
        run_study(DATES, random_walk(), test_start=date(2025, 3, 1))


def test_dates_and_closes_must_have_the_same_length() -> None:
    with pytest.raises(ValueError, match="same length"):
        run_study(DATES, random_walk()[:-1])


# --- Report and command ------------------------------------------------------


def test_the_report_states_the_decision_the_study_reached() -> None:
    study = run_study(DATES, random_walk())

    report = format_study(study)

    assert f"**Decision: {'GO' if study.go else 'NO-GO'}.**" in report
    for heading in (
        "## Replication of the audit",
        "## Selection on the validation slice",
        "## Test slice at each slippage",
        "## Deflated Sharpe probability by number of trials counted",
        "## Decision rule at the headline cost",
        "## Rolling windows",
        "## Every configuration at the headline cost",
    ):
        assert heading in report
    assert study.winner.name in report
    assert report.count("| pass |") + report.count("| FAIL |") == 6


def seed_btc(db_session: Session, days: int) -> None:
    closes = random_walk()[:days]
    db_session.add_all(
        Price(
            timestamp=datetime.combine(DATES[i], time(0, 0)).replace(tzinfo=UTC),
            open=Decimal(f"{closes[i]:.2f}"),
            high=Decimal(f"{closes[i]:.2f}"),
            low=Decimal(f"{closes[i]:.2f}"),
            close=Decimal(f"{closes[i]:.2f}"),
            volume=Decimal("1000"),
            source="test",
        )
        for i in range(days)
    )
    db_session.commit()


def test_the_command_prints_the_report_of_the_stored_series(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_btc(db_session, DAYS)

    code = trend_study.main(session_factory=lambda: nullcontext(db_session))

    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("# Trend-following study on BTCUSDT")
    assert "**Decision:" in out


def test_the_command_fails_with_exit_1_when_the_history_is_too_short(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    seed_btc(db_session, 400)

    code = trend_study.main(session_factory=lambda: nullcontext(db_session))

    assert code == 1
    assert "validation slice" in caplog.text


def test_the_command_fails_with_exit_1_when_nothing_is_stored(
    db_session: Session,
) -> None:
    assert trend_study.main(session_factory=lambda: nullcontext(db_session)) == 1
