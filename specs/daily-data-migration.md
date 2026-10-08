---
title: Daily Data Frequency Migration
status: superseded
created: 2026-05-22
updated: 2026-10-06
issue: "#38, superseded by #102"
---

# Daily Data Frequency Migration

**Problem (#38):** `fetch_price` stored hourly CoinGecko data (24 rows per day) while the daily worker ran `SELECT ... LIMIT 60` expecting 60 days, so models trained on 30-hour windows instead of 30-day windows.

**Decision (2026-05):** aggregate by day in the worker (`DATE_TRUNC('day', ...)` taking the latest row of each day) so a window of N means N days, and move the pipeline to daily frequency. The spec chose 4-hour CoinGecko candles (30 days of history, 6 rows per day) because CoinGecko's free tier capped history at 30 days. It argued for daily over hourly with third-party studies (higher accuracy and lower fees); those figures were not measured here.

**Superseded by #102:** CoinGecko and the 4-hour candles were replaced by Binance daily bars from `data.binance.vision` (9 years of history, with volume), and the pipeline works on daily bars only. The per-day aggregation survives in `get_recent_series` (`workers/daily/predictor.py`) and `fetch_training_data` (`workers/daily/trainer.py`). The measured result of the daily-versus-hourly question is in `docs/spikes/109-intraday-prediction.md`; the current data design is in `CLAUDE.md` (Design Decisions 5 and 6). The implementation plan was deleted because every step in it described the CoinGecko 4-hour design.
