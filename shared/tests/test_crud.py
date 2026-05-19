"""
Integration tests for CRUD operations in shared.db.crud.

These tests verify the behavior of database query functions,
specifically targeting mutation testing scenarios.
"""

import pickle
from datetime import UTC, date, datetime

import numpy as np
import pytest

from shared.db.crud import get_evaluated_predictions
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
            assert pred.model_id == model1.id,                 f"Prediction 1 should have model_id={model1.id}, got {pred.model_id}"
        elif pred.id == prediction2.id:
            assert pred.model_id == model2.id,                 f"Prediction 2 should have model_id={model2.id}, got {pred.model_id}"
        else:
            pytest.fail(f"Unexpected prediction id: {pred.id}")


def test_to_date_filter_uses_less_than_or_equal(
    db_session,
    sample_model_artifact
):
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
    results = get_evaluated_predictions(
        db_session,
        to_date=date(2026, 5, 5)
    )

    # Should return 2 predictions (2026-05-01 and 2026-05-05)
    # If mutant changed <= to ==, it would only return 1 (2026-05-05)
    assert len(results) == 2,         f"Expected 2 predictions with to_date <= 2026-05-05, got {len(results)}"

    result_dates = {pred.predicted_for for pred in results}
    assert date(2026, 5, 1) in result_dates, "Should include prediction from 2026-05-01"
    assert date(2026, 5, 5) in result_dates, "Should include prediction from 2026-05-05"
    assert date(2026, 5, 10) not in result_dates, "Should NOT include prediction from 2026-05-10"


def test_from_date_filter_uses_greater_than_or_equal(
    db_session,
    sample_model_artifact
):
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
    results = get_evaluated_predictions(
        db_session,
        from_date=date(2026, 5, 5)
    )

    # Should return 2 predictions (2026-05-05 and 2026-05-10)
    assert len(results) == 2

    result_dates = {pred.predicted_for for pred in results}
    assert date(2026, 5, 1) not in result_dates
    assert date(2026, 5, 5) in result_dates
    assert date(2026, 5, 10) in result_dates


def test_date_range_filter_both_boundaries(
    db_session,
    sample_model_artifact
):
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
        db_session,
        from_date=date(2026, 5, 3),
        to_date=date(2026, 5, 7)
    )

    # Should return 3 predictions (2026-05-03, 05, 07)
    assert len(results) == 3

    result_dates = {pred.predicted_for for pred in results}
    assert result_dates == {date(2026, 5, 3), date(2026, 5, 5), date(2026, 5, 7)}
