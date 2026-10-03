"""
Integration tests for CRUD operations in shared.db.crud.

These tests verify the behavior of database query functions,
specifically targeting mutation testing scenarios.
"""

import pickle
from datetime import UTC, date, datetime

import numpy as np
import pytest

from shared.db.crud import (
    activate_model,
    deactivate_all_models,
    get_active_model,
    get_all_models,
    get_evaluated_predictions,
    get_evaluated_predictions_async,
)
from shared.db.models import Model, Prediction, model_family


@pytest.fixture
def sample_model_artifact():
    """Create serialized LinearRegressionModel for testing."""
    from workers.daily.models.linear import LinearRegressionModel

    model = LinearRegressionModel(window_days=30)
    X = np.random.rand(30, 30) * 50000
    y = np.random.rand(30) * 50000
    model.train(X, y)
    return pickle.dumps(model)


def test_join_uses_exact_equality(db_session, sample_model_artifact):
    """
    MUTATION TEST: Verify JOIN uses exact equality (==), not <= or 'is not'.

    This test kills mutants:
    - Prediction.model_id == Model.id → Prediction.model_id <= Model.id
    - Prediction.model_id == Model.id → Prediction.model_id is not Model.id

    Strategy:
    - Create 2 models with id=1 and id=2
    - Create 2 predictions: one with model_id=1, another with model_id=2
    - Query all predictions
    - Verify each prediction is associated with EXACTLY its model_id
    """
    # Create two models
    model1 = Model(
        name="linear_v1_join_test",
        version="1.0.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    model2 = Model(
        name="linear_v2_join_test",
        version="2.0.0",
        params={"window_days": 60},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add_all([model1, model2])
    db_session.commit()
    db_session.refresh(model1)
    db_session.refresh(model2)

    # Create predictions for each model (both evaluated)
    prediction1 = Prediction(
        model_id=model1.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 18),
        price_at_prediction=50000.00,
        predicted_price=51000.00,
        actual_price=50500.00,  # Evaluated
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.99,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    prediction2 = Prediction(
        model_id=model2.id,  # Different model
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 19),
        price_at_prediction=51000.00,
        predicted_price=52000.00,
        actual_price=51500.00,  # Evaluated
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.97,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    db_session.add_all([prediction1, prediction2])
    db_session.commit()

    # Query all evaluated predictions
    results = get_evaluated_predictions(db_session)

    # Verify we got both predictions
    assert len(results) == 2

    # Verify each prediction is associated with EXACTLY its model_id
    # If JOIN used <= or 'is not', this would fail
    for pred in results:
        if pred.id == prediction1.id:
            assert pred.model_id == model1.id, (
                f"Prediction 1 should have model_id={model1.id}, got {pred.model_id}"
            )
        elif pred.id == prediction2.id:
            assert pred.model_id == model2.id, (
                f"Prediction 2 should have model_id={model2.id}, got {pred.model_id}"
            )
        else:
            pytest.fail(f"Unexpected prediction id: {pred.id}")


def test_to_date_filter_uses_less_than_or_equal(db_session, sample_model_artifact):
    """
    MUTATION TEST: Verify to_date filter uses <= (range), not == (exact).

    This test kills mutant:
    - Prediction.predicted_for <= to_date → Prediction.predicted_for == to_date

    Strategy:
    - Create 3 predictions with dates: 2026-05-01, 2026-05-05, 2026-05-10
    - Query with to_date=2026-05-05
    - Verify it returns predictions on 2026-05-01 and 2026-05-05 (<=)
    - Verify it does NOT return prediction on 2026-05-10 (>)
    """
    # Create a model first
    model = Model(
        name="test_model",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)

    # Create 3 predictions with different dates
    pred_early = Prediction(
        model_id=model.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 1),  # Before to_date
        price_at_prediction=50000.00,
        predicted_price=51000.00,
        actual_price=50500.00,
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.99,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    pred_exact = Prediction(
        model_id=model.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 5),  # Exactly to_date
        price_at_prediction=51000.00,
        predicted_price=52000.00,
        actual_price=51500.00,
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.97,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    pred_late = Prediction(
        model_id=model.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 10),  # After to_date
        price_at_prediction=52000.00,
        predicted_price=53000.00,
        actual_price=52500.00,
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.95,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    db_session.add_all([pred_early, pred_exact, pred_late])
    db_session.commit()

    # Query with to_date=2026-05-05
    results = get_evaluated_predictions(db_session, to_date=date(2026, 5, 5))

    # Should return 2 predictions (2026-05-01 and 2026-05-05)
    # If mutant changed <= to ==, it would only return 1 (2026-05-05)
    assert len(results) == 2, (
        f"Expected 2 predictions with to_date <= 2026-05-05, got {len(results)}"
    )

    result_dates = {pred.predicted_for for pred in results}
    assert date(2026, 5, 1) in result_dates, "Should include prediction from 2026-05-01"
    assert date(2026, 5, 5) in result_dates, "Should include prediction from 2026-05-05"
    assert date(2026, 5, 10) not in result_dates, (
        "Should NOT include prediction from 2026-05-10"
    )


def test_from_date_filter_uses_greater_than_or_equal(db_session, sample_model_artifact):
    """
    Test that from_date filter uses >= (range), not == (exact).

    This is the symmetric test for from_date, ensuring consistency.
    """
    # Create a model
    model = Model(
        name="test_model",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)

    # Create 3 predictions with different dates
    pred_early = Prediction(
        model_id=model.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 1),
        price_at_prediction=50000.00,
        predicted_price=51000.00,
        actual_price=50500.00,
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.99,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    pred_exact = Prediction(
        model_id=model.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 5),
        price_at_prediction=51000.00,
        predicted_price=52000.00,
        actual_price=51500.00,
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.97,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    pred_late = Prediction(
        model_id=model.id,
        predicted_at=datetime.now(UTC),
        predicted_for=date(2026, 5, 10),
        price_at_prediction=52000.00,
        predicted_price=53000.00,
        actual_price=52500.00,
        evaluated_at=datetime.now(UTC),
        error_abs=500.00,
        error_pct=0.95,
        direction_correct=True,
        pnl_simulated=100.00,
    )

    db_session.add_all([pred_early, pred_exact, pred_late])
    db_session.commit()

    # Query with from_date=2026-05-05
    results = get_evaluated_predictions(db_session, from_date=date(2026, 5, 5))

    # Should return 2 predictions (2026-05-05 and 2026-05-10)
    assert len(results) == 2

    result_dates = {pred.predicted_for for pred in results}
    assert date(2026, 5, 1) not in result_dates
    assert date(2026, 5, 5) in result_dates
    assert date(2026, 5, 10) in result_dates


def test_date_range_filter_both_boundaries(db_session, sample_model_artifact):
    """
    Test that both from_date and to_date work together correctly.

    Ensures the range query [from_date, to_date] is inclusive on both ends.
    """
    # Create a model
    model = Model(
        name="test_model",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)

    # Create predictions spanning a range
    dates = [date(2026, 5, i) for i in [1, 3, 5, 7, 10]]
    for d in dates:
        pred = Prediction(
            model_id=model.id,
            predicted_for=d,
            predicted_at=datetime.now(UTC),
            price_at_prediction=50000.00,
            predicted_price=51000.00,
            actual_price=50500.00,
            evaluated_at=datetime.now(UTC),
            error_abs=500.00,
            error_pct=0.99,
            direction_correct=True,
            pnl_simulated=100.00,
        )
        db_session.add(pred)

    db_session.commit()

    # Query with from_date=2026-05-03, to_date=2026-05-07
    results = get_evaluated_predictions(
        db_session, from_date=date(2026, 5, 3), to_date=date(2026, 5, 7)
    )

    # Should return 3 predictions (2026-05-03, 05, 07)
    assert len(results) == 3

    result_dates = {pred.predicted_for for pred in results}
    assert result_dates == {date(2026, 5, 3), date(2026, 5, 5), date(2026, 5, 7)}


# ============================================================================
# Model Activation CRUD Tests (US-024)
# ============================================================================


def test_get_active_model_returns_active_model(db_session, sample_model_artifact):
    """Test that get_active_model returns the model with is_active=True."""
    # Create 2 models: one active, one inactive
    inactive_model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    active_model = Model(
        name="linear_v2",
        version="2.0.0",
        params={"window_days": 60},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,  # This one is active
    )

    db_session.add_all([inactive_model, active_model])
    db_session.commit()

    # Query active model
    result = get_active_model(db_session)

    assert result is not None
    assert result.id == active_model.id
    assert result.name == "linear_v2"
    assert result.is_active is True


def test_get_active_model_returns_none_when_no_active(
    db_session, sample_model_artifact
):
    """Test that get_active_model returns None when no models are active."""
    # Create 2 inactive models
    model1 = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    model2 = Model(
        name="lstm_v1",
        version="1.0.0",
        params={"window_days": 60},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add_all([model1, model2])
    db_session.commit()

    # Query active model
    result = get_active_model(db_session)

    assert result is None


def test_get_all_models_returns_all_ordered_by_trained_at(
    db_session, sample_model_artifact
):
    """Test that get_all_models returns all models ordered by trained_at DESC."""
    # Create 3 models with different trained_at timestamps
    old_model = Model(
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime(2024, 1, 1, tzinfo=UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    recent_model = Model(
        name="lstm_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime(2024, 5, 1, tzinfo=UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    newest_model = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime(2024, 6, 1, tzinfo=UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add_all([old_model, recent_model, newest_model])
    db_session.commit()

    # Query all models
    results = get_all_models(db_session)

    # Should return 3 models, newest first
    assert len(results) == 3
    assert results[0].name == "xgboost_v1"  # Newest
    assert results[1].name == "lstm_v1"
    assert results[2].name == "linear_v1"  # Oldest


def test_deactivate_all_models(db_session, sample_model_artifact):
    """Test that deactivate_all_models sets is_active=False for all models."""
    # Create 3 models, 2 active
    model1 = Model(
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,  # Active
    )

    model2 = Model(
        name="lstm_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,  # Active
    )

    model3 = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,  # Already inactive
    )

    db_session.add_all([model1, model2, model3])
    db_session.commit()

    # Deactivate all
    count = deactivate_all_models(db_session)
    db_session.commit()

    # Should return 2 (number of models that were active)
    assert count == 2

    # Verify all models are now inactive
    all_models = get_all_models(db_session)
    for model in all_models:
        assert model.is_active is False


def test_activate_model_success(db_session, sample_model_artifact):
    """
    Test that activate_model activates the target and deactivates the
    previous active version of the SAME name -- but leaves a different-
    named active model untouched (multi-model mode, US-025).
    """
    # Two versions of "linear_v1", the first one currently active
    linear_v1 = Model(
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,  # Currently active
    )

    linear_v2 = Model(
        name="linear_v1",
        version="2.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    # A different-named model, also active -- must not be touched
    xgboost_v1 = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    db_session.add_all([linear_v1, linear_v2, xgboost_v1])
    db_session.commit()
    db_session.refresh(linear_v2)  # Get the ID

    # Activate the newer "linear_v1" version
    activated = activate_model(db_session, linear_v2.id)

    # Verify the new version is activated
    assert activated.id == linear_v2.id
    assert activated.is_active is True

    # Verify the previous "linear_v1" version was deactivated
    db_session.refresh(linear_v1)
    assert linear_v1.is_active is False

    # Verify the different-named model is still active (multi-model mode)
    db_session.refresh(xgboost_v1)
    assert xgboost_v1.is_active is True

    # Exactly one active version of "linear_v1", plus the untouched xgboost
    all_models = get_all_models(db_session)
    active_models = [m for m in all_models if m.is_active]
    assert len(active_models) == 2
    assert {m.name for m in active_models} == {"linear_v1", "xgboost_v1"}


def test_activate_model_rolls_back_on_commit_failure(
    db_session, sample_model_artifact, monkeypatch
):
    """
    If the commit inside activate_model() fails, the previous active model
    must remain active -- no partial state (issue #66 atomicity guarantee).
    """
    old_active = Model(
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )
    new_version = Model(
        name="linear_v1",
        version="2.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add_all([old_active, new_version])
    db_session.commit()
    db_session.refresh(new_version)

    def failing_commit():
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(db_session, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        activate_model(db_session, new_version.id)

    # Restore real commit so the assertions below (and the fixture teardown)
    # can talk to the database again. activate_model() already rolled back
    # internally on failure; the conftest savepoint listener re-establishes
    # a fresh savepoint automatically once that rollback completes.
    monkeypatch.undo()

    db_session.refresh(old_active)
    db_session.refresh(new_version)

    assert old_active.is_active is True, "Previous active model must remain active"
    assert new_version.is_active is False, "Failed activation must not persist"


def test_activate_model_raises_error_for_nonexistent_id(
    db_session, sample_model_artifact
):
    """Test that activate_model raises ValueError for non-existent model_id."""
    # Create one model
    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add(model)
    db_session.commit()

    # Try to activate non-existent model_id=9999
    with pytest.raises(ValueError, match="Model with id=9999 does not exist"):
        activate_model(db_session, model_id=9999)


def test_activate_model_keeps_different_names_independently_active(
    db_session, sample_model_artifact
):
    """
    Activating models with different names accumulates active models --
    this is what powers multi-model prediction mode (US-025). Only
    activating a NEW VERSION of the SAME name replaces the previous one.
    """
    # Create 4 models (all different types/names)
    models = []
    for name in ["linear", "lstm", "xgboost", "arima"]:
        model = Model(
            name=f"{name}_v1",
            version="1.0.0",
            params={},
            artifact=sample_model_artifact,
            trained_at=datetime.now(UTC),
            train_from=date(2024, 1, 1),
            train_to=date(2024, 5, 1),
            is_active=False,
        )
        models.append(model)

    db_session.add_all(models)
    db_session.commit()

    # Activate each model sequentially; since all four have different
    # names, each activation must NOT deactivate the previously activated
    # ones.
    for i, target_model in enumerate(models, start=1):
        db_session.refresh(target_model)
        activate_model(db_session, target_model.id)

        all_models = get_all_models(db_session)
        active_models = [m for m in all_models if m.is_active]

        assert len(active_models) == i
        assert target_model.id in {m.id for m in active_models}


def test_activate_model_only_one_active_version_per_name(
    db_session, sample_model_artifact
):
    """
    CRITICAL TEST: activating a new version of the SAME model name leaves
    exactly one active version of that name (the atomicity guarantee
    behind issue #66), even though other model names may also be active.
    """
    versions = []
    for version in ["1.0.0", "2.0.0", "3.0.0"]:
        model = Model(
            name="linear_v1",
            version=version,
            params={},
            artifact=sample_model_artifact,
            trained_at=datetime.now(UTC),
            train_from=date(2024, 1, 1),
            train_to=date(2024, 5, 1),
            is_active=False,
        )
        versions.append(model)

    db_session.add_all(versions)
    db_session.commit()

    for target_model in versions:
        db_session.refresh(target_model)
        activate_model(db_session, target_model.id)

        all_models = get_all_models(db_session)
        active_linear_versions = [
            m for m in all_models if m.name == "linear_v1" and m.is_active
        ]

        assert len(active_linear_versions) == 1, (
            "Only one version of linear_v1 should be active"
        )
        assert active_linear_versions[0].id == target_model.id


def _persisted_model(session, name, timeframe, is_active):
    model = Model(
        name=name,
        version="1.0.0",
        params={},
        artifact=b"artifact",
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=is_active,
        timeframe=timeframe,
    )
    session.add(model)
    session.commit()
    return model


def test_deactivate_all_models_scoped_to_a_timeframe(db_session):
    """Only the models of the given timeframe are deactivated (#68)."""
    daily = _persisted_model(db_session, "daily_model", "1d", is_active=True)
    weekly = _persisted_model(db_session, "weekly_model", "1w", is_active=True)

    count = deactivate_all_models(db_session, timeframe="1w")
    db_session.commit()

    assert count == 1
    assert daily.is_active is True
    assert weekly.is_active is False


async def test_get_evaluated_predictions_async_filters_and_orders(async_db_session):
    """The async query keeps evaluated rows only, filtered and newest first (#68)."""
    model = Model(
        name="async_model",
        version="1.0.0",
        params={},
        artifact=b"artifact",
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
        timeframe="1d",
    )
    async_db_session.add(model)
    await async_db_session.flush()

    def prediction(day, timeframe, actual_price):
        return Prediction(
            model_id=model.id,
            predicted_at=datetime.now(UTC),
            predicted_for=date(2026, 5, day),
            timeframe=timeframe,
            price_at_prediction=50000.00,
            predicted_price=51000.00,
            actual_price=actual_price,
        )

    async_db_session.add_all(
        [
            prediction(10, "1d", 50500.00),
            prediction(12, "1d", 50600.00),
            prediction(14, "1d", None),  # pending, never returned
            prediction(15, "1w", 50700.00),
        ]
    )
    await async_db_session.flush()

    everything = await get_evaluated_predictions_async(async_db_session)
    daily_in_range = await get_evaluated_predictions_async(
        async_db_session,
        from_date=date(2026, 5, 11),
        to_date=date(2026, 5, 15),
        timeframe="1d",
    )

    assert [p.predicted_for.day for p in everything] == [15, 12, 10]
    assert [p.predicted_for.day for p in daily_in_range] == [12]


def _versioned_model(session, name, version, *, symbol="BTCUSDT", timeframe="1d"):
    model = Model(
        symbol=symbol,
        name=name,
        version=version,
        params={},
        artifact=b"artifact",
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
        timeframe=timeframe,
    )
    session.add(model)
    session.commit()
    return model


def test_activate_model_replaces_previous_version_in_the_name(db_session):
    """
    Issue #169: the daily trainer names models "<family>_v<N>", so activating
    linear_v2 must deactivate linear_v1 -- while xgboost_v1 stays active.
    """
    linear_v1 = _versioned_model(db_session, "linear_v1", "v1")
    linear_v2 = _versioned_model(db_session, "linear_v2", "v2")
    xgboost_v1 = _versioned_model(db_session, "xgboost_v1", "v1")
    activate_model(db_session, linear_v1.id)
    activate_model(db_session, xgboost_v1.id)

    activate_model(db_session, linear_v2.id)

    active = {m.name for m in get_all_models(db_session) if m.is_active}
    assert active == {"linear_v2", "xgboost_v1"}


def test_activate_model_does_not_touch_other_symbols_or_timeframes(db_session):
    """The family scope stays within one (symbol, timeframe)."""
    paxg = _versioned_model(db_session, "linear_v1", "v1", symbol="PAXGUSDT")
    weekly = _versioned_model(db_session, "linear_v1", "v1", timeframe="1w")
    new = _versioned_model(db_session, "linear_v2", "v2")
    activate_model(db_session, paxg.id)
    activate_model(db_session, weekly.id)

    activate_model(db_session, new.id)

    db_session.refresh(paxg)
    db_session.refresh(weekly)
    assert paxg.is_active is True
    assert weekly.is_active is True


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("linear_v1", "linear"),
        ("linear_v12", "linear"),
        ("linear_weekly_v1", "linear_weekly"),
        ("xgboost", "xgboost"),
        ("model_v1_extra", "model_v1_extra"),
    ],
)
def test_model_family_strips_only_a_trailing_version_suffix(name, family):
    assert model_family(name) == family
