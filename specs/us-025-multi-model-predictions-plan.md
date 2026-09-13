# Implementation Plan: US-025 Multi-Model Predictions (Parallel)

**Spec**: `specs/us-025-multi-model-predictions.md`  
**Created**: 2026-05-19  
**Status**: approved

---

## Components

### 1. Enhanced Predictor with Multi-Model Support
- **Purpose**: Modify predictor to support both single-model and multi-model modes
- **Files**:
  - `workers/daily/predictor.py` (modify)
  - `workers/daily/main.py` (add CLI flag parsing)
- **Effort**: M (1 day)

### 2. Enhanced Evaluator (Verification Only)
- **Purpose**: Verify evaluator already handles multiple predictions per date
- **Files**:
  - `workers/daily/evaluator.py` (verify, no changes expected)
- **Effort**: XS (0.5 hour)

### 3. Comprehensive Test Suite
- **Purpose**: Test both modes, idempotency, and failure scenarios
- **Files**:
  - `workers/daily/tests/test_predictor.py` (enhance)
  - `workers/daily/tests/test_multi_model.py` (new)
- **Effort**: S (0.5 day)

### 4. Railway Deployment Update
- **Purpose**: Update daily cron service configuration
- **Files**:
  - `railway.toml` or service config
  - Deployment guide update
- **Effort**: XS (0.25 day)

---

## Dependencies

### Build Order
1. **Enhanced Predictor** (foundation) - must be built first
2. **Evaluator Verification** (parallel with testing)
3. **Test Suite** (depends on predictor changes)
4. **Railway Deployment** (final step)

### External Dependencies
- None (all dependencies already installed)
- Uses existing BaseModel interface
- Uses existing DB schema

---

## Risks & Assumptions

### Risks
- **Risk 1: Model deserialization failures**
  - **Description**: One model may fail to load from pickle file
  - **Mitigation**: Wrap model loading in try/except, log error, skip model
  
- **Risk 2: Performance degradation**
  - **Description**: Generating 4 predictions may take too long
  - **Mitigation**: Each prediction is independent, total time ~5-10 seconds acceptable
  
- **Risk 3: Database UNIQUE constraint conflicts**
  - **Description**: Concurrent predictor runs may cause conflicts
  - **Mitigation**: Idempotency check before insertion, graceful conflict handling

### Assumptions
- ✅ Database schema already supports model_id FK (verified in US-024)
- ✅ Evaluator already processes all predictions for a date (no changes needed)
- ✅ All models implement BaseModel interface (verified in US-023)
- ✅ Railway CLI is authenticated and ready for deployment

---

## Milestones

- [ ] **Milestone 1**: Predictor supports --multi-model flag and generates predictions from all active models
- [ ] **Milestone 2**: Single-model mode (default) works unchanged (backward compatibility verified)
- [ ] **Milestone 3**: All tests passing (including idempotency and failure scenarios)
- [ ] **Milestone 4**: Deployed to Railway and verified in production

---

## Tasks

### Foundation (Build First)

#### Task 1: Add CLI flag parsing for --multi-model
- **Acceptance**: 
  - `python -m daily.predictor --multi-model` enables multi-model mode
  - `python -m daily.predictor` (no flag) uses single-model mode
  - Help text shows `--multi-model` option
- **Files**:
  - `workers/daily/main.py`
- **Tests**:
  - Test flag parsing
  - Test default behavior (no flag)
- **Effort**: XS

#### Task 2: Refactor predictor to fetch all active models
- **Acceptance**:
  - In multi-model mode, fetch all models where `is_active=true`
  - In single-model mode, fetch only the primary model
  - Log count of active models found
  - Exit with error if 0 active models
- **Files**:
  - `workers/daily/predictor.py`
- **Tests**:
  - Test with 0 active models (should exit with error)
  - Test with 1 active model (should work)
  - Test with multiple active models (should fetch all)
- **Effort**: S

#### Task 3: Implement multi-model prediction loop
- **Acceptance**:
  - Loop through all active models
  - For each model:
    - Fetch historical prices based on model's window_days
    - Load model from pickle file
    - Generate prediction
    - Save to database with model_id
  - Handle prediction failures gracefully (log, continue)
  - Log summary of all predictions generated
- **Files**:
  - `workers/daily/predictor.py`
- **Tests**:
  - Test predictions generated for all active models
  - Test graceful failure (one model fails, others continue)
  - Test predictions have correct model_id
- **Effort**: M

#### Task 4: Implement idempotency check
- **Acceptance**:
  - Before generating predictions, check if predictions for (predicted_for, model_id) exist
  - Skip insertion if already exists
  - Log "Predictions for {date} already exist, skipping"
  - Re-running predictor should not create duplicates
- **Files**:
  - `workers/daily/predictor.py`
- **Tests**:
  - Test re-running predictor doesn't duplicate
  - Test UNIQUE constraint prevents duplicates at DB level
- **Effort**: S

### Verification (Build Second)

#### Task 5: Verify evaluator handles multiple predictions per date
- **Acceptance**:
  - Review evaluator.py code
  - Confirm it processes ALL predictions for a given date
  - No changes needed (evaluator already loops through predictions)
  - Add test to verify multi-model evaluation
- **Files**:
  - `workers/daily/evaluator.py` (read-only verification)
  - `workers/daily/tests/test_evaluator.py` (add test)
- **Tests**:
  - Test evaluator with multiple predictions for same date
  - Verify all predictions get evaluated
- **Effort**: XS

### Testing (Build Third)

#### Task 6: Write comprehensive tests for multi-model mode
- **Acceptance**:
  - Test all Gherkin scenarios from spec
  - Test single-model mode (default)
  - Test multi-model mode (--multi-model flag)
  - Test idempotency
  - Test graceful failure
  - Test with 0, 1, multiple active models
  - All tests passing
- **Files**:
  - `workers/daily/tests/test_multi_model.py` (new)
  - `workers/daily/tests/test_predictor.py` (enhance existing)
- **Tests**:
  - 15+ test scenarios covering all Gherkin scenarios
- **Effort**: M

#### Task 7: Run tests in Docker container
- **Acceptance**:
  - All tests pass: `docker compose exec api pytest workers/daily/tests/ -v`
  - Coverage > 90%
  - No regressions in existing tests
- **Files**:
  - N/A (validation step)
- **Tests**:
  - Run full test suite
- **Effort**: XS

### Deployment (Build Fourth)

#### Task 8: Update Railway daily service configuration
- **Acceptance**:
  - Update start command to use `--multi-model` flag
  - Or add environment variable to control mode
  - Deploy to Railway
  - Verify service starts successfully
  - Check logs for multi-model predictions
- **Files**:
  - Railway service config (via CLI or web UI)
  - `docs/railway/US-025-DEPLOYMENT.md` (new guide)
- **Tests**:
  - Verify deployment successful
  - Check Railway logs show predictions from all models
- **Effort**: S

#### Task 9: Create Railway deployment guide
- **Acceptance**:
  - Document how to deploy updated daily service
  - Include CLI commands
  - Include verification steps
  - Link from main deployment docs
- **Files**:
  - `docs/railway/US-025-DEPLOYMENT.md`
- **Tests**:
  - Follow guide to verify it's accurate
- **Effort**: XS

---

## Effort Estimate

**Total Estimated Days**: 2 days

| Phase | Effort |
|-------|--------|
| Foundation (Tasks 1-4) | 1 day |
| Verification (Task 5) | 0.5 hour |
| Testing (Tasks 6-7) | 0.5 day |
| Deployment (Tasks 8-9) | 0.25 day |
| **Total** | **~2 days** |

---

## Implementation Order

1. ✅ **Day 1 Morning**: Tasks 1-2 (CLI flag + model fetching)
2. ✅ **Day 1 Afternoon**: Task 3 (multi-model prediction loop)
3. ✅ **Day 1 Evening**: Task 4 (idempotency)
4. ✅ **Day 2 Morning**: Tasks 5-6 (verification + tests)
5. ✅ **Day 2 Afternoon**: Tasks 7-9 (run tests + deployment)

---

## Definition of Done (Checklist)

- [ ] All Gherkin scenarios have passing automated tests
- [ ] Predictor supports `--multi-model` flag
- [ ] Default mode (no flag) uses single model (backward compatible)
- [ ] Multi-model mode generates predictions for all active models
- [ ] Evaluator evaluates predictions for all models
- [ ] Idempotency verified (re-run doesn't duplicate)
- [ ] Handles prediction failures gracefully (skip failed model)
- [ ] Logging shows predictions from all models
- [ ] Tests cover both single-model and multi-model modes
- [ ] Lint and type-check green (`docker compose exec api ruff check`)
- [ ] **Deployed to Railway via CLI** ⭐ (added per user request)
- [ ] Railway logs show multi-model predictions working
