---
title: US-025 Multi-Model Predictions (Parallel)
status: approved
created: 2026-05-19
updated: 2026-05-19
issue: #27
---

# US-025: Multi-Model Predictions (Parallel)

## Objective

Enable the BTC Predictor system to generate predictions from multiple active ML models in parallel, allowing traders to compare model performance side-by-side in production and identify which model is most accurate in real-time.

## Context

### Current State
- The predictor job (`workers/daily/predictor.py`) only uses ONE active model (where `is_active=true`)
- One prediction per day
- Cannot compare models in production - only one prediction exists per day
- To evaluate a different model, we must deactivate the current one and activate another

### Problem
Bitcoin traders need to see predictions from multiple models simultaneously to:
- Compare which model is most accurate in real market conditions
- Evaluate different ML approaches (Linear vs LSTM vs XGBoost vs ARIMA)
- Build confidence by seeing consensus or divergence across models
- Make better-informed trading decisions

### Prerequisites
- ✅ US-023: LSTM, XGBoost, ARIMA implemented
- ✅ US-024: Multi-model training system
- ✅ Database schema already supports `model_id` foreign key in predictions table

## Requirements

### Functional Requirements

- [ ] Predictor supports `--multi-model` CLI flag to enable multi-model mode
- [ ] In multi-model mode, predictor generates predictions from ALL active models
- [ ] In single-model mode (default), predictor uses only the primary/best model (backward compatible)
- [ ] Each prediction is stored with its corresponding `model_id`
- [ ] Evaluator evaluates predictions for ALL models (not just one)
- [ ] Idempotency: re-running predictor doesn't duplicate predictions
- [ ] Graceful handling: if one model fails to predict, log error and continue with others
- [ ] Logging shows predictions from all models clearly

### Non-Functional Requirements

- [ ] Performance: Generating 4 predictions should take < 10 seconds total
- [ ] Backward Compatibility: Default behavior (no flag) remains unchanged
- [ ] Idempotency: UNIQUE constraint on (predicted_for, model_id) prevents duplicates
- [ ] Resilience: One model failure doesn't stop the entire prediction job

## Architecture

### Components

1. **Predictor (Enhanced)**
   - `workers/daily/predictor.py`
   - Add `--multi-model` flag parsing
   - Fetch all active models (not just one)
   - Loop through models and generate predictions
   - Handle prediction failures gracefully

2. **Evaluator (Enhanced)**
   - `workers/daily/evaluator.py`
   - Evaluate predictions for all models
   - Already supports this (operates on all predictions for a given date)

3. **Database**
   - No schema changes needed
   - `predictions` table already has `model_id` FK
   - UNIQUE constraint on (predicted_for, model_id) for idempotency

### Data Model

**Existing `predictions` table** (no changes):
```sql
CREATE TABLE predictions (
    id SERIAL PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id),
    predicted_for DATE NOT NULL,
    predicted_price NUMERIC(10, 2) NOT NULL,
    price_at_prediction NUMERIC(10, 2) NOT NULL,
    actual_price NUMERIC(10, 2),  -- NULL until evaluated
    error_abs NUMERIC(10, 2),
    error_pct NUMERIC(5, 2),
    direction_correct BOOLEAN,
    pnl_simulated NUMERIC(10, 2),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (predicted_for, model_id)  -- Prevents duplicates
);
```

**Query pattern** (example):
```sql
-- Get all predictions for May 20, 2024
SELECT p.id, m.name, p.predicted_price, p.actual_price, p.error_pct
FROM predictions p
JOIN models m ON p.model_id = m.id
WHERE p.predicted_for = '2024-05-20'
ORDER BY m.name;
```

### External Dependencies

- No new dependencies
- Uses existing `BaseModel` interface for all models

## User Stories

**Main User Story:**
```
As a Bitcoin trader comparing ML models
I want to see predictions from multiple models side-by-side
In order to evaluate which model performs best in real-time
```

**Acceptance Criteria** (Gherkin):

See full Gherkin specification in GitHub Issue #27.

**Key scenarios:**
1. ✅ Predictor generates predictions from all active models
2. ✅ Skip inactive models in multi-model mode
3. ✅ Single-model mode uses only the "best" active model (backward compatible)
4. ✅ Evaluator evaluates predictions for all models
5. ✅ Handle prediction failure for one model gracefully
6. ✅ Idempotency: re-running predictor doesn't duplicate predictions
7. ✅ Each model uses the same input features (fair comparison)
8. ✅ Predictions table supports multiple predictions per date
9. ✅ CLI flag to enable/disable multi-model mode
10. ✅ Log prediction summary for all models
11. ✅ Different models can have different window_days

## Testing Strategy

### Unit Tests
- Test predictor in single-model mode (default)
- Test predictor in multi-model mode (--multi-model flag)
- Test idempotency (re-run doesn't duplicate)
- Test graceful failure (one model fails, others continue)
- Test with 0, 1, and multiple active models

### Integration Tests
- End-to-end: predictor → database → evaluator
- Verify all active models get predictions
- Verify inactive models are skipped

### Edge Cases (ZOMBIES)
- **Z (Zero)**: No active models → exit with error
- **O (One)**: Only 1 model available → works like current behavior
- **M (Many)**: 4 models → 4 predictions per day
- **B (Boundaries)**: One model fails to predict → log warning, continue
- **I (Interfaces)**: All models use same BaseModel interface
- **E (Exceptions)**: Prediction fails for one model → skip, continue with others
- **S (Security)**: No risk, read-only predictions

## Boundaries & Constraints

### In Scope
- Multi-model prediction generation
- CLI flag to enable/disable multi-model mode
- Graceful error handling for individual model failures
- Backward compatibility with single-model mode
- Logging of all model predictions

### Out of Scope
- Dashboard visualization (deferred to US-026)
- Model activation/deactivation via API (use CLI script from US-024)
- Automatic model selection based on performance
- Ensemble predictions (averaging multiple models)
- Real-time predictions (only daily cron)

### Technical Constraints
- Must maintain backward compatibility (default behavior unchanged)
- Must use existing BaseModel interface
- Must respect is_active flag
- Must handle different window_days per model

## Success Criteria

- [ ] All Gherkin scenarios have passing automated tests
- [ ] Predictor supports `--multi-model` flag
- [ ] Default mode (no flag) uses single model (backward compatible)
- [ ] Multi-model mode generates predictions for all active models
- [ ] Evaluator evaluates predictions for all models
- [ ] Idempotency verified (re-run doesn't duplicate)
- [ ] Handles prediction failures gracefully (skip failed model, log error)
- [ ] Logging shows predictions from all models
- [ ] Tests cover both single-model and multi-model modes
- [ ] Lint and type-check pass (ruff)
- [ ] Deployed to Railway with updated daily cron service

## Implementation Plan

See: `specs/us-025-multi-model-predictions-plan.md`

## Effort Estimate

**M (Medium)**: 2 days

**Breakdown:**
- Refactor predictor.py for multi-model support: 1 day
- CLI flag + mode selection logic: 0.5 day
- Tests (multi-model, idempotency, failures): 0.5 day
- Railway deployment: 0.25 day (update daily service)
