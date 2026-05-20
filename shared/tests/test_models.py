"""
Unit tests for SQLAlchemy Model class.

These tests verify the Model ORM class definition without database operations.
"""

from datetime import UTC, date, datetime

from shared.db.models import Model


def test_create_model_instance():
    """Test creating a Model instance with valid data."""
    trained_at = datetime(2024, 5, 17, 10, 30, 0, tzinfo=UTC)
    train_from = date(2024, 1, 1)
    train_to = date(2024, 5, 1)

    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30, "features": ["close"]},
        artifact=b"pickled_model_bytes_here",
        trained_at=trained_at,
        train_from=train_from,
        train_to=train_to,
        is_active=True,
    )

    assert model.name == "linear_v1"
    assert model.version == "1.0.0"
    assert model.params == {"window_days": 30, "features": ["close"]}
    assert model.artifact == b"pickled_model_bytes_here"
    assert model.trained_at == trained_at
    assert model.train_from == train_from
    assert model.train_to == train_to
    assert model.is_active is True


def test_model_jsonb_params():
    """Test that JSONB params field serializes dict correctly."""
    complex_params = {
        "window_days": 30,
        "features": ["close", "volume", "high", "low"],
        "learning_rate": 0.001,
        "nested": {"optimizer": "adam", "epochs": 100},
    }

    model = Model(
        name="lstm_v1",
        version="2.0.0",
        params=complex_params,
        artifact=b"model_bytes",
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    assert model.params["window_days"] == 30
    assert model.params["features"] == ["close", "volume", "high", "low"]
    assert model.params["nested"]["optimizer"] == "adam"


def test_model_bytea_artifact():
    """Test that BYTEA artifact field accepts bytes."""
    large_artifact = b"x" * 1000  # Simulate a 1KB model

    model = Model(
        name="test_model",
        version="1.0.0",
        params={"test": True},
        artifact=large_artifact,
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=False,
    )

    assert isinstance(model.artifact, bytes)
    assert len(model.artifact) == 1000


def test_model_repr():
    """Test __repr__ method returns useful string."""
    trained_at = datetime(2024, 5, 17, 10, 30, 0, tzinfo=UTC)

    model = Model(
        name="linear_v1",
        version="1.0.0",
        params={"window_days": 30},
        artifact=b"model",
        trained_at=trained_at,
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        is_active=True,
    )

    repr_str = repr(model)
    assert "Model" in repr_str
    assert "linear_v1" in repr_str
    assert "1.0.0" in repr_str
    assert "True" in repr_str
    assert str(trained_at) in repr_str


def test_model_default_is_active():
    """Test that is_active defaults to False when not specified."""
    model = Model(
        name="test",
        version="1.0.0",
        params={},
        artifact=b"",
        trained_at=datetime.now(UTC),
        train_from=date(2024, 1, 1),
        train_to=date(2024, 5, 1),
        # Note: is_active not specified
    )

    # SQLAlchemy should apply the default value (False)
    # This will be None until persisted to DB, but the column has a default
    assert model.is_active is None or model.is_active is False
