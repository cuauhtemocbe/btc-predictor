"""
Integration tests for Model table database operations.

These tests verify actual database operations with the models table,
including Gherkin acceptance criteria from US-007.
"""

import pickle
from datetime import UTC, date, datetime

import numpy as np
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from shared.db.models import Model


# Gherkin Scenario 1: Create models table via migration
def test_models_table_exists(db_engine, apply_migrations):
    """
    Scenario: Create models table via migration
        When I run "alembic upgrade head"
        Then a table named "models" exists
        And it has columns: id, name, version, params, artifact, trained_at,
                            train_from, train_to, is_active
    """
    inspector = inspect(db_engine)
    table_names = inspector.get_table_names()

    # Verify table exists
    assert "models" in table_names

    # Verify columns
    columns = {col["name"]: col for col in inspector.get_columns("models")}
    expected_columns = [
        "id", "name", "version", "params", "artifact",
        "trained_at", "train_from", "train_to", "is_active"
    ]

    for col_name in expected_columns:
        assert col_name in columns, f"Column {col_name} not found"

    # Verify column types
    assert str(columns["id"]["type"]) == "INTEGER"
    assert "VARCHAR" in str(columns["name"]["type"])
    assert "VARCHAR" in str(columns["version"]["type"])
    assert "JSONB" in str(columns["params"]["type"])
    assert "BYTEA" in str(columns["artifact"]["type"])
    assert "TIMESTAMP" in str(columns["trained_at"]["type"])
    assert "DATE" in str(columns["train_from"]["type"])
    assert "DATE" in str(columns["train_to"]["type"])
    assert "BOOLEAN" in str(columns["is_active"]["type"])


def test_models_table_constraints(db_engine, apply_migrations):
    """
    Verify constraints and indexes exist on models table.
    """
    inspector = inspect(db_engine)

    # Verify primary key
    pk_constraint = inspector.get_pk_constraint("models")
    assert pk_constraint["constrained_columns"] == ["id"]

    # Verify UNIQUE constraint
    unique_constraints = inspector.get_unique_constraints("models")
    unique_names = {uc["name"] for uc in unique_constraints}
    assert "unique_model_version" in unique_names

    # Verify indexes
    indexes = inspector.get_indexes("models")
    index_names = {idx["name"] for idx in indexes}
    assert "ix_models_name" in index_names
    assert "idx_models_active" in index_names

    # Verify CHECK constraint exists
    with db_engine.connect() as conn:
        result = conn.execute(text("""
            SELECT constraint_name, check_clause
            FROM information_schema.check_constraints
            WHERE constraint_name = 'valid_training_period'
        """))
        check_constraints = list(result)
        assert len(check_constraints) > 0, "CHECK constraint not found"


# Gherkin Scenario 2: Insert trained model
@pytest.fixture
def sample_model_artifact():
    """
    Create and serialize a real LinearRegressionModel for testing.
    """
    from workers.daily.models.linear import LinearRegressionModel

    model = LinearRegressionModel(window_days=30)

    # Train with synthetic data (30 samples, 30 features each)
    X = np.random.rand(30, 30) * 50000  # Random prices
    y = np.random.rand(30) * 50000

    model.train(X, y)

    # Serialize
    return pickle.dumps(model)


def test_insert_and_retrieve_model(db_session, sample_model_artifact):
    """
    Scenario: Insert trained model
        Given I have a serialized LinearRegressionModel as bytes
        When I insert a record with name="linear_v1", artifact=bytes, is_active=True
        Then the record is saved successfully
        And querying by name returns the model
    """
    trained_at = datetime.now(UTC)
    train_from = date(2024, 1, 1)
    train_to = date(2024, 5, 1)

    # Insert model
    model_record = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30, "features": ["close"]},
        artifact=sample_model_artifact,
        trained_at=trained_at,
        train_from=train_from,
        train_to=train_to,
        is_active=True,
    )

    db_session.add(model_record)
    db_session.commit()
    db_session.refresh(model_record)

    # Verify saved
    assert model_record.id is not None

    # Query back
    retrieved = db_session.query(Model).filter_by(name="linear_v1").first()
    assert retrieved is not None
    assert retrieved.name == "linear_v1"
    assert retrieved.version == "1.0.0"
    assert retrieved.params["window_days"] == 30
    assert retrieved.is_active is True
    assert retrieved.train_from == train_from
    assert retrieved.train_to == train_to

    # Verify artifact can be deserialized
    deserialized_model = pickle.loads(retrieved.artifact)
    assert hasattr(deserialized_model, "predict")
    assert deserialized_model.is_trained is True


# Gherkin Scenario 3: Retrieve active model
def test_retrieve_active_model(db_session, sample_model_artifact):
    """
    Scenario: Retrieve active model
        Given the models table has 3 records for name="linear_v1"
        And only 1 has is_active=True
        When I query for the active model with name="linear_v1"
        Then I receive the record where is_active=True
    """
    trained_at = datetime.now(UTC)
    train_from = date(2024, 1, 1)
    train_to = date(2024, 5, 1)

    # Insert 3 models with same name, different versions
    model1 = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=trained_at,
        train_from=train_from,
        train_to=train_to,
        is_active=False,  # Inactive
    )

    model2 = Model(
        name="linear_v1",
        version="1.1.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=trained_at,
        train_from=train_from,
        train_to=train_to,
        is_active=True,  # ACTIVE
    )

    model3 = Model(
        name="linear_v1",
        version="1.2.0",
        params={"window_days": 30},
        artifact=sample_model_artifact,
        trained_at=trained_at,
        train_from=train_from,
        train_to=train_to,
        is_active=False,  # Inactive
    )

    db_session.add_all([model1, model2, model3])
    db_session.commit()

    # Query for active model
    active_model = db_session.query(Model).filter_by(
        name="linear_v1",
        is_active=True
    ).first()

    assert active_model is not None
    assert active_model.version == "1.1.0"
    assert active_model.is_active is True

    # Verify only one active model
    active_count = db_session.query(Model).filter_by(
        name="linear_v1",
        is_active=True
    ).count()
    assert active_count == 1


# Gherkin Scenario 4: Store params as JSONB
def test_jsonb_params_queries(db_session, sample_model_artifact):
    """
    Scenario: Store params as JSONB
        Given I insert a model with params={"window_days": 30, "features": ["close"]}
        When I query the model
        Then params is a JSON object with key "window_days" = 30
    """
    model = Model(
        name="test_jsonb",
        version="1.0.0",
        params={"window_days": 30, "features": ["close", "volume"]},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)

    # Query back
    retrieved = db_session.query(Model).filter_by(name="test_jsonb").first()
    assert retrieved.params["window_days"] == 30
    assert retrieved.params["features"] == ["close", "volume"]

    # Test JSON query: retrieve by name and verify params
    # Note: Direct JSON field queries work differently between PostgreSQL and SQLite,
    # so we filter by name instead
    result = db_session.query(Model).filter_by(name="test_jsonb").first()
    assert result is not None
    assert result.params["window_days"] == 30


# Gherkin Scenario 5: Constraint validation
def test_unique_constraint_violation(db_session, sample_model_artifact):
    """
    Test UNIQUE constraint: duplicate (name, version) should raise IntegrityError.
    """
    model1 = Model(
        name="duplicate_test",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add(model1)
    db_session.commit()

    # Try to insert duplicate (name, version)
    model2 = Model(
        name="duplicate_test",
        version="1.0.0",  # Same version
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add(model2)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "unique_model_version" in str(exc_info.value)


def test_check_constraint_violation(db_session, sample_model_artifact):
    """
    Test CHECK constraint: train_to < train_from should raise IntegrityError.
    """
    model = Model(
        name="check_test",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 5, 1),  # Later date
        train_to=date(2024, 1, 1),    # Earlier date (INVALID)
        is_active=False,
    )

    db_session.add(model)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    assert "valid_training_period" in str(exc_info.value)


def test_trained_at_not_null_constraint(db_session, sample_model_artifact):
    """
    MUTATION TEST: Verify trained_at is NOT NULL.

    This test kills mutant:
    - nullable=False → nullable=True in trained_at field

    Strategy:
    - Try to create a Model with trained_at=None
    - Verify IntegrityError is raised (NOT NULL constraint violation)
    """
    model = Model(
        name="null_test",
        version="1.0.0",
        params={},
        artifact=sample_model_artifact,
        trained_at=None,  # INVALID - should be NOT NULL
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    db_session.add(model)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()

    # Verify it's a NOT NULL constraint violation
    error_msg = str(exc_info.value).lower()
    assert "null" in error_msg or "not null" in error_msg
    assert "trained_at" in error_msg
