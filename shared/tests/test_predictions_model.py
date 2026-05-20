"""
Integration tests for Prediction model (US-008).

Tests all Gherkin scenarios:
1. Migration creates predictions table with correct schema
2. Insert prediction with NULL evaluation fields (phase 1)
3. Update prediction with evaluation data (phase 2)
4. Query unevaluated predictions
5. Foreign key CASCADE delete
6. NOT NULL constraints
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from shared.db.models import Prediction


def test_migration_creates_predictions_table(db_engine):
    """
    Gherkin Scenario: Create predictions table via migration

    When I run "alembic upgrade head"
    Then a table named "predictions" exists
    And it has columns: id, model_id, predicted_for, predicted_at,
        price_at_prediction, predicted_price, actual_price, evaluated_at,
        error_abs, error_pct, direction_correct, pnl_simulated
    And model_id is a foreign key to models.id
    """
    inspector = inspect(db_engine)

    # Verify table exists
    assert "predictions" in inspector.get_table_names()

    # Verify columns
    columns = {col["name"]: col for col in inspector.get_columns("predictions")}
    expected_columns = [
        "id",
        "model_id",
        "predicted_for",
        "predicted_at",
        "price_at_prediction",
        "predicted_price",
        "actual_price",
        "evaluated_at",
        "error_abs",
        "error_pct",
        "direction_correct",
        "pnl_simulated",
    ]

    for col_name in expected_columns:
        assert col_name in columns, f"Column {col_name} not found in predictions table"

    # Verify foreign key
    fks = inspector.get_foreign_keys("predictions")
    assert len(fks) > 0, "No foreign keys found"

    model_fk = next((fk for fk in fks if "model_id" in fk["constrained_columns"]), None)
    assert model_fk is not None, "Foreign key on model_id not found"
    assert model_fk["referred_table"] == "models"
    assert model_fk["referred_columns"] == ["id"]
    assert model_fk["options"]["ondelete"] == "CASCADE"

    # Verify indexes
    indexes = inspector.get_indexes("predictions")
    index_names = {idx["name"]: idx["column_names"] for idx in indexes}

    assert "ix_predictions_model_id" in index_names
    assert "model_id" in index_names["ix_predictions_model_id"]

    assert "ix_predictions_predicted_for" in index_names
    assert "predicted_for" in index_names["ix_predictions_predicted_for"]


def test_insert_prediction_phase1(db_session, sample_model):
    """
    Gherkin Scenario: Insert new prediction (before evaluation)

    Given a trained model with id=123
    When I insert a prediction for predicted_for="2026-05-17"
         with predicted_price=68000.0
    And actual_price, error_abs, error_pct, direction_correct,
        pnl_simulated are NULL
    Then the record is saved successfully
    """
    # Given: trained model
    model = sample_model(name="test_linear", version="1.0.0")

    # When: insert prediction (phase 1)
    prediction = Prediction(
        model_id=model.id,
        predicted_for=date(2026, 5, 17),
        predicted_at=datetime.now(UTC),
        price_at_prediction=Decimal("67000.00"),
        predicted_price=Decimal("68000.00"),
        # Phase 1: evaluation fields NULL
        actual_price=None,
        evaluated_at=None,
        error_abs=None,
        error_pct=None,
        direction_correct=None,
        pnl_simulated=None,
    )
    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    # Then: record saved successfully
    assert prediction.id is not None
    assert prediction.model_id == model.id
    assert prediction.predicted_for == date(2026, 5, 17)
    assert prediction.predicted_price == Decimal("68000.00")
    assert prediction.price_at_prediction == Decimal("67000.00")

    # Evaluation fields are NULL
    assert prediction.actual_price is None
    assert prediction.evaluated_at is None
    assert prediction.error_abs is None
    assert prediction.error_pct is None
    assert prediction.direction_correct is None
    assert prediction.pnl_simulated is None


def test_update_prediction_phase2(db_session, sample_prediction):
    """
    Gherkin Scenario: Update prediction with evaluation (next day)

    Given a prediction exists for predicted_for="2026-05-16"
          with predicted_price=67000.0
    And actual_price is NULL
    When I update the record with actual_price=67500.0,
         error_abs=500.0, error_pct=0.74
    Then the record is updated successfully
    And evaluated_at is set to current timestamp
    """
    # Given: prediction exists (phase 1)
    prediction = sample_prediction(
        predicted_for=date(2026, 5, 16),
        predicted_price=Decimal("67000.00"),
    )
    assert prediction.actual_price is None

    # When: update with evaluation data (phase 2)
    now = datetime.now(UTC)
    prediction.actual_price = Decimal("67500.00")
    prediction.evaluated_at = now
    prediction.error_abs = Decimal("500.00")
    prediction.error_pct = Decimal("0.74")
    prediction.direction_correct = True
    prediction.pnl_simulated = Decimal("500.00")

    db_session.commit()
    db_session.refresh(prediction)

    # Then: record updated successfully
    assert prediction.actual_price == Decimal("67500.00")
    assert prediction.evaluated_at is not None
    assert prediction.error_abs == Decimal("500.00")
    assert prediction.error_pct == Decimal("0.74")
    assert prediction.direction_correct is True
    assert prediction.pnl_simulated == Decimal("500.00")


def test_query_unevaluated_predictions(db_session, sample_model):
    """
    Gherkin Scenario: Query unevaluated predictions

    Given predictions table has 10 records
    And 3 have actual_price=NULL (unevaluated)
    When I query for predictions WHERE actual_price IS NULL
    Then I receive 3 records
    """
    # Create shared models for all predictions
    model_evaluated = sample_model(name="model_evaluated", version="1.0.0")
    model_unevaluated = sample_model(name="model_unevaluated", version="1.0.0")

    # Given: 7 evaluated predictions
    for i in range(7):
        pred = Prediction(
            model_id=model_evaluated.id,
            predicted_for=date.today() - timedelta(days=i + 1),
            predicted_at=datetime.now(UTC) - timedelta(days=i + 1),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=Decimal("68000.00"),
            actual_price=Decimal("67500.00"),
            evaluated_at=datetime.now(UTC),
            error_abs=Decimal("500.00"),
            error_pct=Decimal("0.74"),
            direction_correct=True,
            pnl_simulated=Decimal("500.00"),
        )
        db_session.add(pred)

    # And: 3 unevaluated predictions
    for i in range(3):
        pred = Prediction(
            model_id=model_unevaluated.id,
            predicted_for=date.today() + timedelta(days=i + 1),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=Decimal("68000.00"),
            actual_price=None,
            evaluated_at=None,
            error_abs=None,
            error_pct=None,
            direction_correct=None,
            pnl_simulated=None,
        )
        db_session.add(pred)

    db_session.commit()

    # When: query unevaluated predictions
    unevaluated = (
        db_session.query(Prediction).filter(Prediction.actual_price.is_(None)).all()
    )

    # Then: receive 3 records
    assert len(unevaluated) == 3
    for pred in unevaluated:
        assert pred.actual_price is None


def test_foreign_key_cascade_delete(db_session):
    """
    Test: Foreign key CASCADE delete works

    When a model is deleted, all its predictions should be deleted.
    """
    # Given: model with predictions
    from shared.db.models import Model

    model = Model(
        name="cascade_delete_test",
        version="1.0.0",
        params={"test": True},
        artifact=b"test",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today(),
        is_active=False,
    )
    db_session.add(model)
    db_session.commit()
    model_id = model.id

    # Create predictions
    pred1 = Prediction(
        model_id=model_id,
        predicted_for=date.today() + timedelta(days=1),
        predicted_at=datetime.now(UTC),
        price_at_prediction=Decimal("67000.00"),
        predicted_price=Decimal("68000.00"),
    )
    pred2 = Prediction(
        model_id=model_id,
        predicted_for=date.today() + timedelta(days=2),
        predicted_at=datetime.now(UTC),
        price_at_prediction=Decimal("67000.00"),
        predicted_price=Decimal("68000.00"),
    )
    db_session.add(pred1)
    db_session.add(pred2)
    db_session.commit()

    # Verify predictions exist
    assert (
        db_session.query(Prediction).filter(Prediction.model_id == model_id).count()
        == 2
    )

    # When: delete model (expunge predictions first to avoid ORM interference)
    db_session.expunge(pred1)
    db_session.expunge(pred2)
    db_session.delete(model)
    db_session.commit()

    # Then: predictions are also deleted (CASCADE)
    assert (
        db_session.query(Prediction).filter(Prediction.model_id == model_id).count()
        == 0
    )


def test_not_null_constraints(db_session):
    """
    Test: NOT NULL constraints are enforced

    Required fields: model_id, predicted_for, predicted_at,
                     price_at_prediction, predicted_price
    """
    import time

    # Test 1: missing model_id
    with pytest.raises(IntegrityError):
        prediction = Prediction(
            model_id=None,  # NULL not allowed
            predicted_for=date.today(),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=Decimal("68000.00"),
        )
        db_session.add(prediction)
        db_session.commit()

    db_session.rollback()

    # Test 2: missing predicted_for
    # Create fresh model with unique name using timestamp
    from shared.db.models import Model

    timestamp = str(int(time.time() * 1000000))  # microsecond precision
    model2 = Model(
        name=f"constraint_test_{timestamp}_2",
        version="1.0.0",
        params={"test": True},
        artifact=b"test",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today(),
        is_active=False,
    )
    db_session.add(model2)
    db_session.commit()

    with pytest.raises(IntegrityError):
        prediction = Prediction(
            model_id=model2.id,
            predicted_for=None,  # NULL not allowed
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=Decimal("68000.00"),
        )
        db_session.add(prediction)
        db_session.commit()

    db_session.rollback()

    # Test 3: missing predicted_price
    # Create another fresh model with unique name
    timestamp = str(int(time.time() * 1000000))
    model3 = Model(
        name=f"constraint_test_{timestamp}_3",
        version="1.0.0",
        params={"test": True},
        artifact=b"test",
        trained_at=datetime.now(UTC),
        train_from=date.today() - timedelta(days=30),
        train_to=date.today(),
        is_active=False,
    )
    db_session.add(model3)
    db_session.commit()

    with pytest.raises(IntegrityError):
        prediction = Prediction(
            model_id=model3.id,
            predicted_for=date.today(),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=None,  # NULL not allowed
        )
        db_session.add(prediction)
        db_session.commit()

    db_session.rollback()


def test_prediction_relationship_to_model(db_session, sample_model, sample_prediction):
    """
    Test: Prediction has relationship to Model via model_id
    """
    # Given: model and prediction
    model = sample_model(name="relationship_test", version="1.0.0")
    prediction = sample_prediction(model_id=model.id)

    # Then: can access model via relationship
    assert prediction.model is not None
    assert prediction.model.id == model.id
    assert prediction.model.name == "relationship_test"


def test_prediction_repr(db_session, sample_prediction):
    """
    Test: __repr__ method returns useful debug string
    """
    prediction = sample_prediction()
    repr_str = repr(prediction)

    assert "Prediction" in repr_str
    assert f"id={prediction.id}" in repr_str
    assert f"model_id={prediction.model_id}" in repr_str
    assert str(prediction.predicted_for) in repr_str
    assert str(prediction.predicted_price) in repr_str
