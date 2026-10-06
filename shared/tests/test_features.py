"""
Tests for the return-based feature builder (#104).

Covers the builder-level Gherkin scenarios of "Return-based next-day prediction":
price-level invariance, no lookahead, the 7-day target, insufficient history and
invalid data. The scenarios that involve the trainers and predictors live in
workers/daily/tests/test_return_prediction.py.
"""

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from shared.features import (
    build_prediction_features,
    build_training_set,
    feature_count,
    price_from_return,
    require_fresh_series,
    require_recent_close,
    required_history_days,
)

WINDOW = 10


def _random_walk(days: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    closes = 60000 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
    volumes = 1000 * np.exp(rng.normal(0, 0.2, days))
    return closes, volumes


class TestFeaturesDoNotDependOnThePriceLevel:
    """Scenario: two histories with the same daily returns, one scaled by 1.5."""

    def test_feature_matrices_are_equal(self) -> None:
        closes, volumes = _random_walk(60)

        base = build_training_set(closes, volumes, WINDOW)
        scaled = build_training_set(closes * 1.5, volumes, WINDOW)

        assert np.allclose(base.X, scaled.X)
        assert np.allclose(base.y, scaled.y)

    def test_prediction_features_are_equal(self) -> None:
        closes, volumes = _random_walk(60)

        base = build_prediction_features(closes, volumes, WINDOW)
        scaled = build_prediction_features(closes * 1.5, volumes, WINDOW)

        assert np.allclose(base, scaled)


class TestFeaturesUseNoFutureData:
    """Scenario: changing any price after day t does not change day t's features."""

    def test_changing_later_closes_and_volumes_keeps_earlier_rows(self) -> None:
        closes, volumes = _random_walk(60)
        # Row k of the training set is the day at index k + WINDOW
        t = 35
        row = t - WINDOW

        changed_closes, changed_volumes = closes.copy(), volumes.copy()
        changed_closes[t + 1 :] *= 3.0
        changed_volumes[t + 1 :] *= 0.1

        original = build_training_set(closes, volumes, WINDOW)
        changed = build_training_set(changed_closes, changed_volumes, WINDOW)

        assert np.array_equal(original.X[: row + 1], changed.X[: row + 1])
        # The sanity check that the change is visible further on
        assert not np.array_equal(original.X[row + 1 :], changed.X[row + 1 :])

    def test_prediction_features_ignore_rows_older_than_the_window(self) -> None:
        closes, volumes = _random_walk(60)
        older_changed = closes.copy()
        older_changed[:20] *= 5.0

        original = build_prediction_features(closes, volumes, WINDOW)
        changed = build_prediction_features(older_changed, volumes, WINDOW)

        assert np.array_equal(original, changed)


class TestFeatureLayout:
    def test_columns_are_returns_volatility_and_volume_changes(self) -> None:
        closes, volumes = _random_walk(30)

        X = build_prediction_features(closes, volumes, WINDOW)[0]

        returns = np.diff(np.log(closes))[-WINDOW:]
        volume_changes = np.diff(np.log(volumes))[-WINDOW:]
        assert X.shape == (feature_count(WINDOW),)
        assert np.allclose(X[:WINDOW], returns)
        assert X[WINDOW] == pytest.approx(returns.std())
        assert np.allclose(X[WINDOW + 1 :], volume_changes)

    def test_training_set_shapes(self) -> None:
        closes, volumes = _random_walk(60)

        training = build_training_set(closes, volumes, WINDOW)

        # 60 rows - 10 window - 1 horizon
        assert training.X.shape == (49, 21)
        assert training.y.shape == (49,)
        assert training.base_close.shape == (49,)

    def test_target_is_the_next_day_log_return(self) -> None:
        closes, volumes = _random_walk(60)

        training = build_training_set(closes, volumes, WINDOW)

        # Sample 0 is the day at index WINDOW; its target is the move to the next day
        assert training.base_close[0] == pytest.approx(closes[WINDOW])
        assert training.y[0] == pytest.approx(
            math.log(closes[WINDOW + 1] / closes[WINDOW])
        )
        assert training.y[-1] == pytest.approx(math.log(closes[-1] / closes[-2]))

    def test_accepts_decimals(self) -> None:
        closes, volumes = _random_walk(30)

        from_decimals = build_prediction_features(
            [Decimal(str(c)) for c in closes],
            [Decimal(str(v)) for v in volumes],
            WINDOW,
        )

        assert np.allclose(
            from_decimals, build_prediction_features(closes, volumes, WINDOW)
        )


class TestWeeklyTarget:
    """Scenario: the weekly worker builds a 7-day target."""

    def test_each_target_is_the_sum_of_the_next_7_daily_log_returns(self) -> None:
        closes, volumes = _random_walk(60)
        daily_returns = np.diff(np.log(closes))

        training = build_training_set(closes, volumes, WINDOW, horizon_days=7)

        # 60 rows - 10 window - 7 horizon
        assert len(training.y) == 43
        for k in (0, 10, 42):
            day = WINDOW + k  # index of the day the sample was built at
            assert training.y[k] == pytest.approx(daily_returns[day : day + 7].sum())
        assert training.y[-1] == pytest.approx(math.log(closes[-1] / closes[-8]))

    def test_features_do_not_depend_on_the_horizon(self) -> None:
        closes, volumes = _random_walk(60)

        daily = build_training_set(closes, volumes, WINDOW, horizon_days=1)
        weekly = build_training_set(closes, volumes, WINDOW, horizon_days=7)

        assert np.array_equal(daily.X[: len(weekly.X)], weekly.X)


class TestInsufficientHistory:
    """Scenario: fewer rows than the window plus one are rejected, naming the days."""

    def test_names_required_and_available_days_for_prediction(self) -> None:
        closes, volumes = _random_walk(WINDOW)  # one short of window + 1

        with pytest.raises(ValueError, match=r"need 11 daily rows.*have 10"):
            build_prediction_features(closes, volumes, WINDOW)

    def test_exactly_window_plus_one_rows_is_enough(self) -> None:
        closes, volumes = _random_walk(WINDOW + 1)

        assert build_prediction_features(closes, volumes, WINDOW).shape == (1, 21)

    def test_training_needs_the_horizon_on_top(self) -> None:
        closes, volumes = _random_walk(WINDOW + 7)

        with pytest.raises(ValueError, match=r"need 18 daily rows.*have 17"):
            build_training_set(closes, volumes, WINDOW, horizon_days=7)

        one_sample = build_training_set(
            *_random_walk(WINDOW + 8), WINDOW, horizon_days=7
        )
        assert len(one_sample.y) == 1

    def test_required_history_days(self) -> None:
        assert required_history_days(21) == 22
        assert required_history_days(21, horizon_days=7) == 29


class TestInvalidDataIsRejected:
    """Scenario Outline: zero close, zero volume and missing close fail the build."""

    @staticmethod
    def _series_with(problem: str) -> tuple[list[Any], list[Any]]:
        close_array, volume_array = _random_walk(40)
        closes: list[Any] = list(close_array)
        volumes: list[Any] = list(volume_array)
        if problem == "zero close price":
            closes[20] = 0
        elif problem == "zero volume":
            volumes[20] = 0
        elif problem == "missing close":
            closes[20] = None
        return closes, volumes

    @pytest.mark.parametrize(
        ("problem", "message"),
        [
            ("zero close price", "Invalid close"),
            ("zero volume", "Invalid volume"),
            ("missing close", "Invalid close"),
        ],
    )
    def test_training_set_fails(self, problem: str, message: str) -> None:
        closes, volumes = self._series_with(problem)

        with pytest.raises(ValueError, match=message):
            build_training_set(closes, volumes, WINDOW)

    @pytest.mark.parametrize("problem", ["zero close price", "zero volume"])
    def test_prediction_features_fail_when_the_bad_row_is_in_the_window(
        self, problem: str
    ) -> None:
        close_array, volume_array = _random_walk(40)
        closes: list[Any] = list(close_array)
        volumes: list[Any] = list(volume_array)
        if problem == "zero close price":
            closes[-3] = 0
        else:
            volumes[-3] = 0

        with pytest.raises(ValueError, match="Invalid"):
            build_prediction_features(closes, volumes, WINDOW)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
    def test_non_finite_and_negative_values_fail(self, bad: float) -> None:
        closes, volumes = _random_walk(40)
        closes[10] = bad

        with pytest.raises(ValueError, match="Invalid close"):
            build_training_set(closes, volumes, WINDOW)

    def test_mismatched_lengths_fail(self) -> None:
        closes, volumes = _random_walk(40)

        with pytest.raises(ValueError, match="same length"):
            build_training_set(closes, volumes[:-1], WINDOW)

    def test_valid_data_never_produces_non_finite_values(self) -> None:
        closes, volumes = _random_walk(200)

        training = build_training_set(closes, volumes, WINDOW)

        assert np.isfinite(training.X).all()
        assert np.isfinite(training.y).all()


class TestPriceFromReturn:
    """Scenario: the stored price comes from the predicted return."""

    def test_plus_one_percent_on_84000(self) -> None:
        price = price_from_return(Decimal("84000"), 0.01)

        assert price == pytest.approx(84000 * math.exp(0.01))
        assert price > 84000  # direction up

    def test_negative_return_is_below_the_last_close(self) -> None:
        assert price_from_return(84000, -0.02) == pytest.approx(84000 * math.exp(-0.02))
        assert price_from_return(84000, -0.02) < 84000

    def test_zero_return_keeps_the_last_close(self) -> None:
        assert price_from_return(84000, 0.0) == 84000

    def test_missing_last_close_fails(self) -> None:
        with pytest.raises(ValueError, match="last_close"):
            price_from_return(None, 0.01)


class TestRequireFreshSeries:
    """Scenarios of #174: a stale series or one with gaps is refused."""

    TODAY = date(2026, 10, 6)

    @staticmethod
    def _days(first: date, count: int) -> list[date]:
        return [first + timedelta(days=i) for i in range(count)]

    def test_complete_series_ending_yesterday_passes(self) -> None:
        require_fresh_series(self._days(date(2026, 9, 6), 30), self.TODAY)

    def test_a_series_ending_two_days_ago_names_the_missing_day(self) -> None:
        dates = self._days(date(2026, 9, 5), 30)  # last bar: 2026-10-04

        with pytest.raises(
            ValueError, match=r"latest bar is dated 2026-10-04.*2026-10-05"
        ):
            require_fresh_series(dates, self.TODAY)

    def test_a_series_ending_today_is_refused(self) -> None:
        with pytest.raises(ValueError, match="expected 2026-10-05"):
            require_fresh_series(self._days(date(2026, 9, 7), 30), self.TODAY)

    def test_a_gap_inside_the_window_names_the_missing_date(self) -> None:
        dates = self._days(date(2026, 9, 6), 30)
        dates.remove(date(2026, 9, 20))

        with pytest.raises(ValueError, match="2026-09-20") as error:
            require_fresh_series(dates, self.TODAY)

        assert "2026-09-21" not in str(error.value)

    def test_several_missing_dates_are_all_named(self) -> None:
        dates = [d for d in self._days(date(2026, 9, 6), 30) if d.day not in (10, 11)]

        with pytest.raises(ValueError, match="2026-09-10, 2026-09-11"):
            require_fresh_series(dates, self.TODAY)

    def test_an_empty_series_is_refused(self) -> None:
        with pytest.raises(ValueError, match="No stored bars"):
            require_fresh_series([], self.TODAY)


class TestRequireRecentClose:
    """The last bar must have closed at most ``max_age`` before the run (#175)."""

    BAR = date(2026, 10, 3)  # closed at 2026-10-04 00:00 UTC
    MAX_AGE = timedelta(hours=2)

    def test_ten_minutes_after_the_close_passes(self) -> None:
        now = datetime(2026, 10, 4, 0, 10, tzinfo=UTC)
        require_recent_close(self.BAR, now, self.MAX_AGE)

    def test_exactly_the_maximum_age_passes(self) -> None:
        now = datetime(2026, 10, 4, 2, 0, tzinfo=UTC)
        require_recent_close(self.BAR, now, self.MAX_AGE)

    def test_one_second_over_the_maximum_age_raises(self) -> None:
        now = datetime(2026, 10, 4, 2, 0, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="maximum age is 2:00:00"):
            require_recent_close(self.BAR, now, self.MAX_AGE)

    def test_seven_hours_after_the_close_raises_naming_the_bar(self) -> None:
        now = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match=r"2026-10-03.*2026-10-04 00:00 UTC"):
            require_recent_close(self.BAR, now, self.MAX_AGE)
