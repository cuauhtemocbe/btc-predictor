"""Tests for the trend-following rules and metrics (#181)."""

import math
from statistics import NormalDist

import numpy as np
import pytest

from scripts.trend_following import (
    EULER_MASCHERONI,
    Costs,
    Simulation,
    compute_metrics,
    deflated_sharpe_probability,
    donchian_positions,
    donchian_state,
    expected_max_sharpe,
    rolling_returns,
    simulate,
    sma_positions,
    summarize_windows,
    volatility_scale,
)


def floats(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


# --- SMA ---------------------------------------------------------------------


def test_sma_is_long_above_the_average_and_cash_otherwise() -> None:
    closes = floats(10, 11, 12, 11, 9, 10, 13)

    # SMA3 ends at index 2: (10+11+12)/3=11, (11+12+11)/3=11.33, (12+11+9)/3=10.67,
    # (11+9+10)/3=10, (9+10+13)/3=10.67
    assert sma_positions(closes, 3).tolist() == [0, 0, 1, 0, 0, 0, 1]


def test_sma_is_cash_during_warm_up_and_when_the_close_equals_the_average() -> None:
    assert sma_positions(floats(5, 5, 5, 5), 3).tolist() == [0, 0, 0, 0]
    assert sma_positions(floats(1, 2), 3).tolist() == [0, 0]


def test_sma_rejects_a_lookback_below_2() -> None:
    with pytest.raises(ValueError, match="lookback"):
        sma_positions(floats(1, 2, 3), 1)


def test_a_later_close_never_changes_an_earlier_sma_position() -> None:
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))
    changed = closes.copy()
    changed[200:] *= rng.uniform(0.5, 2.0, 100)

    assert (sma_positions(closes, 20)[:200] == sma_positions(changed, 20)[:200]).all()


# --- Donchian ----------------------------------------------------------------


def test_donchian_enters_on_a_breakout_and_leaves_below_the_midpoint() -> None:
    # lookback 3. Day 3: close 12 > max(10, 10, 10)=10 -> long.
    # Day 4: channel 10..12, midpoint 11, close 11.5 -> stays long.
    # Day 5: channel (10, 12, 11.5)=10..12, midpoint 11, close 10.5 -> cash.
    closes = floats(10, 10, 10, 12, 11.5, 10.5, 10.4)

    assert donchian_state(closes, 3).tolist() == [0, 0, 0, 1, 1, 0, 0]


def test_donchian_does_not_enter_when_the_close_only_equals_the_high() -> None:
    assert donchian_state(floats(10, 10, 10, 10, 10), 3).tolist() == [0, 0, 0, 0, 0]


def test_a_later_close_never_changes_an_earlier_donchian_position() -> None:
    rng = np.random.default_rng(2)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300)))
    changed = closes.copy()
    changed[200:] *= rng.uniform(0.5, 2.0, 100)

    before = donchian_positions(closes, (10, 30), target_vol=0.4)[:200]
    after = donchian_positions(changed, (10, 30), target_vol=0.4)[:200]
    assert (before == after).all()


def test_the_ensemble_is_the_share_of_channels_that_are_long() -> None:
    # lookback 2 enters on day 2; lookback 4 only when 20 beats every prior close.
    closes = floats(10, 10, 11, 11, 10.5, 20)

    positions = donchian_positions(closes, (2, 4))

    assert positions[2] == 0.5  # only the lookback-2 channel is long
    assert positions[5] == 1.0  # both are long


def test_the_position_follows_the_target_only_in_steps_of_the_rebalance_band() -> None:
    # Long from index 40. Channel 2 leaves at index 42, channels 4 and 30 at index 44,
    # so the target goes 1, 2/3, 0.
    closes = floats(*([10.0] * 40), 20, 19, 17, 15, 12, 9, 9, 9)

    free = donchian_positions(closes, (2, 4, 30), rebalance_band=0.1)
    banded = donchian_positions(closes, (2, 4, 30), rebalance_band=0.5)

    assert free[40:46].tolist() == pytest.approx([1, 1, 2 / 3, 2 / 3, 0, 0])
    assert banded[40:46].tolist() == [1, 1, 1, 1, 0, 0]  # a step of 1/3 is ignored


def test_donchian_needs_lookbacks() -> None:
    with pytest.raises(ValueError, match="empty"):
        donchian_positions(floats(1, 2, 3), ())


def test_volatility_scale_caps_at_one_and_shrinks_with_volatility() -> None:
    rng = np.random.default_rng(3)
    calm = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, 200)))
    wild = 100 * np.exp(np.cumsum(rng.normal(0, 0.08, 200)))

    calm_scale = volatility_scale(calm, 0.4)
    wild_scale = volatility_scale(wild, 0.4)

    assert calm_scale[:30].tolist() == [0.0] * 30
    assert calm_scale[30:].max() == 1.0
    assert wild_scale[30:].max() < 1.0
    assert wild_scale[30:].mean() < calm_scale[30:].mean()


def test_volatility_scale_validates_its_arguments() -> None:
    with pytest.raises(ValueError, match="target_vol"):
        volatility_scale(floats(1, 2, 3), 0.0)
    with pytest.raises(ValueError, match="vol_window"):
        volatility_scale(floats(1, 2, 3), 0.4, vol_window=1)


# --- Simulation --------------------------------------------------------------


def test_a_position_earns_the_return_of_the_next_day_not_of_its_own_day() -> None:
    closes = floats(100, 110, 99, 99)
    positions = floats(1, 0, 0, 0)  # long decided at the close of day 0

    simulation = simulate(closes, positions, Costs(0.0, 0.0), 1, 3)

    assert simulation.net == pytest.approx([0.10, 0.0, 0.0])  # earns day 1 only


def test_fees_and_slippage_are_charged_on_each_change_of_position() -> None:
    closes = floats(100, 100, 100, 100, 100)
    positions = floats(1, 1, 0, 0, 0)
    costs = Costs(fee=0.001, slippage=0.002)

    simulation = simulate(closes, positions, costs, 1, 4)

    # Day 1 buys (0 -> 1), day 2 holds, day 3 sells (1 -> 0), day 4 is cash.
    assert simulation.traded.tolist() == [1, 0, 1, 0]
    assert simulation.net == pytest.approx([-0.003, 0.0, -0.003, 0.0])


def test_a_stretch_that_starts_long_pays_the_entry_and_buy_and_hold_pays_once() -> None:
    closes = floats(100, 100, 100, 100)

    simulation = simulate(closes, np.ones(4), Costs(0.001, 0.0), 1, 3)

    assert simulation.traded.tolist() == [1, 0, 0]
    assert simulation.net == pytest.approx([-0.001, 0.0, 0.0])


def test_fractional_changes_pay_in_proportion() -> None:
    closes = floats(100, 100, 100)
    positions = floats(0.5, 0.25, 0.25)

    simulation = simulate(closes, positions, Costs(0.01, 0.0), 1, 2)

    assert simulation.traded.tolist() == [0.5, 0.25]
    assert simulation.net == pytest.approx([-0.005, -0.0025])


def test_simulate_validates_lengths_and_days() -> None:
    with pytest.raises(ValueError, match="same length"):
        simulate(floats(1, 2, 3), floats(1, 1), Costs(), 1, 2)
    with pytest.raises(ValueError, match="first_day"):
        simulate(floats(1, 2, 3), floats(1, 1, 1), Costs(), 0, 2)
    with pytest.raises(ValueError, match="first_day"):
        simulate(floats(1, 2, 3), floats(1, 1, 1), Costs(), 1, 3)


# --- Metrics -----------------------------------------------------------------


def one_year_of_constant_return() -> Simulation:
    net = np.full(365, 0.001)
    traded = np.zeros(365)
    traded[0] = 1.0
    return Simulation(net=net, held=np.ones(365), traded=traded)


def test_a_constant_daily_return_compounds_into_the_cagr() -> None:
    m = compute_metrics(one_year_of_constant_return())

    assert m.total_return == pytest.approx(1.001**365 - 1)
    assert m.cagr == pytest.approx(1.001**365 - 1)  # exactly one year
    assert m.max_drawdown == 0.0
    assert m.calmar is None
    assert m.sharpe == 0.0  # no variance


def test_max_drawdown_is_the_worst_fall_from_a_peak() -> None:
    net = np.array([0.10, -0.50, 0.20, 0.10])
    m = compute_metrics(
        Simulation(net=net, held=np.ones(4), traded=np.array([1.0, 0, 0, 0]))
    )

    # equity 1.10, 0.55, 0.66, 0.726: worst fall is 1.10 -> 0.55
    assert m.max_drawdown == pytest.approx(-0.5)
    assert m.cagr == pytest.approx(0.726 ** (365 / 4) - 1)
    assert m.calmar == pytest.approx(m.cagr / 0.5)


def test_the_drawdown_counts_a_loss_on_the_first_day() -> None:
    m = compute_metrics(
        Simulation(
            net=np.array([-0.2, 0.1]), held=np.ones(2), traded=np.array([1.0, 0])
        )
    )

    assert m.max_drawdown == pytest.approx(-0.2)


def test_sharpe_is_annualized_with_the_square_root_of_365() -> None:
    net = np.array([0.01, -0.01, 0.02, 0.0])
    m = compute_metrics(
        Simulation(net=net, held=np.ones(4), traded=np.array([1.0, 0, 0, 0]))
    )

    assert m.sharpe == pytest.approx(net.mean() / net.std(ddof=1) * math.sqrt(365))


def test_trades_turnover_and_exposure() -> None:
    held = np.array([1.0, 1.0, 0.5, 0.0])
    traded = np.array([1.0, 0.0, 0.5, 0.5])
    m = compute_metrics(Simulation(net=np.zeros(4), held=held, traded=traded))

    assert m.trades == 3
    assert m.trades_per_year == pytest.approx(3 / (4 / 365))
    assert m.turnover_per_year == pytest.approx(2.0 / (4 / 365))
    assert m.exposure == pytest.approx(0.625)


def test_a_total_loss_is_a_cagr_of_minus_one() -> None:
    m = compute_metrics(
        Simulation(net=np.array([-1.0, 0.5]), held=np.ones(2), traded=np.zeros(2))
    )

    assert m.cagr == -1.0
    assert m.max_drawdown == pytest.approx(-1.0)


def test_metrics_of_no_days_fail() -> None:
    empty = np.array([], dtype=np.float64)
    with pytest.raises(ValueError, match="empty"):
        compute_metrics(Simulation(net=empty, held=empty, traded=empty))


# --- Deflated Sharpe ratio ---------------------------------------------------


def test_one_trial_expects_no_luck() -> None:
    assert expected_max_sharpe(1, 0.5) == 0.0


def test_expected_max_sharpe_follows_the_paper_formula() -> None:
    normal = NormalDist()
    n, variance = 50, 0.04
    expected = math.sqrt(variance) * (
        (1 - EULER_MASCHERONI) * normal.inv_cdf(1 - 1 / n)
        + EULER_MASCHERONI * normal.inv_cdf(1 - 1 / (n * math.e))
    )

    assert expected_max_sharpe(n, variance) == pytest.approx(expected)
    assert expected_max_sharpe(n, variance) > expected_max_sharpe(10, variance) > 0


def test_expected_max_sharpe_validates_its_arguments() -> None:
    with pytest.raises(ValueError, match="n_trials"):
        expected_max_sharpe(0, 0.1)
    with pytest.raises(ValueError, match="variance"):
        expected_max_sharpe(5, -0.1)


def test_more_trials_lower_the_deflated_sharpe_probability() -> None:
    rng = np.random.default_rng(4)
    net = rng.normal(0.001, 0.02, 1000)

    few = deflated_sharpe_probability(net, 2, 0.0004)
    many = deflated_sharpe_probability(net, 200, 0.0004)

    assert 0.0 <= many < few <= 1.0


def test_a_strong_sharpe_is_deflated_to_near_one_and_noise_to_near_zero() -> None:
    rng = np.random.default_rng(5)
    strong = rng.normal(0.01, 0.01, 1000)
    noise = rng.normal(0.0, 0.02, 1000)
    noise = noise - noise.mean()  # a Sharpe ratio of exactly zero

    assert deflated_sharpe_probability(strong, 10, 0.0001) > 0.99
    assert deflated_sharpe_probability(noise, 10, 0.0001) < 0.5


def test_one_trial_reduces_to_the_probabilistic_sharpe_of_zero() -> None:
    rng = np.random.default_rng(6)
    net = rng.normal(0.001, 0.02, 500)
    sharpe = net.mean() / net.std(ddof=1)
    centered = (net - net.mean()) / net.std()
    skew = (centered**3).mean()
    kurt = (centered**4).mean()
    z = (
        sharpe
        * math.sqrt(499)
        / math.sqrt(1 - skew * sharpe + (kurt - 1) / 4 * sharpe**2)
    )

    assert deflated_sharpe_probability(net, 1, 0.0) == pytest.approx(
        NormalDist().cdf(z)
    )


def test_the_deflated_sharpe_needs_a_sample_with_variance() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        deflated_sharpe_probability(floats(0.1, 0.2), 2, 0.1)
    with pytest.raises(ValueError, match="variance"):
        deflated_sharpe_probability(floats(0.1, 0.1, 0.1), 2, 0.1)


# --- Rolling windows ---------------------------------------------------------


def test_rolling_returns_compound_each_window() -> None:
    net = floats(0.10, -0.10, 0.20, 0.0)

    windows = rolling_returns(net, 2)

    assert windows == pytest.approx([1.1 * 0.9 - 1, 0.9 * 1.2 - 1, 1.2 - 1])


def test_rolling_returns_of_a_series_shorter_than_the_window_is_empty() -> None:
    assert len(rolling_returns(floats(0.1, 0.1), 3)) == 0
    with pytest.raises(ValueError, match="window"):
        rolling_returns(floats(0.1), 0)


def test_the_window_summary_gives_percentiles_and_the_share_of_losing_windows() -> None:
    net = np.array([0.01, -0.02] * 50)

    summary = summarize_windows(net, 10)

    assert summary.n_windows == 91
    assert set(summary.percentiles) == {5, 25, 50, 75, 95}
    assert summary.percentiles[5] <= summary.percentiles[50] <= summary.percentiles[95]
    assert summary.share_negative == 1.0  # every 10-day window nets -5 x 1%


def test_the_window_summary_of_a_short_series_has_no_windows() -> None:
    summary = summarize_windows(floats(0.1), 5)

    assert summary.n_windows == 0
    assert summary.percentiles == {}
    assert summary.share_negative is None
