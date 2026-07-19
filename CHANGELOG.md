# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Dev Standards Compliance hardening: container healthcheck, pinned base
  image, self-documented Makefile, `mypy --strict` on `shared/`, enforced
  coverage gate, secret scanning, LICENSE, CHANGELOG, and accessibility
  glyphs for PnL indicators.

## [0.1.0] - 2026-07-18

### Added

- Shared package with database configuration and Alembic migrations.
- BTC price ingestion from CoinGecko with an hourly-to-daily fetch cron.
- `GET /api/prices` endpoint.
- Abstract `BaseModel` ML interface with a Linear Regression baseline,
  and a `models` table for model versioning.
- Two-phase daily prediction lifecycle: predictor job inserts a prediction,
  evaluator job fills in the actual price, errors, and PnL the next day.
- Web dashboard (`GET /`) and `GET /api/predictions/history` endpoint.
- Simulated PnL calculation and `GET /api/predictions/pnl` endpoint.
- Railway cron automation for the fetch-price and daily jobs.
- Multiple PnL trading strategies (simple, long/short, threshold, realistic)
  with a strategy comparison dashboard.
- Historical BTC price backfill and a walk-forward backtesting system with
  a results dashboard.
- Weekly multi-timeframe predictions, advanced ML models (LSTM, XGBoost,
  ARIMA), and a multi-model training/comparison system.
- Dynamic training window strategy that auto-scales from 30 to 145+ days
  of historical data across five progressive phases.

### Changed

- Migrated the price data source from Binance to CoinGecko after Binance
  started returning HTTP 451 (geo-blocking) on Railway.
- Migrated price ingestion from hourly to daily frequency with 4-hour
  candle aggregation.

### Fixed

- Evaluator lookup of 4-hour candles that previously failed to match the
  expected evaluation time.

### Removed

- Temporary admin backfill endpoint that caused service failures in
  production.

[Unreleased]: https://github.com/cuauhtemocbe/btc-predictor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cuauhtemocbe/btc-predictor/releases/tag/v0.1.0
