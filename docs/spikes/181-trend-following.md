# Spike #181: do simple trend rules beat buy-and-hold after fees, and is the result robust enough to paper-trade?

**Decision: no-go, by the rule fixed before the run.** The winning rule, a 122-day simple moving average chosen on the validation slice, passes five of the six conditions of `docs/STRATEGY.md` and #181 (Sharpe, Calmar, drawdown, positive return, plateau) and fails the sixth: its deflated Sharpe probability is 0.863, below the 0.95 the rule requires. The shortfall does not come from counting many trials: with one trial and no deflation at all the probability is 0.941. The 974 days of the test slice cannot show, at 95%, that a Sharpe ratio of 0.94 is above zero.

Date: 2026-11-22. Code: `scripts/trend_following.py` (rules and metrics) and `scripts/trend_study.py` (protocol and report), with tests. Nothing is written to the database. Data: `BTCUSDT` daily bars as stored, 2017-08-17 to 2026-08-31.

On 2026-11-22 the owner overrode the no-go for paper-trading only, with conditions for real money, pause and archive. They are in `docs/STRATEGY.md`, "Override of the #181 no-go". This document records the result of the spike, not the override.

## Method

- **Rules.** Long or cash, spot, no leverage.
  - `SMA(n)`: long while the close is above the mean of the last `n` closes, today's included. The grid is 32 lookbacks from 20 to 288, each about 10% above the previous, plus 50, 100 and 200.
  - Donchian ensemble: five channels (10, 20, 40, 80, 160 days) on closes. A channel enters when the close is above the highest close of the previous `n` days and leaves below the midpoint of that channel. The position is the share of channels that are long, optionally multiplied by `min(1, target volatility / 30-day realized volatility)`, with targets none, 30%, 45% and 60%. The position moves only when the target differs from it by at least 0.10, or goes to zero.
- **Timing.** A position is decided with the closes up to day `t` and earns the return from close `t` to close `t + 1`. A test shows that a later close never changes an earlier position.
- **Costs.** 0.1% fee per side plus slippage of 0.05%, 0.1% and 0.2% per side, charged on the size of every change of position. The headline is 0.1% slippage, so 0.2% per side. Each stretch starts from cash and pays its entry; nothing is sold at the end, so buy-and-hold pays one entry.
- **Selection.** On the validation slice only (2018-06-01 to 2023-12-31, the first day on which every rule has its warm-up), by net Sharpe at the headline cost: the best SMA and the best Donchian variant, then the better of the two. A test changes every close after 2023-12-31 and checks that the winner and all validation metrics stay the same.
- **Test.** One run from 2024-01-01 to 2026-08-31 (974 days) for the winner, its two neighbors (lookbacks 20% below and above), buy-and-hold and every other candidate. The others only feed the deflated Sharpe ratio and the tables.
- **Deflated Sharpe ratio** (Bailey and López de Prado, 2014). Trials: every configuration looked at, 38 (32 SMA, 4 Donchian, 2 neighbors outside the grid). The trial variance is the variance of the daily Sharpe ratios of those 38 on the test slice.
- **Decision rule** (`decide` in `scripts/trend_study.py`), on the test slice, net of costs: Sharpe and Calmar above buy-and-hold's, max drawdown no worse than -40% (warning from -30%), positive net return, neighbors within 20% keep at least half of the winner's Sharpe, deflated Sharpe probability above 0.95. A no-go stops the strategy work.

### Choices of this spike that the issue did not fix

- **The Donchian rule is the author's reading of the abstract, not the paper's.** The paper (Zarattini, Pagani, Barbon, 2025) was not read, only its abstract. The lookbacks, the exit at the midpoint, the volatility window, the targets and the 0.10 band are this spike's choices, and the rule uses closes because the loader reuses `scripts/backtest_engine.py`, which returns no highs or lows. A different Donchian specification could behave differently.
- **"Do not collapse"** is read as: a neighbor's test Sharpe is at least half of the winner's. The issue did not define it.
- **Trials are counted as independent**, which is conservative: neighboring lookbacks move together.

## Results

### The audit table reproduces

The engine, run as the audit script of 2026-10-03 did (2019-01-01 to 2026-08-31, 0.1% fee, no slippage), gives the numbers of the issue: CAGR, Sharpe and trade counts match to the printed digit. Only the SMA100 drawdown differs, -38.5% here against -39% in the issue.

| | CAGR | Sharpe | Max drawdown | Calmar | Trades | Trades/year | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| Buy and hold | 48.9% | 0.96 | -77% | 0.64 | 1 | 0.1 | 100% |
| Long if close > SMA50 | 62.9% | 1.34 | -58% | 1.08 | 151 | 19.7 | 54% |
| Long if close > SMA100 | 55.2% | 1.22 | -38% | 1.44 | 99 | 12.9 | 56% |
| Long if close > SMA200 | 37.2% | 0.93 | -64% | 0.58 | 61 | 8.0 | 57% |

### Selection on the validation slice

| | CAGR | Sharpe | Max drawdown | Calmar | Trades | Trades/year | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| SMA122 | 72.2% | 1.40 | -34% | 2.15 | 31 | 5.5 | 52% |
| Donchian 10/20/40/80/160, vol 30% | 25.0% | 1.28 | -27% | 0.91 | 214 | 38.3 | 21% |

Winner: SMA122. It is not one of the three windows fixed in advance.

### Test slice (2024-01-01 to 2026-08-31), headline cost

| | CAGR | Sharpe | Max drawdown | Calmar | Trades | Trades/year | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| SMA122 (winner) | 29.9% | 0.94 | -27% | 1.10 | 33 | 12.4 | 57% |
| Buy and hold | 26.1% | 0.72 | -53% | 0.49 | 1 | 0.4 | 100% |
| SMA98 (neighbor) | 20.9% | 0.74 | -39% | 0.53 | 45 | 16.9 | 55% |
| SMA146 (neighbor) | 23.9% | 0.80 | -28% | 0.85 | 33 | 12.4 | 56% |

| Condition | Result |
|---|:---:|
| Net Sharpe above buy-and-hold | pass |
| Net Calmar above buy-and-hold | pass |
| Max drawdown no worse than -40% | pass |
| Net return positive | pass |
| Neighbors within 20% keep at least half of the Sharpe | pass |
| Deflated Sharpe probability above 0.95 | **FAIL (0.863)** |

The drawdown warning (-30% to -40%) does not apply: -27%.

### Slippage does not decide it

| Slippage per side | Winner CAGR | Winner Sharpe | Winner Calmar | Winner max drawdown | Deflated Sharpe probability | Go |
|---:|---:|---:|---:|---:|---:|:---:|
| 0.05% | 30.7% | 0.96 | 1.16 | -27% | 0.871 | no |
| 0.10% | 29.9% | 0.94 | 1.10 | -27% | 0.863 | no |
| 0.20% | 28.3% | 0.91 | 1.00 | -28% | 0.841 | no |

The winner trades 12 times a year, so going from the lowest to the highest slippage takes 2.4 points of CAGR. Buy-and-hold's Sharpe (0.72) and Calmar (0.49) do not change.

### The deflated Sharpe probability does not depend on the number of trials

| Trials counted | Probability |
|---:|---:|
| 1 | 0.941 |
| 2 | 0.926 |
| 5 | 0.904 |
| 10 | 0.889 |
| 20 | 0.875 |
| 38 | 0.863 |

With one trial this is the probability that the true Sharpe ratio is above zero. Even there it is 0.941. The test Sharpe of 0.94 a year (0.049 a day) has a standard error of about 0.032 a day over 974 days. This probability compares the rule with zero and with luck, not with buy-and-hold. The decision rule has no test of the difference between the rule's Sharpe and buy-and-hold's (0.94 against 0.72); it only requires the rule's to be higher.

### Plateau, not a spike

The test Sharpe of the 32 SMA lookbacks is between 0.55 and 1.08, all with positive return and a drawdown inside -40%. 20 of 32 beat buy-and-hold's Sharpe (0.72) and 25 of 32 its Calmar (0.49). The three windows fixed in advance: SMA50 0.91, SMA100 0.78, SMA200 0.70 (below buy-and-hold). The effect is broad, not the property of one lookback. The full grid, with validation and test columns, is in the output of `scripts/trend_study.py`.

The Donchian variants, not the winner, scored a test Sharpe of 0.77 to 0.83, a CAGR of 13% to 18% (below buy-and-hold's 26%) and a drawdown of -20% to -23%, with 137 to 148 trades in the slice.

### Where the edge comes from

| Year | Winner CAGR | Winner Sharpe | Winner max drawdown | Buy-and-hold CAGR | Buy-and-hold Sharpe | Buy-and-hold max drawdown |
|---:|---:|---:|---:|---:|---:|---:|
| 2018 | -21.7% | -1.16 | -20% | -70.0% | -1.51 | -62% |
| 2019 | 156.5% | 1.97 | -28% | 93.9% | 1.31 | -49% |
| 2020 | 179.2% | 2.29 | -25% | 299.7% | 2.25 | -54% |
| 2021 | 95.3% | 1.34 | -27% | 59.5% | 0.98 | -53% |
| 2022 | -7.9% | -0.82 | -14% | -64.3% | -1.29 | -67% |
| 2023 | 86.1% | 1.72 | -23% | 155.1% | 2.34 | -20% |
| 2024 | 89.4% | 1.61 | -26% | 120.4% | 1.75 | -26% |
| 2025 | 3.9% | 0.28 | -19% | -6.5% | 0.05 | -32% |
| 2026 (to 08-31) | 2.6% | 0.24 | -13% | -15.4% | -0.13 | -40% |

2018 is part of the validation slice and 2018 to 2023 chose the lookback. In the test slice the winner lags buy-and-hold in 2024 (89% against 120%) and leads in 2025 and 2026 only because it stayed out of the decline. In the full period the winner loses less in every down year (2018, 2022, 2025, 2026) and earns less in the strongest up years (2020, 2023, 2024). That is a drawdown effect, as #181 expected, and the test slice holds essentially one main decline.

### Rolling windows of the winner (#182 compares live results against these)

Compounded net return of every window of 30 days (1 month) and 91 days (3 months), one per day, at the headline cost.

| Windows | | Count | p5 | p25 | p50 | p75 | p95 | Losing |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| test slice, 1 month | winner | 945 | -9.8% | -3.7% | 0.0% | 3.8% | 31.3% | 41% |
| test slice, 1 month | buy and hold | 945 | -19.8% | -6.2% | 1.3% | 9.3% | 31.6% | 45% |
| test slice, 3 months | winner | 884 | -14.9% | -9.6% | 0.0% | 12.6% | 50.6% | 49% |
| test slice, 3 months | buy and hold | 884 | -24.8% | -15.0% | -0.8% | 20.0% | 56.1% | 51% |
| validation and test, 1 month | winner | 2985 | -10.8% | -2.7% | 0.0% | 7.5% | 37.1% | 34% |
| validation and test, 1 month | buy and hold | 2985 | -24.8% | -7.7% | 1.6% | 14.0% | 39.4% | 45% |
| validation and test, 3 months | winner | 2924 | -14.6% | -6.0% | 0.0% | 25.4% | 105.5% | 41% |
| validation and test, 3 months | buy and hold | 2924 | -40.2% | -15.7% | 4.2% | 34.1% | 112.2% | 45% |

The median window is 0.0% because the rule is in cash on 43% of the days of the test slice. The 5th percentile of the winner's windows is -10% to -11% for 1 month and -15% for 3 months. The validation-and-test windows hold more regimes, so they are the better reference for the pause threshold of #182 if the strategy goes ahead. The lookback was chosen on the validation days of those windows, so they are not out of sample.

## Answers to the questions

**Does a simple trend rule beat buy-and-hold after fees on Bitcoin?** On the test slice, yes on risk-adjusted terms: Sharpe 0.94 against 0.72, Calmar 1.10 against 0.49, a drawdown of -27% against -53%, and a CAGR of 29.9% against 26.1%, after 0.2% per side. The advantage in return is small and rests on one decline (2025 to 2026); the one in drawdown is large and shows in every down year since 2018.

**Is the result robust enough to paper-trade?** By the rule as written, no. Neighbors and the whole lookback grid pass the plateau test, the result survives the highest slippage and the drawdown limit holds. The deflated Sharpe probability fails (0.863 against 0.95), and it fails because the test slice is short, not because many configurations were tried.

## Caveats

- One asset, one path, a period dominated by a rise, and 2024 onward already seen by the audit script. The validation slice (2018 to 2023) holds the 2018 and 2022 declines and the 2020 to 2021 rise.
- The winner was chosen by validation Sharpe among 32 lookbacks and picked the maximum of a region (SMA111 to SMA135 all have a validation Sharpe of 1.38 to 1.40). The test slice is the only check of the choice.
- Costs are fee and slippage only: no spread beyond slippage, no taxes (`docs/STRATEGY.md`, answer 6, still open), and the fill is assumed at the close of the signal day. A manual order after the 00:10 UTC signal can fill away from that close; slippage is the allowance for it.
- The database ends on 2026-08-31 because that is the last month loaded. September to November 2026 is not in the study and stays untouched.
- Weekly vs. daily rebalancing, other assets and other rule families were not tried.

## What would change the decision

- **More data.** If the winner keeps the same daily Sharpe (0.049), skewness (0.72) and kurtosis (9.9) it had on the test slice, the probability passes 0.95 after about 1,080 days of test data with one trial, and after about 2,200 days (6 years) with the 38 trials counted. The test slice has 974. This is arithmetic on the formula, not a measurement. Data after the spike is the only clean data, as #181 said, and the roughly 80 days from September to 21 November 2026 are the first of it.
- **An owner override** (done on 2026-11-22, paper-trading only). Paper-trading costs no money, and the result passes every other condition including a plateau and the drawdown limit, so #182 is the cheaper way to collect clean data. The pause thresholds of the override are the 5th percentiles of the rolling windows above.
- **A different rule.** If the owner wants the 0.95 threshold to hold, the next step is a better-specified Donchian ensemble with the paper's own lookbacks and highs and lows, which needs the full paper and a loader that returns highs and lows.

## Reproduce

```bash
docker compose exec api python -m scripts.trend_study > report.md
```

The run is deterministic for the stored data: no random numbers are used. It takes about 0.3 s.
