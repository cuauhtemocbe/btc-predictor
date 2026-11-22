# Strategy: how the project makes money in v1, v2 and v3

Spike #186. Date: 2026-11-22. Status: **v1 is defined and has its issues (#181, #182). v2 and v3 are "not yet"**, each with the reason and the condition to open it. #181 ended in a no-go and the owner overrode it on 2026-11-22 for paper-trading only, with the conditions in "Override of the #181 no-go".

The six owner answers are in the first section and fix the thresholds used below. A version starts only when the gate of the previous one is met, or when the owner overrides it in writing in this document. Research notes and data checks for a later version do not count as starting it; building it does.

## Owner answers

Given by the owner on 2026-11-22.

| # | Question | Answer |
|---|---|---|
| 1 | Loss the owner can accept | **30-40% maximum drawdown.** In this document 40% is the hard limit (a backtest or live drawdown worse than -40% fails the gate or stops the version) and 30% is a warning level (reported, the owner reviews). The owner accepted this reading on 2026-11-22 by following the recommendation. |
| 2 | Instrument | **Spot, long or cash only.** Real money only after the paper-trade of #182 passes its gate. Futures or margin only if the gate of v2 justifies them. |
| 3 | Execution | **Manual in v1.** The system computes the signal after the daily close (00:10 UTC, 18:10 in Mexico City) and the owner places the order. Automatic orders are decided at the v1 gate and need their own issue. |
| 4 | What counts as making money | **Better Calmar and Sharpe than buy-and-hold after costs**, with the drawdown inside the limit of answer 1 and a positive net return as the floor. Always reported next to buy-and-hold. |
| 5 | Budget | **Free data only.** The owner can give **3 to 6 hours per week**, enough for one version at a time. |
| 6 | Taxes and exchange rules | **Not investigated.** Open item: the owner confirms them before any real order. This repository gives no tax advice and paper-trading needs none. |

Calmar is the annualized return divided by the absolute maximum drawdown.

## What the evidence says today

From the audit script of 2026-10-03 (BTCUSDT 2019-2026, 0.1% fee per side), as reported in #181. The script is not in the repository, one asset and one path, so this is a hypothesis, not a result.

| Strategy | CAGR | Sharpe | Max drawdown | Calmar (CAGR / drawdown) | Inside the 40% limit |
|---|---:|---:|---:|---:|:---:|
| Buy and hold | 48.9% | 0.96 | -77% | 0.64 | no |
| Long if close > SMA50 | 62.9% | 1.34 | -58% | 1.08 | no |
| Long if close > SMA100 | 55.2% | 1.22 | -39% | 1.42 | yes |
| Long if close > SMA200 | 37.2% | 0.93 | -64% | 0.58 | no |
| Linear model, long/cash | -17.4% | -0.16 | -91% | n/a (negative) | no |

- The drawdown limit is a real filter: of the three trend rules, only SMA100 fits it, and it is one point on a path that was seen before the test (#181 explains why 2024 onward is no longer clean).
- Since 2024 the rules' CAGR is close to buy-and-hold's; their edge is mostly a shallower drawdown.
- Predicting the price with a model has not worked at daily horizons (README "Resultados", #109, #184). The linear model stays as the benchmark.

## v1: trend rule on BTCUSDT, long or cash

| | |
|---|---|
| **Source of return** | Trend persistence in daily BTC returns: the rule is long while the trend is up and in cash during long declines, so most of its benefit is a shallower drawdown rather than a higher return. Evidence: the audit script above (hypothesis), Zarattini, Pagani and Barbon (2025) for a Donchian ensemble with volatility sizing, and Detzel et al. (2021) for price-to-moving-average ratios forecasting daily Bitcoin returns. |
| **Data** | `BTCUSDT` daily bars already stored (`data.binance.vision`, closed UTC bars, 2017-08 onward). Nothing new to fetch or pay for. |
| **Decision rule** | Long or cash on spot. Candidates: SMA 50, 100 and 200, and a Donchian ensemble with volatility sizing. The rule is chosen in #181 with parameters picked on the validation slice (before 2024-01-01) only. The signal is computed from closed, complete bars after the daily close; the owner places the order by hand. |
| **Costs** | 0.1% per side (Binance spot fee) plus slippage tested at 0.05%, 0.1% and 0.2% per side. A manual fill can differ from the close the backtest assumes; the slippage parameter is the allowance for that. |
| **Success metric and threshold** | On the test slice, net of costs: Calmar and Sharpe above buy-and-hold's, max drawdown no worse than -40% (warning at -30%), net return positive. Plus the robustness conditions proposed in #181: neighboring lookbacks within 20% do not collapse and the deflated Sharpe probability is above 0.95. |
| **Gate to v2** | Both of: a go in #181 (replaced, after the override, by condition 2 of that section), and the live burn-in of #182 passed (at least 3 executed signal changes, no skipped day, no stale-data exit, live results not below the 5th percentile of the same-length windows reported by #181). |
| **Stop condition** | A no-go in #181 stops the strategy work unless the owner overrides it; the override of 2026-11-22 is below, with its own archive condition. Either way, any drawdown worse than -40% of the strategy's equity (paper or real) stops the rule until the owner reviews it, and live results below the 5th percentile of #181's windows pause it. A stale or gapped series already produces no signal (#174). |
| **Issues** | [#181](https://github.com/cuauhtemocbe/btc-predictor/issues/181) validates the rule historically. [#182](https://github.com/cuauhtemocbe/btc-predictor/issues/182) runs it on live bars and shows it against buy-and-hold. The model benchmark is #184 (closed). |

Out of scope for v1: automatic orders, API keys, a position limit and a kill switch. They need an explicit owner decision and their own issue.

### Override of the #181 no-go

Date: 2026-11-22. Result of #181 (`docs/spikes/181-trend-following.md`): **no-go**. SMA122, chosen on the validation slice, passes five of the six conditions on the test slice and fails the deflated Sharpe probability: 0.863, needs above 0.95, and 0.941 even with a single trial, because the test slice has 974 days. The owner overrode the no-go **for paper-trading only** (#182), on these conditions:

1. **The rule is frozen.** SMA122 on `BTCUSDT` closes: long while the close is above the mean of the last 122 closes, otherwise cash. The lookback does not change during the paper-trade. Another lookback or rule needs a new spike.
2. **Real money needs two things:** the gate of #182, and a deflated Sharpe probability above 0.95. The probability is computed by `python -m scripts.trend_study` after loading history with `scripts/load_binance_history.py`, on the test slice extended with every closed day after 2026-08-31 and counting the same 38 trials. Those days are clean: neither the lookback nor the threshold was chosen with them. If the daily Sharpe stays at 0.049, the probability passes 0.95 at about 2,200 test days; the slice has 974.
3. **Pause thresholds.** A compounded net return of the rule (paper or real) below -10.8% over any 30 days, or below -14.6% over any 91 days, pauses it until the owner reviews it. These are the 5th percentile of the winner's windows over the validation and test days in the spike, and they replace "the 5th percentile of the windows reported by #181" above.
4. **Archive.** If the extended test sample reaches 2,200 days and the probability is still not above 0.95, the strategy is archived and the strategy work stops, as a no-go would have done.

## v2: rule plus model

| | |
|---|---|
| **Source of return** | A model accepts, rejects or sizes the v1 rule's signals (meta-labeling, López de Prado), or forecasts volatility for position sizing. Evidence is conditional: Bysik and Ślepaczuk (2026) report that a cost-aware filter restores profitability in selected configurations. A model with no edge does not gain one from more input unless the new input carries information that prices do not. |
| **Data** | Prices and volume (stored) and PAXG (stored, from 2020-08). Derivatives data **exists in the Binance public files**, checked on 2026-11-22 against the bucket listing of `data.binance.vision`, although the repository README documents only klines, aggTrades and trades: `futures/um/monthly/fundingRate` (BTCUSDT from 2020-01, every 8 hours: `calc_time`, `funding_interval_hours`, `last_funding_rate`) and `futures/um/daily/metrics` (BTCUSDT from 2020-09-01: open interest, top-trader and account long/short ratios, taker long/short volume ratio). Also present: premium index, mark price and index price klines, bookDepth and bookTicker. Their history is shorter than spot's (2020 versus 2017). The first `metrics` file has a duplicated first row, so deduplicate on load. These are signal inputs only; they do not mean trading futures (answer 2). |
| **Decision rule** | The v1 signal stays the base. The model only accepts, rejects or resizes it. XGBoost can return from git history. Any model must beat v1 and the linear model after costs. |
| **Costs** | Same as v1, plus a fee on every change of position size if the model resizes. |
| **Success metric and threshold** | On the same test days as v1, out of sample with purged walk-forward and net of costs: Calmar and Sharpe above v1's, max drawdown no worse than -40%, deflated Sharpe probability above 0.95. The minimum margin over v1 is fixed in the v2 spike before the test slice is run, because it depends on the Calmar v1 measures; it cannot be set after seeing results. |
| **Gate to v3** | Met success metric above, and the live results of v2 inside the distribution its own backtest reports. |
| **Stop condition** | If v2 does not beat v1 on the success metric, drop the model and stay on v1. |
| **Issues** | **Not yet.** Open the v2 spike when the v1 gate is met, so that v1's measured Calmar can set the margin. |

## v3: rule plus model plus text

| | |
|---|---|
| **Source of return** | Features derived from news text, added to v2. Evidence is weak and mixed, and comes from search summaries that were not opened: a 2024 paper in the Journal of Risk and Financial Management reports that Bitcoin market sentiment and technical measures are poor out-of-sample predictors, and a 2026 doctoral thesis (Sanhueza) reports that 4 of 67 variables beat a random walk across horizons. Other papers (Ider and Lessmann; Ortu et al., 2022) report improvements from sentiment, depending on model and regime. |
| **Data** | A news source with publication timestamps and several years of history. **None found that is free** (answer 5): the CryptoPanic free API gives recent posts and its history depth is not stated; free price APIs keep about one year; GDELT's blog says the DOC API searches from 2017, but third-party documentation says it officially supports the last 3 months, so the real limit has to be checked on GDELT's live documentation. A labeling model (if a language model is used) must have a training cutoff before the test period. |
| **Decision rule** | Text features enter v2's model as extra inputs; the v1 rule is unchanged. |
| **Costs** | Same as v2, plus the source and the labeling compute. Budget: none (answer 5). |
| **Success metric and threshold** | Improves v2 on the same test days, out of sample and net of costs, with the same Calmar, Sharpe, drawdown and deflated Sharpe criteria as v2. The margin is fixed in the v3 spike before the test slice is run. |
| **Gate** | The success metric above. |
| **Stop condition** | If it does not improve v2 out of sample after costs, drop it. |
| **Issues** | **Not yet.** Two reasons: v2 does not exist, and no source fits the "free only" budget. First action when v2 passes: verify GDELT's live date range and timestamps, and decide with the owner whether a paid source is worth it. |

## Alternatives not pursued

- **Funding-rate carry** (long spot, short perpetual, no price bet): needs a futures account, margin and liquidation management; excluded by answer 2. The sources found describe returns from funding payments that can reverse and were not read in full.
- **Other assets as signal or diversifier:** PAXG is stored, with history from 2020-08. Not researched; a candidate input for v2.

## Sources

- Zarattini, Pagani, Barbon (2025), "Catching Crypto Trends": https://ideas.repec.org/p/chf/rpseri/rp2580.html (abstract only)
- Detzel, Liu, Strauss, Zhou, Zhu (2021), Financial Management 50(1): https://profiles.wustl.edu/en/publications/learning-and-predictability-via-technical-analysis-evidence-from-/ (from a search summary)
- Bysik and Ślepaczuk (2026), arXiv:2606.00060: https://arxiv.org/abs/2606.00060
- Baquero (2026), arXiv:2606.00071: https://arxiv.org/abs/2606.00071
- Bailey and López de Prado (2014), "The Deflated Sharpe Ratio": https://papers.ssrn.com/abstract=2460551
- Binance public data: https://github.com/binance/binance-public-data and the bucket listing at https://data.binance.vision (folders and file headers read directly on 2026-11-22)
- Bitcoin return predictability and sentiment, JRFM 2024 (from a search summary, not opened): https://ideas.repec.org/a/gam/jjrfmx/v17y2024i10p443-d1490211.html
- GDELT DOC 2.0 date range: https://blog.gdeltproject.org/doc-2-0-updates-1-5-year-searching-and-updated-mobile-interface/ and https://rbozydar.github.io/py-gdelt/getting-started/data-sources (the two disagree; check the live documentation)
- CryptoPanic API: https://cryptopanic.com/developers/api/about
