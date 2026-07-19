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
)
from shared.db.models import Model, Prediction


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
    """Test that activate_model activates the target and deactivates others."""
    # Create 3 models, one active
    model1 = Model(
        name="linear_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,  # Currently active
    )

    model2 = Model(
        name="lstm_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    model3 = Model(
        name="xgboost_v1",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add_all([model1, model2, model3])
    db_session.commit()
    db_session.refresh(model2)  # Get the ID

    # Activate model2
    activated = activate_model(db_session, model2.id)
    db_session.commit()

    # Verify model2 is activated
    assert activated.id == model2.id
    assert activated.is_active is True

    # Verify only model2 is active
    active = get_active_model(db_session)
    assert active.id == model2.id

    # Verify model1 and model3 are deactivated
    all_models = get_all_models(db_session)
    active_count = sum(1 for m in all_models if m.is_active)
    assert active_count == 1, "Only one model should be active"


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


def test_activate_model_only_one_active_at_a_time(db_session, sample_model_artifact):
    """
    CRITICAL TEST: Verify only ONE model is active after activation.

    This is the core requirement of US-024.
    """
    # Create 4 models (all 4 types)
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

    # Activate each model sequentially, verify only one active each time
    for target_model in models:
        db_session.refresh(target_model)
        activate_model(db_session, target_model.id)
        db_session.commit()

        # Count active models
        all_models = get_all_models(db_session)
        active_models = [m for m in all_models if m.is_active]

        assert len(active_models) == 1, "Only ONE model should be active"
        assert active_models[0].id == target_model.id
