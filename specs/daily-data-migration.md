---
title: Daily Data Frequency Migration
status: in-progress
created: 2026-05-22
updated: 2026-05-22
issue: #38
---

# Daily Data Frequency Migration

## Objective

Migrate the BTC Predictor project from hourly to daily data frequency to fix a critical bug in the daily worker and improve prediction accuracy. The daily worker currently queries for 60 records expecting 60 DAYS but receives 60 HOURS (~2.5 days), causing models to be trained on 30-hour windows instead of 30-day windows. This migration will correct the bug, backfill 365 days of historical daily data, and align all components to use daily frequency consistently.

## Context

### Problem Statement

The BTC Predictor has a critical data frequency mismatch:

1. **fetch_price worker**: Downloads HOURLY data (24 records/day) from CoinGecko API
2. **daily worker (trainer/predictor)**: Has a BUG - executes `SELECT ... LIMIT 60` expecting 60 DAYS but receives 60 HOURS
3. **Result**: Models trained on 30-hour windows produce incorrect predictions

### Research Evidence

Web research on Bitcoin trading and ML prediction shows:

| Metric | Daily Data | Hourly Data | Source |
|--------|-----------|-------------|--------|
| ML Accuracy | 65-66% | 51-55% | MDPI, PMC studies |
| Trading Return | 6.6% annual | 4.6% annual | QuantPedia |
| Transaction Fees | Low (20-30 trades/month) | High (180+ trades/month) | Bitget Academy |
| Best For | Part-time investors | Day traders | Multiple sources |

**Conclusion**: Daily data is strategically superior for this project's target users (part-time investors).

### User Needs

- **Data Scientists**: Need models trained on correct time scales (30 days, not 30 hours)
- **Part-Time Investors**: Need daily predictions with lower transaction costs
- **System Reliability**: Need consistent data frequency across all components

### Business Justification

- **Correctness**: Fix critical bug causing incorrect predictions
- **Accuracy**: Improve from 51% to 65% baseline accuracy
- **Cost Efficiency**: Reduce transaction fees by 10x
- **Scalability**: Process 24x less data (hourly → daily)

## Requirements

### Functional Requirements

- [ ] **FR-1**: Backfill script downloads 30 days of 4-hour OHLC data (180 candles) from CoinGecko
- [ ] **FR-2**: Daily worker uses date aggregation (`DATE_TRUNC`) to fetch exactly N DAYS (not N HOURS)
- [ ] **FR-3**: Trained models use 30-day windows (verified via train_from/train_to dates)
- [ ] **FR-4**: Predictor uses 30 daily aggregated prices for prediction window
- [ ] **FR-5**: fetch_price worker uses `days=30` to download 4-hour data (180 candles, 6/day)
- [ ] **FR-6**: All test fixtures create 6 records per day at 4-hour intervals (0h, 4h, 8h, 12h, 16h, 20h)
- [ ] **FR-7**: Backtest validation expects 4-hour data (min_rows = window_days * 6)
- [ ] **FR-8**: Production backfill completes successfully on Railway (30 days)
- [ ] **FR-9**: Railway cron updated to daily schedule (1:00 AM UTC)
- [ ] **FR-10**: All existing tests pass with 4-hour data and daily aggregation

### Non-Functional Requirements

- [ ] **NFR-1 Performance**: Backfill completes in < 2 minutes for 30 days (180 candles)
  - **Verification**: Measure Railway execution time in logs
  - **Note**: 365-day backfill not viable (returns 4-day granularity, only 92 candles)
  
- [ ] **NFR-2 Reliability**: Backfill is idempotent (0 duplicates on retry)
  - **Verification**: Run backfill twice, verify COUNT(*) unchanged
  
- [ ] **NFR-3 Data Quality**: CoinGecko returns exactly 6 records/day ±1 (4-hour intervals)
  - **Verification**: Query `SELECT day, COUNT(*) FROM (SELECT date_trunc('day', timestamp) as day FROM btc_prices) AS days GROUP BY day HAVING COUNT(*) NOT BETWEEN 5 AND 7` returns 0 rows
  
- [ ] **NFR-4 Correctness**: Model training window is 60 ±2 days
  - **Verification**: Query `SELECT (train_to::date - train_from::date) FROM models WHERE ... BETWEEN 58 AND 62`
  
- [ ] **NFR-5 Test Coverage**: Maintain ≥90% test coverage
  - **Verification**: `pytest --cov` shows coverage >= 90%

## Architecture

### Current State (Broken)

```
┌─────────────────┐
│  fetch_price    │ 
│  Cron: hourly   │ ──┐
│  days=1         │   │
│  → 24 candles   │   │
└─────────────────┘   │
                      ▼
               ┌──────────────┐
               │  btc_prices  │
               │  HOURLY data │
               │  (24 rows/day)│
               └──────────────┘
                      │
                      ▼
          ┌──────────────────────┐
          │  daily worker        │
          │  LIMIT 60            │ ❌ BUG
          │  → Gets 60 HOURS     │
          │  → Trains on 2.5 days│
          └──────────────────────┘
```

### Target State (Fixed)

```
┌─────────────────┐
│  backfill       │ (one-time)
│  days=30        │ ──┐
│  → 180 candles  │   │  (4-hour granularity)
│  (4h each)      │   │
└─────────────────┘   │
                      │
┌─────────────────┐   │
│  fetch_price    │   │
│  Cron: daily 1AM│ ──┤
│  days=30        │   │
│  → 180 candles  │   │  (6 candles/day × 30 days)
│  (4h each)      │   │
└─────────────────┘   │
                      ▼
               ┌──────────────┐
               │  btc_prices  │
               │  4-HOUR data │
               │  (6 rows/day)│  ← Raw storage
               └──────────────┘
                      │
                      ▼
          ┌──────────────────────┐
          │  daily worker        │
          │  DATE_TRUNC('day')   │ ✅ FIXED
          │  + MAX(timestamp)    │
          │  → Aggregates 6→1/day│
          │  → Gets 60 DAYS      │
          │  → Trains on 60 days │
          └──────────────────────┘
```

**Key Points**:
- CoinGecko `days=30` returns 180 candles (6/day) with 4-hour intervals
- Raw data: 6 records per day (4-hour granularity)
- Daily worker: Aggregates to 1 record/day using `DATE_TRUNC` + `MAX(timestamp)`
- Flexibility: Can aggregate to daily, 12h, 8h, 6h, or use raw 4h data

### Components

#### 1. Backfill Script (NEW)
- **File**: `scripts/backfill_daily_prices.py`
- **Purpose**: One-time download of 30 days historical 4-hour data
- **Key Features**:
  - Uses `CoinGeckoClient.fetch_ohlcv(days=30)`
  - CoinGecko returns 4-hour granularity for `days=3-30` (180 candles)
  - ⚠️ **Cannot use `days=365`** - would return 4-DAY granularity (92 sparse candles)
  - Chunked insertion (100 records/batch)
  - Exponential backoff retry for rate limits
  - Idempotent (UNIQUE timestamp constraint)
  - Progress logging
  - Railway-safe (timeout aware)
  
**Granularity Verification**: See `scripts/verify_days30_granularity.py` for confirmation test

#### 2. Daily Worker Fix (CRITICAL)
- **Files**: `workers/daily/trainer.py`, `workers/daily/predictor.py`
- **Purpose**: Fix critical bug - add date aggregation
- **Pattern**: Copy from `workers/weekly/predictor.py:93-103`
- **Implementation**:
  ```python
  # Subquery: Get latest timestamp per day
  latest_per_day = (
      select(
          func.date_trunc('day', BtcPrice.timestamp).label('day'),
          func.max(BtcPrice.timestamp).label('latest_timestamp')
      )
      .group_by('day')
      .order_by(func.date_trunc('day', BtcPrice.timestamp).desc())
      .limit(min_days)
      .subquery()
  )
  
  # Main query: Get close for latest timestamp each day
  stmt = (
      select(BtcPrice.close)
      .join(latest_per_day, BtcPrice.timestamp == latest_per_day.c.latest_timestamp)
      .order_by(latest_per_day.c.day.desc())
  )
  ```

#### 3. Fetch Price Update
- **File**: `workers/fetch_price/main.py`
- **Change**: `fetch_prices(days=1)` → `fetch_prices(days=30)`
- **Rationale**: `days=30` gives 4-hour granularity (180 candles), maximum before degrading to 4-day intervals
- **Behavior**: Fetches last 30 days (180 candles), idempotency skips duplicates, inserts ~6 new candles/day
- **Railway**: Update cron from `0 * * * *` to `0 1 * * *`

#### 4. Test Fixtures Update
- **Files**: 
  - `scripts/tests/conftest.py`
  - `workers/daily/tests/conftest.py`
- **Change**: Update `for hour in range(24)` loops to `for interval in range(6)` (4-hour intervals)
- **Pattern**: Create 6 records/day at: 0h, 4h, 8h, 12h, 16h, 20h UTC

#### 5. Backtest Utils Update
- **File**: `scripts/backtest_utils.py`
- **Changes**:
  - Line 82: `min_expected_rows = window_days * 20` → `window_days * 6` (6 candles/day at 4h intervals)
  - Lines 122-126: Keep manual `groupby('date')` aggregation OR rely on DATE_TRUNC in SQL query

### Data Model

**Table**: `btc_prices` (no schema changes needed)

```sql
CREATE TABLE btc_prices (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL UNIQUE,  -- Daily: 1 record/day
    open NUMERIC(18,8) NOT NULL,
    high NUMERIC(18,8) NOT NULL,
    low NUMERIC(18,8) NOT NULL,
    close NUMERIC(18,8) NOT NULL,
    volume NUMERIC(18,8) NOT NULL,
    source VARCHAR(50) NOT NULL
);

CREATE UNIQUE INDEX ix_btc_prices_timestamp ON btc_prices(timestamp);
```

**Migration Strategy**: Additive only
- Keep existing hourly data (don't delete)
- Add daily data via backfill
- Daily worker queries daily aggregates (via DATE_TRUNC)
- Eventually archive/delete hourly data (separate cleanup task)

### External Dependencies

- **CoinGecko API (Free Tier)**: 
  - Purpose: Historical OHLC data
  - Endpoint: `/coins/bitcoin/ohlc?vs_currency=usd&days={days}`
  - Constraint: Max 365 days for free tier
  - Rate Limit: ~50 calls/minute
  - **Granularity (AUTOMATIC, cannot override on free plan)**:
    - `days=1-2`: **30 minutes** (48-96 candles)
    - `days=3-30`: **4 hours** (18-180 candles) ← **OPTIMAL RANGE**
    - `days=31+`: **4 DAYS** (sparse, ~92 candles for 365 days)
  - **Implication**: Use `days=30` for maximum 4-hour granularity
  - **Paid plans only**: `interval=daily` or `interval=hourly` parameters (not available on free tier)
  
- **Railway**: 
  - Purpose: Production deployment
  - Services: postgres, api, fetch-price, daily
  - Cron scheduling via dashboard
  - Timeout: ~10 minutes per job

- **Python Libraries** (existing):
  - SQLAlchemy 2.0: Database ORM
  - httpx: Async HTTP client
  - pandas: Data manipulation (backtesting)

## User Stories

Reference: [GitHub Issue #38](https://github.com/cuauhtemocbe/btc-predictor/issues/38)

The issue contains complete Gherkin acceptance criteria with 9 scenarios covering:
1. Backfill downloads 365 days
2. Daily worker fetches N DAYS
3. Model trained on 30-day window
4. Predictor uses 30 daily prices
5. Fetch price downloads daily data
6. Test fixtures create 1 record/day
7. Backtest validation expects daily
8. Production backfill succeeds
9. All tests pass

## Testing Strategy

### Unit Tests

**Coverage Target**: ≥90% for modified files

**Test Files**:
- `workers/daily/tests/test_trainer.py`: Test date aggregation function
- `workers/daily/tests/test_predictor.py`: Test daily price fetching
- `scripts/tests/test_backfill.py`: NEW - Test backfill script
- `workers/fetch_price/tests/test_main.py`: Update for daily frequency

**Key Test Cases**:
- Date aggregation returns exactly N days (not hours)
- Model window_days parameter creates correct sliding windows
- Backfill handles duplicates idempotently
- CoinGecko returns daily granularity

### Integration Tests

**Test Files**:
- `scripts/tests/test_backtest_integration.py`: Update for daily data
- `workers/daily/tests/test_integration.py`: End-to-end trainer → predictor

**Key Test Cases**:
- Trainer + predictor work with daily data
- Backtesting runs with daily frequency
- Railway deployment (manual verification)

### Fixtures Update

**Pattern Change**:
```python
# BEFORE (hourly - 24 records/day)
for day in range(60):
    for hour in range(24):
        timestamp = base_date + timedelta(days=day, hours=hour)
        BtcPrice(timestamp=timestamp, ...)

# AFTER (4-hour intervals - 6 records/day)
for day in range(60):
    for interval in range(6):  # 0, 4, 8, 12, 16, 20 hours
        hour = interval * 4
        timestamp = base_date + timedelta(days=day, hours=hour)
        BtcPrice(timestamp=timestamp, ...)
```

**Rationale**: Matches CoinGecko `days=30` behavior (4-hour granularity, 6 candles/day)

**Files to Update**:
1. `scripts/tests/conftest.py`: 3 fixtures
2. `workers/daily/tests/conftest.py`: hourly fixtures
3. Update all assertions expecting hourly counts

### Performance Tests

**Backfill Performance**:
```bash
# Local
time docker compose exec api python scripts/backfill_daily_prices.py --days=30

# Railway
railway run -s api python scripts/backfill_daily_prices.py --days=30
# Monitor execution time in logs
```

**Target**: < 2 minutes for 30 days (180 candles)

**Granularity Verification**:
```bash
docker compose exec api python scripts/verify_days30_granularity.py
```

### Verification Checklist

Before deploying to production:

- [ ] All unit tests pass (100%)
- [ ] All integration tests pass
- [ ] Coverage ≥90% on modified files
- [ ] Backfill runs successfully locally with --days=30 (180 candles)
- [ ] Granularity verified: 4.00 hours between candles
- [ ] Model trains with 60-day window (after aggregation via DATE_TRUNC)
- [ ] Predictor uses 30 daily aggregated prices
- [ ] No regression in existing functionality
- [ ] Lint passes (`ruff check`)

After deploying to production:

- [ ] Backfill completes on Railway (30 days, 180 candles)
- [ ] Daily worker runs without errors (aggregates 6 candles/day → 1/day)
- [ ] Model shows 60-day training span (after DATE_TRUNC aggregation)
- [ ] Predictions created with correct dates
- [ ] Database has ~6 records/day (4-hour intervals)
- [ ] No errors in logs for 48 hours

## Boundaries & Constraints

### In Scope

✅ **Data Frequency Migration**:
- Backfill 30 days of historical 4-hour data (180 candles)
- Fix daily worker date aggregation bug (DATE_TRUNC to aggregate 6 candles/day → 1/day)
- Update fetch_price to use `days=30` for 4-hour granularity
- Update all test fixtures to 4-hour intervals (6 records/day)
- Deploy to Railway

✅ **Bug Fix**:
- Correct 30-hour → 30-day training window bug
- Verify models train on correct time scale

✅ **Production Deployment**:
- Railway backfill execution
- Cron schedule updates
- 48-hour monitoring

### Out of Scope

❌ **NOT Changing**:
- Database schema (table structure unchanged)
- Model algorithms (Linear Regression, LSTM, XGBoost, ARIMA)
- API endpoints (queries work with any timestamp frequency)
- Dashboard UI (reads data frequency-agnostic)

❌ **Future Work** (Separate Tasks):
- Delete old hourly data (archival/cleanup)
- Add hourly data as secondary timeframe (multi-timeframe)
- Optimize backfill for larger datasets
- Add data quality monitoring

### Technical Constraints

**CoinGecko API Constraints**:
- Free tier: Max 365 days historical data
- Rate limit: ~50 calls/minute
- `days` parameter: Must be in {1, 7, 14, 30, 90, 180, 365}
- Daily granularity: Only when `days >= 7`

**Railway Constraints**:
- Job timeout: ~10 minutes
- Cron schedule: Configured via dashboard (not code)
- Database: Shared PostgreSQL instance

**Python/Framework Constraints**:
- SQLAlchemy 2.0 syntax (no legacy 1.x)
- Async support for CoinGecko client
- Decimal precision for price data

**Backwards Compatibility**:
- Keep existing hourly data (additive migration)
- Weekly worker unaffected (already uses date aggregation)
- API endpoints unaffected (timestamp-based queries)

## Success Criteria

### Must Have (P0)

- [x] **Critical Bug Fixed**: Daily worker fetches 60 DAYS (not 60 hours)
  - Verify: Query models table, check `(train_to - train_from) ~= 60 days`
  
- [x] **30 Days Backfilled**: Production DB has 4-hour historical data (180 candles)
  - Verify: `SELECT COUNT(*), MIN(timestamp)::date, MAX(timestamp)::date FROM btc_prices WHERE timestamp >= NOW() - INTERVAL '30 days'`
  - Expected: ~180 records spanning 30 days
  
- [x] **All Tests Pass**: 100% pass rate locally and in CI
  - Verify: `pytest` shows no failures
  
- [x] **Coverage Maintained**: ≥90% test coverage
  - Verify: `pytest --cov` shows >= 90%

### Should Have (P1)

- [x] **Model Accuracy Baseline**: First prediction after migration
  - Verify: Prediction created with `predicted_for = tomorrow`
  
- [x] **Railway Deployment**: No errors in logs for 48 hours
  - Verify: `railway logs -s daily` shows no errors
  
- [x] **Documentation Updated**: CLAUDE.md reflects daily frequency
  - Verify: File mentions "daily" not "hourly"

### Nice to Have (P2)

- [ ] **Performance Benchmark**: Backfill time < 5 minutes (stretch goal)
- [ ] **Monitoring Dashboard**: Track backfill execution metrics
- [ ] **Automated Rollback**: If deployment fails, auto-revert

## Implementation Plan

See: [specs/daily-data-migration-plan.md](./daily-data-migration-plan.md)

**Summary**:
1. **Phase 1**: Create backfill script
2. **Phase 2**: Fix daily worker bug
3. **Phase 3**: Update fetch_price
4. **Phase 4**: Update test fixtures
5. **Phase 5**: Deploy to Railway

**Estimated Effort**: 8-11 hours total (M-sized)

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Backfill timeout on Railway | HIGH | MEDIUM | Incremental backfill (90 → 180 → 365 days) |
| CoinGecko rate limiting | MEDIUM | LOW | Exponential backoff retry (already implemented) |
| Tests fail after fixtures update | MEDIUM | MEDIUM | Update all fixtures in same PR, run full suite before push |
| Daily worker fails with new aggregation | HIGH | LOW | Extensive local testing, copy proven pattern from weekly worker |
| Production data corruption | HIGH | VERY LOW | Additive migration (keep hourly data), easy rollback |

## Changelog

- **2026-05-23 00:30**: **CRITICAL UPDATE** - CoinGecko granularity limitations discovered
  - **Discovery**: CoinGecko free plan has AUTOMATIC granularity based on `days` parameter:
    - `days=1-2`: 30 minutes (48-96 candles)
    - `days=3-30`: 4 hours (18-180 candles) ✅ TARGET RANGE
    - `days=31+`: **4 DAYS** (sparse data, NOT 4 hours)
  - **Confirmed via testing**: `days=30` returns exactly 180 candles with 4.00-hour intervals
  - **Critical finding**: Backfill with `days=365` returns only 92 candles (1 every 4 DAYS)
  - **Decision**: Use `days=30` instead of `days=365` for backfill
  - **Impact**: 
    - Maximum 30 days of 4-hour data per fetch (180 candles)
    - Cannot backfill 365 days in one request with 4-hour granularity
    - Daily worker aggregation unchanged (DATE_TRUNC still works)
  - **Sources**: 
    - [CoinGecko OHLC API Docs](https://docs.coingecko.com/reference/coins-id-ohlc)
    - Verified with `scripts/verify_days30_granularity.py`
  
- **2026-05-22 17:15**: **DESIGN DECISION** - Changed from "daily-only" to "4-hour granularity with aggregation"
  - **Discovery**: CoinGecko `/ohlc` endpoint returns 4-hour granularity (not daily) for 1-30 days
  - **Decision**: Store 4-hour data in `btc_prices`, aggregate to daily/other frequencies as needed
  - **Rationale**: More flexible - allows testing daily, 12h, 8h, 6h, 4h models without re-downloading
  - **Impact**: Daily worker will use `DATE_TRUNC('day')` to aggregate 6 records/day → 1 daily price
  - **Benefit**: 6x more training data available (6 points/day vs 1)
  
- **2026-05-22**: Initial spec created based on Issue #38 and research findings
