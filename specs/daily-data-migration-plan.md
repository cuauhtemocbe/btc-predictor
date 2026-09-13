# Implementation Plan: Daily Data Frequency Migration

**Spec**: [daily-data-migration.md](./daily-data-migration.md)  
**Created**: 2026-05-22  
**Status**: in-progress  
**Issue**: [#38](https://github.com/cuauhtemocbe/btc-predictor/issues/38)

## Components

### 1. Backfill Script
- **Purpose**: Download 365 days of historical daily OHLC data from CoinGecko
- **Files**: 
  - `scripts/backfill_daily_prices.py` (NEW)
  - `scripts/tests/test_backfill.py` (NEW)
- **Key Features**:
  - CLI with `--days` argument (default: 365)
  - Uses `CoinGeckoClient.fetch_ohlcv()` with retry logic
  - Chunked insertion for Railway timeout safety
  - Idempotent (skips duplicates via UNIQUE timestamp)
  - Progress logging with batch counts
- **Effort**: S (1 hour)

### 2. Daily Worker Date Aggregation Fix
- **Purpose**: Fix critical bug - query for N DAYS (not N HOURS)
- **Files**:
  - `workers/daily/trainer.py` (MODIFY)
  - `workers/daily/predictor.py` (MODIFY)
  - `workers/daily/tests/test_trainer.py` (UPDATE)
  - `workers/daily/tests/test_predictor.py` (UPDATE)
- **Implementation Pattern**: Copy from `workers/weekly/predictor.py:93-103`
- **Key Changes**:
  - Add `get_daily_close_prices()` helper function
  - Use `func.date_trunc('day', BtcPrice.timestamp)`
  - Use `.group_by('day')` for daily aggregation
  - Replace direct `LIMIT` queries with date-aggregated subquery
- **Effort**: M (2 hours)

### 3. Fetch Price Worker Update
- **Purpose**: Change from hourly to daily data fetching
- **Files**:
  - `workers/fetch_price/main.py` (MODIFY)
  - `workers/fetch_price/tests/test_main.py` (UPDATE)
- **Changes**:
  - Line 147: `fetch_prices(days=1)` → `fetch_prices(days=7)`
  - Update docstrings to reflect daily frequency
  - Update mock expectations in tests
- **Railway**: Cron schedule update (via dashboard)
  - From: `0 * * * *` (hourly)
  - To: `0 1 * * *` (daily at 1 AM UTC)
- **Effort**: XS (30 minutes)

### 4. Test Fixtures Update
- **Purpose**: Change all fixtures from hourly to daily (1 record/day)
- **Files**:
  - `scripts/tests/conftest.py` (MODIFY - 3 fixtures)
  - `workers/daily/tests/conftest.py` (MODIFY - hourly fixtures)
  - `shared/tests/conftest.py` (VERIFY - no changes needed)
- **Pattern Change**:
  ```python
  # BEFORE
  for day in range(60):
      for hour in range(24):  # ← REMOVE
          timestamp = datetime(...) + timedelta(hours=hour)
          
  # AFTER
  for day in range(60):
      timestamp = datetime.combine(start_date + timedelta(days=day), time(12, 0))
  ```
- **Effort**: M (2 hours)

### 5. Backtest Utils Update
- **Purpose**: Remove hourly assumptions and manual aggregation
- **Files**:
  - `scripts/backtest_utils.py` (MODIFY)
  - `scripts/tests/test_backtest_utils.py` (UPDATE)
  - `scripts/tests/test_backtest_integration.py` (UPDATE)
  - `scripts/tests/test_backtest_gherkin.py` (UPDATE)
- **Changes**:
  - Line 82: `min_expected_rows = window_days * 20` → `window_days * 1`
  - Lines 122-126: Remove `training_data.groupby("date")` aggregation
  - Update all test assertions expecting hourly row counts
- **Effort**: M (2 hours)

### 6. Documentation Update
- **Purpose**: Update project documentation to reflect daily frequency
- **Files**:
  - `CLAUDE.md` (MODIFY)
  - `shared/db/models.py` (MODIFY docstrings)
  - Worker docstrings (MODIFY)
- **Changes**:
  - Replace "hourly" → "daily" in descriptions
  - Update fetch_price cron description
  - Clarify data frequency expectations
- **Effort**: XS (30 minutes)

### 7. Production Deployment
- **Purpose**: Deploy to Railway and execute backfill
- **Steps**:
  1. Push code to main
  2. Monitor Railway deployment
  3. Execute backfill: `railway run -s api python scripts/backfill_daily_prices.py --days=365`
  4. Update cron schedules in Railway dashboard
  5. Verify daily worker runs
  6. Monitor logs for 48 hours
- **Effort**: S (1-2 hours)

## Dependencies

### Build Order (Sequential)

```
1. Backfill Script (Component 1)
   ↓
2. Daily Worker Fix (Component 2) ← Can test with backfilled data
   ↓
3. Fetch Price Update (Component 3) ← After daily worker works
   ↓
4. Test Fixtures Update (Component 4) ← After code changes done
   ↓
5. Backtest Utils Update (Component 5) ← After fixtures updated
   ↓
6. Documentation Update (Component 6) ← After everything works
   ↓
7. Production Deployment (Component 7) ← Final step
```

**Rationale for Order**:
1. **Backfill first**: Need daily data to test daily worker fix
2. **Daily worker second**: Core bug fix, can test with backfilled data
3. **Fetch price third**: Only after daily worker works with daily data
4. **Tests fourth**: Update after code changes complete
5. **Backtest fifth**: Depends on updated fixtures
6. **Docs sixth**: Document after everything works
7. **Deploy last**: All changes tested locally first

### External Dependencies

| Dependency | When Needed | Version/Details |
|------------|-------------|-----------------|
| CoinGecko API | Component 1 (Backfill) | Free tier, max 365 days |
| Railway Dashboard | Component 7 (Deploy) | Cron schedule update |
| PostgreSQL | All components | Existing Railway instance |
| pytest | Components 1-6 | Testing framework |
| SQLAlchemy 2.0 | Component 2 | Date aggregation functions |

### Internal Dependencies

| From Component | Depends On | Why |
|----------------|------------|-----|
| Daily Worker Fix | Backfill Script | Need daily data to test against |
| Fetch Price Update | Daily Worker Fix | Ensure daily worker works first |
| Test Fixtures | All code changes | Must match new implementation |
| Backtest Utils | Test Fixtures | Uses fixtures for testing |
| Production Deploy | All above | Deploy only after local verification |

## Risks & Assumptions

### Risks

#### Risk 1: Backfill Timeout on Railway (HIGH)
- **Description**: 365 days might exceed Railway job timeout (~10 min)
- **Impact**: Backfill fails, no historical data in production
- **Probability**: Medium (depends on network speed, API rate limits)
- **Mitigation**: 
  - Implement incremental backfill strategy:
    1. First run: `--days=90` (~2 min)
    2. Second run: `--days=180` (skips existing, ~2 min)
    3. Third run: `--days=365` (skips existing, ~3 min)
  - Fallback: Run locally and export/import to Railway
- **Detection**: Monitor Railway logs for timeout errors
- **Rollback**: None needed (no data corruption, just incomplete)

#### Risk 2: Daily Worker Fails with New Aggregation (MEDIUM)
- **Description**: Date aggregation query has bug or performance issue
- **Impact**: Daily worker crashes, no new predictions
- **Probability**: Low (copying proven pattern from weekly worker)
- **Mitigation**:
  - Extensive local testing before deploy
  - Copy exact pattern from `workers/weekly/predictor.py:93-103`
  - Add unit tests specifically for date aggregation function
  - Test with multiple data sizes (7, 30, 60, 90 days)
- **Detection**: Daily worker logs show errors, no predictions created
- **Rollback**: `git revert` + Railway redeploy

#### Risk 3: Test Failures After Fixtures Update (MEDIUM)
- **Description**: Updating fixtures breaks existing tests
- **Impact**: CI/CD fails, can't merge
- **Probability**: Medium (many fixtures to update)
- **Mitigation**:
  - Update all fixtures in single PR (atomic change)
  - Run full test suite locally before push
  - Update assertions systematically (60*24 → 60)
  - Review test output carefully
- **Detection**: `pytest` shows failures
- **Rollback**: Fix tests before merging

#### Risk 4: CoinGecko Rate Limiting During Backfill (LOW)
- **Description**: Too many API calls trigger rate limit (429)
- **Impact**: Backfill slows down or fails
- **Probability**: Low (CoinGeckoClient has retry logic)
- **Mitigation**:
  - Already implemented: Exponential backoff retry
  - Respect `Retry-After` header
  - Add delay between chunks if needed
- **Detection**: 429 errors in logs
- **Rollback**: Retry from last successful point (idempotent)

#### Risk 5: Production Data Corruption (VERY LOW)
- **Description**: Migration corrupts existing data
- **Impact**: Loss of historical predictions or prices
- **Probability**: Very Low (additive migration)
- **Mitigation**:
  - Migration is ADDITIVE (keep hourly data)
  - No DELETE or UPDATE operations
  - Only INSERT new daily data
  - Database backup before deployment (Railway automatic)
- **Detection**: Data loss visible in queries
- **Rollback**: Restore from Railway backup

### Assumptions

#### Assumption 1: CoinGecko Returns Daily Granularity
- **Assumption**: When `days >= 7`, CoinGecko returns 1 candle per day
- **Validation**: Test locally with `days=7`, verify exactly 7 candles returned
- **Impact if Wrong**: Would get hourly data, breaking migration
- **Validation Method**: 
  ```python
  candles = await client.fetch_ohlcv(days=7)
  assert len(candles) == 7  # Not 168 (7*24)
  ```

#### Assumption 2: Railway Timeout is ~10 Minutes
- **Assumption**: Railway jobs timeout after ~10 minutes
- **Validation**: Check Railway documentation, test with long-running job
- **Impact if Wrong**: Backfill might timeout unexpectedly
- **Validation Method**: Run backfill with `--days=90` in Railway, measure time

#### Assumption 3: Weekly Worker Pattern is Correct
- **Assumption**: `workers/weekly/predictor.py:93-103` date aggregation is bug-free
- **Validation**: Review weekly worker code, verify it works in production
- **Impact if Wrong**: Would copy buggy pattern to daily worker
- **Validation Method**: 
  ```bash
  # Test weekly worker in production
  railway run -s weekly python -m workers.weekly.predictor
  # Verify predictions created correctly
  ```

#### Assumption 4: Existing Hourly Data Won't Interfere
- **Assumption**: Daily worker will correctly filter to daily data only
- **Validation**: Test locally with mixed hourly + daily data
- **Impact if Wrong**: Daily worker might mix hourly and daily records
- **Validation Method**: 
  ```python
  # Insert mix of hourly and daily
  # Run daily worker
  # Verify only daily records used
  ```

#### Assumption 5: No Schema Changes Needed
- **Assumption**: `btc_prices` table can store daily data without changes
- **Validation**: Existing UNIQUE(timestamp) constraint works for daily
- **Impact if Wrong**: Would need migration
- **Validation Method**: Insert daily record, verify constraint works

## Milestones

### Milestone 1: Backfill Working Locally
- **Goal**: Can download 365 days of daily data to local DB
- **Verification**:
  ```bash
  docker compose up -d
  docker compose exec api python scripts/backfill_daily_prices.py --days=7
  docker compose exec postgres psql -U btcpredictor -c "SELECT COUNT(*), MIN(timestamp)::date, MAX(timestamp)::date FROM btc_prices;"
  # Expect: 7 records, span 7 days
  ```
- **Success Criteria**:
  - [ ] Script completes without errors
  - [ ] Exactly 7 daily records inserted
  - [ ] No duplicates on second run
  - [ ] Logs show progress updates
- **Checkpoint**: Don't proceed until backfill works locally

### Milestone 2: Daily Worker Fixed and Tested
- **Goal**: Daily worker queries 60 DAYS (not 60 hours)
- **Verification**:
  ```bash
  # After backfilling 60+ days
  docker compose exec api python -m workers.daily.trainer
  docker compose exec postgres psql -U btcpredictor -c "SELECT name, train_from::date, train_to::date, (train_to::date - train_from::date) as days FROM models ORDER BY trained_at DESC LIMIT 1;"
  # Expect: days ≈ 60
  ```
- **Success Criteria**:
  - [ ] Trainer fetches 60 daily prices
  - [ ] Model trained with 30-day windows
  - [ ] Database shows ~60 day span
  - [ ] Unit tests pass for date aggregation
- **Checkpoint**: Don't update fetch_price until daily worker works

### Milestone 3: All Tests Passing Locally
- **Goal**: 100% test pass rate with daily data
- **Verification**:
  ```bash
  docker compose exec api pytest workers/daily/tests/ -v
  docker compose exec api pytest scripts/tests/ -v
  docker compose exec api pytest --cov --cov-report=term-missing
  # Expect: All tests pass, coverage ≥90%
  ```
- **Success Criteria**:
  - [ ] All test fixtures updated
  - [ ] All assertions updated
  - [ ] No test failures
  - [ ] Coverage ≥90%
- **Checkpoint**: Don't deploy until all tests pass

### Milestone 4: Production Deployment Complete
- **Goal**: Railway running with daily data, no errors for 48 hours
- **Verification**:
  ```bash
  # After Railway deployment
  railway run -s api python scripts/backfill_daily_prices.py --days=365
  railway logs -s daily --tail 100
  # Check for predictions created
  railway run -s postgres psql -c "SELECT predicted_for, predicted_price FROM predictions ORDER BY predicted_at DESC LIMIT 5;"
  ```
- **Success Criteria**:
  - [ ] Backfill completes on Railway
  - [ ] Daily worker runs without errors
  - [ ] Predictions created with correct dates
  - [ ] No errors in logs for 48 hours
- **Checkpoint**: Monitor for 48 hours before closing issue

## Tasks

### Foundation (Build First)

#### Task 1: Create Backfill Script
- **Acceptance**: 
  - Script exists at `scripts/backfill_daily_prices.py`
  - Accepts `--days` CLI argument
  - Downloads daily OHLC from CoinGecko
  - Inserts idempotently (skips duplicates)
  - Logs progress with counts
- **Files**:
  - `scripts/backfill_daily_prices.py` (NEW)
  - `scripts/tests/test_backfill.py` (NEW)
- **Tests**:
  - Unit test: CLI argument parsing
  - Unit test: Idempotency (run twice, same count)
  - Integration test: Downloads 7 days successfully
  - Mock test: CoinGecko client called with correct params
- **Effort**: S (1 hour)
- **Dependencies**: None

#### Task 2: Implement Daily Worker Date Aggregation
- **Acceptance**:
  - `get_daily_close_prices()` function exists
  - Uses `func.date_trunc('day')` and `group_by('day')`
  - Returns exactly N daily prices (not hours)
  - Prices span N calendar days
- **Files**:
  - `workers/daily/trainer.py` (ADD function, UPDATE fetch_training_data)
  - `workers/daily/predictor.py` (USE function in get_recent_prices)
  - `workers/daily/tests/test_trainer.py` (ADD tests)
  - `workers/daily/tests/test_predictor.py` (UPDATE tests)
- **Tests**:
  - Unit test: `get_daily_close_prices(session, 60)` returns 60 prices
  - Unit test: Prices span ~60 days (check min/max timestamps)
  - Integration test: Trainer creates model with 60-day window
  - Integration test: Predictor uses 30 daily prices
- **Effort**: M (2 hours)
- **Dependencies**: Task 1 (need daily data to test)

### Features (Build Second)

#### Task 3: Update Fetch Price Worker
- **Acceptance**:
  - `main.py` uses `fetch_prices(days=7)`
  - Docstrings updated to "daily"
  - Test mocks expect 7 candles (not 24)
- **Files**:
  - `workers/fetch_price/main.py` (MODIFY line 147)
  - `workers/fetch_price/tests/test_main.py` (UPDATE mocks)
- **Tests**:
  - Unit test: Calls `fetch_prices(days=7)`
  - Mock test: CoinGecko returns 7 candles
  - Integration test: Inserts 7 daily records
- **Effort**: XS (30 minutes)
- **Dependencies**: Task 2 (daily worker must work first)

#### Task 4: Update Test Fixtures to Daily
- **Acceptance**:
  - No `for hour in range(24)` loops exist
  - Each fixture creates 1 record per day
  - Timestamps at midnight or noon UTC
  - All tests using fixtures pass
- **Files**:
  - `scripts/tests/conftest.py` (UPDATE 3 fixtures)
  - `workers/daily/tests/conftest.py` (UPDATE hourly fixtures)
- **Tests**:
  - Verify: `sample_btc_prices` creates 60 records (not 1440)
  - Verify: `historical_data_60_days` creates 60 records
  - Verify: `historical_90_days` creates 90 records
  - Run full test suite to verify no breaks
- **Effort**: M (2 hours)
- **Dependencies**: Tasks 2, 3 (code changes done)

### Integration (Build Third)

#### Task 5: Update Backtest Utils
- **Acceptance**:
  - `min_expected_rows = window_days * 1`
  - No manual `groupby('date')` aggregation
  - All backtest tests pass
- **Files**:
  - `scripts/backtest_utils.py` (MODIFY)
  - `scripts/tests/test_backtest_utils.py` (UPDATE assertions)
  - `scripts/tests/test_backtest_integration.py` (UPDATE)
  - `scripts/tests/test_backtest_gherkin.py` (UPDATE)
- **Tests**:
  - Unit test: Validation accepts 30 rows for 30-day window
  - Integration test: Backtest runs with daily data
  - Gherkin tests: All scenarios pass
- **Effort**: M (2 hours)
- **Dependencies**: Task 4 (fixtures updated)

#### Task 6: Update Documentation
- **Acceptance**:
  - CLAUDE.md mentions "daily" frequency
  - Worker docstrings clarified
  - BtcPrice model docstring updated
- **Files**:
  - `CLAUDE.md` (MODIFY)
  - `shared/db/models.py` (UPDATE docstring)
  - Worker files (UPDATE docstrings)
- **Tests**: Manual review
- **Effort**: XS (30 minutes)
- **Dependencies**: Tasks 1-5 (all code complete)

### Deployment (Build Last)

#### Task 7: Deploy to Railway
- **Acceptance**:
  - Code pushed to main
  - Railway deployment successful
  - Backfill runs to completion
  - Cron schedules updated
  - No errors in logs for 48 hours
- **Steps**:
  1. Push to main: `git push origin main`
  2. Monitor: `./scripts/hooks/monitor-railway.sh`
  3. Backfill: `railway run -s api python scripts/backfill_daily_prices.py --days=365`
  4. Update cron: Railway dashboard → fetch-price → `0 1 * * *`
  5. Verify: Check daily worker logs
  6. Monitor: 48 hours
- **Tests**: Production verification
- **Effort**: S (1-2 hours)
- **Dependencies**: Tasks 1-6 (all complete and tested)

## Effort Estimate

**Total Estimated Time**: 8-11 hours

| Phase | Tasks | Effort | Notes |
|-------|-------|--------|-------|
| **Foundation** | Tasks 1-2 | 3 hours | Backfill + Daily worker fix |
| **Features** | Tasks 3-4 | 2.5 hours | Fetch price + Test fixtures |
| **Integration** | Tasks 5-6 | 2.5 hours | Backtest utils + Docs |
| **Deployment** | Task 7 | 1-2 hours | Railway deploy + monitoring |
| **Buffer** | - | 1 hour | Unexpected issues |

**Breakdown by Component**:

| Component | Effort | Complexity |
|-----------|--------|------------|
| Backfill Script | 1 hour | S |
| Daily Worker Fix | 2 hours | M |
| Fetch Price Update | 30 min | XS |
| Test Fixtures | 2 hours | M |
| Backtest Utils | 2 hours | M |
| Documentation | 30 min | XS |
| Railway Deploy | 1-2 hours | S |

**Timeline**:
- **Day 1** (4-5 hours): Tasks 1-3 (Foundation + Features)
- **Day 2** (4-5 hours): Tasks 4-6 (Integration + Testing)
- **Day 3** (1-2 hours): Task 7 (Deployment + Monitoring)

**Total**: **2-3 days** of focused work (M-sized)
