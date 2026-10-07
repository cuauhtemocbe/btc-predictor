# Spike #109: is intraday (1h / 15m) prediction worth pursuing?

**Decision: drop for now.** A 1h return model predicts direction slightly better than the baselines, but the gain per trade is about 10 times smaller than the fees. Revisit only if fees fall below about 1 bp per side.

Date: 2026-10-02. Script: deleted after the spike, recover it with `git show 79c6d2c:scripts/spike_intraday.py`. Nothing is written to the database.

## Method

- Same recipe as production: `shared.features` log-return features (window 21), Linear regression, expanding training window, walk-forward. The prediction rule is the production one: UP when the predicted price is above the price at prediction.
- Same `BTCUSDT` klines source (`data.binance.vision`, SHA256-verified), 2017-08-17 to 2026-08-31, so 1d and 1h cover the same days.
- Retrain once a day (every 1 day for 1d, every 24 rows for 1h). The first 1,000 samples only train.
- Test slice from 2024-01-01 (the headline); everything before is validation. No parameter was tuned.
- Baselines and p-value as in `shared/shared/baselines.py`: always-up, persistence, one-sided binomial test against the best baseline.
- Strategy: long while the model predicts UP, flat otherwise, 0.1% fee on every entry and every exit. Always-up and persistence use the same rule.

## Results (test slice, 2024-01-01 to 2026-08-31)

| | 1d | 1h |
|---|---:|---:|
| Predictions | 973 | 23,375 |
| Model accuracy | 51.28% | 51.54% |
| Always-up accuracy | 50.67% | 50.51% |
| Persistence accuracy | 49.02% | 47.75% |
| Edge over best baseline | +0.62 pp | +1.04 pp |
| p-value | 0.36 (not significant) | 0.0008 |
| Model return, gross | +84.5% | +89.2% |
| Model return, net of 0.1%/side | +5.5% | -99.9% |
| Always-up return (buy-and-hold) | +77.9% | +85.0% |
| Entries | 280 | 4,004 |
| Gross return per entry | +28.6 bps | +2.0 bps |

Validation slice (1d: 1,307 predictions, 1h: 54,716): 1d edge -2.22 pp (p = 0.95), 1h edge +1.45 pp (p < 0.0001). The 1h model has a small, consistent direction edge in both slices; the 1d model has none.

## Answers to the questions

**Does a simple 1h return model beat always-up and persistence on a walk-forward test, before and after 0.1% fees?**

- **Before fees, on direction:** yes, by about 1 pp (p = 0.0008). It also beats persistence by 3.8 pp.
- **Before fees, on return:** barely. The model gains +89.2% against +85.0% for buy-and-hold, and half of that period is spent flat.
- **After fees:** no. The model enters 4,004 times and earns +2.0 bps gross per entry, against 20 bps for the entry and exit fees. Net return is -99.9%. Persistence loses everything too (-100%). Only always-up survives, because it pays the fee once.
- **Break-even:** the fee per side would have to be below about 1 bp (0.01%) for the 1h model to keep anything.
- 1d also does not hold up: +5.5% net against +77.7% for always-up.

**What is the storage and training cost for 1h over 5+ years?**

Measured on 2017-08-17 to 2026-08-31 (9 years), one symbol, running the script alone:

| | 1d | 1h |
|---|---:|---:|
| Rows | 3,302 | 79,113 |
| Postgres size (about 210 bytes per row, from `pg_total_relation_size('prices')`) | 0.7 MB | 16.6 MB |
| One Linear fit | 8 ms | 103 ms (on 79k samples) |
| Whole walk-forward | 20 s | 337 s |

Storage and training are cheap. 16.6 MB per symbol is nothing for Railway Postgres, and a daily 1h refit takes about 0.1 s. Cost is not what decides this. 15m was not run (stopped after more than 25 minutes of a parallel run); at four times the rows it would be about 66 MB and a few hundred ms per fit, an extrapolation, not a measurement.

**Recommendation: drop.** Do not build 1h prediction now.

## Caveats

- The p-value treats the best baseline's accuracy as fixed and ignores serial correlation between consecutive hours, so 0.0008 is optimistic. The edge is probably real, but it is about 1 pp.
- One model, one window (21), a deterministic Linear fit, one asset, long-only, fees only (no slippage, no spread, no funding).
- Fee of 0.1% per side is the standard Binance spot rate. VIP tiers and BNB discounts lower it but not to 0.01%.
- The 1d run here (51.28% on 973 days) is not the same number as the production backtest in the README (51.23% on 974 days): it uses `data.binance.vision` files directly, one test day fewer, and a 1,000-sample warm-up. Both agree that the daily edge is not significant.
- 15m was not run.

## What would change the decision

- A fee per side of 1 bp or less (maker rebates on a different venue), or
- features that predict move size, not just direction, so the gross return per entry rises well above 20 bps.

No follow-up user stories are drafted, because the recommendation is not "pursue".

## Reproduce

The script was removed once the decision was made (#160). Recover it from git:

```bash
git show 79c6d2c:scripts/spike_intraday.py > /tmp/spike_intraday.py
```

It downloaded a few MB of monthly zips and took about 6 minutes for 1h.
