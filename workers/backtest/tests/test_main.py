"""
Tests for the monthly backtest cron (#138).

Gherkin: "Monthly backtest cron uses the production configuration".
"""

import sys
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol

import pytest
from sqlalchemy.orm import Session

import scripts.backtest as worker_script
import workers.backtest.main as worker
from scripts.backtest_engine import DailyHistory, InsufficientHistoryError
from shared.config import settings
from shared.db.models import Price
from workers.daily.trainer import required_training_days

FIRST_DAY = date(2022, 1, 1)


def history(days: int) -> DailyHistory:
    dates = [FIRST_DAY + timedelta(days=i) for i in range(days)]
    return DailyHistory(
        dates=dates,
        closes=[Decimal(30000 + i) for i in range(days)],
        volumes=[Decimal(1000)] * days,
    )


def arguments_of(argv: list[str]) -> dict[str, str]:
    return dict(arg.removeprefix("--").split("=") for arg in argv[1:])


class CronRunner(Protocol):
    """Callable returned by the ``cron`` fixture."""

    def __call__(self, daily_history: DailyHistory, exit_code: int = 0) -> list[str]:
        """Run the cron against ``daily_history`` and return the argv it built."""
        ...


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> CronRunner:
    """Run worker.main() against a given history; return the argv it passed on."""
    captured: dict[str, list[str]] = {}

    def run(daily_history: DailyHistory, exit_code: int = 0) -> list[str]:
        monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(None))
        monkeypatch.setattr(worker, "load_daily_history", lambda db: daily_history)

        def fake_backtest() -> int:
            captured["argv"] = list(sys.argv)
            return exit_code

        monkeypatch.setattr(worker, "run_backtest_main", fake_backtest)
        worker.main()
        return captured["argv"]

    return run


# --- Scenario: The cron uses the production training window ---


def test_the_cron_passes_the_production_training_window(
    cron: CronRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given TRAINING_WINDOW_DAYS is 21
    monkeypatch.setattr(settings, "training_window_days", 21)

    # When the backtest worker builds its arguments
    argv = cron(history(1000))

    # Then it passes --training-window=21
    assert "--training-window=21" in argv


def test_the_cron_follows_a_changed_production_window(
    cron: CronRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "training_window_days", 30)

    assert "--training-window=30" in cron(history(1000))


# --- Scenario: The cron derives its range from the engine's history requirement ---


def test_the_start_date_is_not_earlier_than_the_earliest_allowed(
    cron: CronRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given 1000 loaded daily rows
    monkeypatch.setattr(settings, "training_window_days", 21)
    loaded = history(1000)

    # When the backtest worker chooses its date range
    args = arguments_of(cron(loaded))

    # Then the start date is not earlier than the earliest allowed start date
    earliest = loaded.dates[required_training_days(21)]
    assert date.fromisoformat(args["start-date"]) >= earliest
    assert date.fromisoformat(args["end-date"]) == loaded.dates[-1]


def test_a_short_history_starts_exactly_at_the_earliest_allowed_date() -> None:
    loaded = history(required_training_days(21) + worker.TEST_DAYS + 5)

    start, _, _ = worker.plan_range(loaded, 21)

    assert start == loaded.dates[required_training_days(21)]


def test_a_long_history_is_limited_to_the_lookback(cron: CronRunner) -> None:
    loaded = history(3000)

    args = arguments_of(cron(loaded))

    start, end = date.fromisoformat(args["start-date"]), loaded.dates[-1]
    assert (end - start).days + 1 == worker.LOOKBACK_DAYS


# --- Scenario: Too little history fails with the engine's message ---


def test_too_little_history_exits_one_with_the_engine_message(
    cron: CronRunner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given fewer daily rows than (window + 1) * 5
    monkeypatch.setattr(settings, "training_window_days", 21)
    too_short = history(required_training_days(21) - 1)

    # When the backtest worker runs
    with pytest.raises(SystemExit) as exit_info:
        cron(too_short)

    # Then it exits with code 1
    assert exit_info.value.code == 1
    # And the log states that no start date has enough history
    assert "no start date has enough history" in caplog.text


def test_enough_rows_but_a_short_test_slice_exits_one_with_the_earliest_date(
    cron: CronRunner, caplog: pytest.LogCaptureFixture
) -> None:
    needed = required_training_days(21)
    loaded = history(needed + 50)

    with pytest.raises(SystemExit) as exit_info:
        cron(loaded)

    assert exit_info.value.code == 1
    assert str(loaded.dates[needed]) in caplog.text


def test_no_prices_at_all_exits_one(
    cron: CronRunner, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cron(DailyHistory(dates=[], closes=[], volumes=[]))

    assert exit_info.value.code == 1
    assert "No BTCUSDT prices are loaded" in caplog.text


def test_plan_range_raises_the_engine_error() -> None:
    with pytest.raises(InsufficientHistoryError):
        worker.plan_range(history(10), 21)


# --- Scenario: The range is long enough to report an out-of-sample result ---


def test_the_test_slice_has_at_least_100_days(cron: CronRunner) -> None:
    # Given enough history
    loaded = history(1000)

    # When the backtest worker chooses its date range
    args = arguments_of(cron(loaded))

    # Then the test slice has at least 100 days
    test_start = date.fromisoformat(args["test-start-date"])
    end = date.fromisoformat(args["end-date"])
    assert (end - test_start).days + 1 >= 100
    assert date.fromisoformat(args["start-date"]) < test_start


# --- Scenario: The cron run is reproducible and labelled ---


def test_the_cron_passes_an_explicit_seed_and_retrain_frequency(
    cron: CronRunner,
) -> None:
    args = arguments_of(cron(history(1000)))

    assert args["seed"] == "42"
    assert args["retrain-every"] == "1"


def test_the_report_of_a_cron_run_shows_seed_and_retrain_every(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given a small history and a small test slice
    monkeypatch.setattr(settings, "training_window_days", 3)
    monkeypatch.setattr(worker, "TEST_DAYS", 5)
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db_session))
    needed = required_training_days(3)
    db_session.add_all(
        Price(
            timestamp=datetime.combine(
                FIRST_DAY + timedelta(days=i), time(0, 0), tzinfo=UTC
            ),
            open=Decimal(30000 + i * 7 % 50),
            high=Decimal(30000 + i * 7 % 50),
            low=Decimal(30000 + i * 7 % 50),
            close=Decimal(30000 + i * 7 % 50),
            volume=Decimal(1000 + i),
            source="test",
        )
        for i in range(needed + 20)
    )
    db_session.commit()
    # backtest.main binds SessionLocal as a default argument, so patch the call
    monkeypatch.setattr(
        worker,
        "run_backtest_main",
        lambda: worker_script.main(session_factory=lambda: nullcontext(db_session)),
    )

    # When the worker runs the whole backtest
    worker.main()

    # Then the printed report shows both
    out = capsys.readouterr().out
    assert "seed: 42" in out
    assert "retrain every: 1" in out


def test_the_cron_backtests_the_linear_model(cron: CronRunner) -> None:
    # Given the cron passes no --model, the script default decides the model
    argv = cron(history(1000))

    # Then it is the linear model that production trains (#124)
    assert "--model" not in " ".join(argv)
    assert worker_script.parse_arguments(argv[1:]).model == "linear"


# --- Scenario (#173): an empty history ends the range on the UTC day ---


@pytest.mark.usefixtures("mexico_city_at_0010_utc")
def test_without_history_the_range_ends_on_the_utc_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With TZ=America/Mexico_City at 2026-10-04 00:10 UTC the end date is the 4th."""
    ends: list[date] = []
    monkeypatch.setattr(
        worker,
        "check_enough_history",
        lambda daily_history, config: ends.append(config.end_date),
    )

    _, end, _ = worker.plan_range(DailyHistory(dates=[], closes=[], volumes=[]), 21)

    assert end == date(2026, 10, 4)
    assert ends == [date(2026, 10, 4)]
