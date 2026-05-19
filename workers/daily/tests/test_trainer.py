"""
Tests for trainer module - multi-model training functionality.

Covers:
- train_single_model: Train one model with validation
- train_all_models: Train all 4 models and select best
"""

import pickle
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from shared.db.crud import get_active_model, get_all_models
from shared.db.models import BtcPrice, Model
from workers.daily.models import LinearRegressionModel, LSTMModel, XGBoostModel
from workers.daily.trainer import (
    create_sliding_windows,
    train_all_models,
    train_single_model,
)


@pytest.fixture
def sample_prices(db_session):
    """Create 100 days of sample BTC prices for testing."""
    base_price = 50000
    prices = []

    for i in range(100):
        price_record = BtcPrice(
            timestamp=datetime.now(UTC) - timedelta(days=100 - i),
            open=Decimal(base_price + i * 100),
            high=Decimal(base_price + i * 100 + 500),
            low=Decimal(base_price + i * 100 - 500),
            close=Decimal(base_price + i * 100),
            volume=Decimal("1000.5"),
            source="binance",
        )
        prices.append(price_record)

    db_session.add_all(prices)
    db_session.commit()

    return prices


class TestTrainSingleModel:
    """Test train_single_model function."""

    def test_train_single_model_success(self):
        """Test successful training of a single model with validation."""
        # Create sample data
        X_train = np.random.rand(50, 30) * 10000 + 50000
        y_train = np.random.rand(50) * 10000 + 50000
        X_val = np.random.rand(10, 30) * 10000 + 50000
        y_val = np.random.rand(10) * 10000 + 50000

        # Train LinearRegressionModel
        result = train_single_model(
            model_class=LinearRegressionModel,
            model_name="linear",
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            window_days=30,
        )

        # Verify result
        assert result is not None
        model, validation_error = result
        assert isinstance(model, LinearRegressionModel)
        assert isinstance(validation_error, float)
        assert 0 <= validation_error <= 100  # MAPE percentage

    def test_train_single_model_handles_failure(self):
        """Test that train_single_model returns None on failure."""
        # Invalid data (empty arrays)
        X_train = np.array([])
        y_train = np.array([])
        X_val = np.array([])
        y_val = np.array([])

        result = train_single_model(
            model_class=LinearRegressionModel,
            model_name="linear",
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            window_days=30,
        )

        # Should return None on failure
        assert result is None

    def test_train_single_model_logs_metrics(self, caplog):
        """Test that train_single_model logs duration and validation error."""
        X_train = np.random.rand(20, 30) * 10000 + 50000
        y_train = np.random.rand(20) * 10000 + 50000
        X_val = np.random.rand(5, 30) * 10000 + 50000
        y_val = np.random.rand(5) * 10000 + 50000

        train_single_model(
            model_class=LinearRegressionModel,
            model_name="linear",
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            window_days=30,
        )

        # Check log messages
        assert "Training linearModel..." in caplog.text
        assert "completed in" in caplog.text
        assert "validation error:" in caplog.text


class TestTrainAllModels:
    """Test train_all_models function."""

    def test_train_all_models_success(self, db_session, sample_prices):
        """Test successful training of all 4 models."""
        # Train all models
        models = train_all_models(db_session, window_days=30, min_days=90)

        # Verify we got models back
        assert len(models) > 0  # At least some models should succeed

        # Verify models are saved to database
        all_models = get_all_models(db_session)
        assert len(all_models) >= len(models)

        # Verify one model is active
        active = get_active_model(db_session)
        assert active is not None
        assert active.is_active is True

        # Verify all saved models have validation error in params
        for model in models:
            assert "validation_error_pct" in model.params
            assert "training_samples" in model.params
            assert "validation_samples" in model.params

    def test_train_all_models_activates_best(self, db_session, sample_prices):
        """Test that train_all_models activates the model with lowest validation error."""
        models = train_all_models(db_session, window_days=30, min_days=90)

        # Get active model
        active = get_active_model(db_session)
        assert active is not None

        # Verify active model has lowest validation error among trained models
        active_error = active.params["validation_error_pct"]

        for model in models:
            if model.id != active.id:
                # Other models should have equal or higher error
                assert model.params["validation_error_pct"] >= active_error or \
                       abs(model.params["validation_error_pct"] - active_error) < 0.01

    def test_train_all_models_uses_same_data(self, db_session, sample_prices):
        """Test that all models are trained on the same training data."""
        models = train_all_models(db_session, window_days=30, min_days=90)

        # All models should have same number of training samples
        training_samples = models[0].params["training_samples"]
        validation_samples = models[0].params["validation_samples"]

        for model in models:
            assert model.params["training_samples"] == training_samples
            assert model.params["validation_samples"] == validation_samples

    def test_train_all_models_handles_partial_failures(self, db_session, sample_prices):
        """
        Test that train_all_models continues if one model fails.

        Note: This is a conceptual test. In practice, all models should succeed
        with valid data. Actual failure testing would require mocking.
        """
        # Train with valid data - all should succeed
        models = train_all_models(db_session, window_days=30, min_days=90)

        # At minimum, Linear Regression should always work
        model_names = [m.name for m in models]
        assert any("linear" in name for name in model_names)

    def test_train_all_models_insufficient_data_raises_error(self, db_session):
        """Test that train_all_models raises ValueError with insufficient data."""
        # Create only 20 days of data (< 90 min_days)
        for i in range(20):
            price_record = BtcPrice(
                timestamp=datetime.now(UTC) - timedelta(days=20 - i),
                open=Decimal(50000 + i * 100),
                high=Decimal(50000 + i * 100 + 500),
                low=Decimal(50000 + i * 100 - 500),
                close=Decimal(50000 + i * 100),
                volume=Decimal("1000.5"),
                source="binance",
            )
            db_session.add(price_record)

        db_session.commit()

        # Should raise ValueError
        with pytest.raises(ValueError, match="Insufficient training data"):
            train_all_models(db_session, window_days=30, min_days=90)


class TestCreateSlidingWindows:
    """Test create_sliding_windows helper function."""

    def test_create_sliding_windows_correct_shape(self):
        """Test that sliding windows have correct shape."""
        prices = [Decimal(50000 + i * 100) for i in range(60)]

        X, y = create_sliding_windows(prices, window_days=30)

        # Should create 30 samples (60 - 30)
        assert X.shape == (30, 30)
        assert y.shape == (30,)

    def test_create_sliding_windows_chronological_order(self):
        """Test that windows preserve chronological order."""
        prices = [Decimal(50000 + i * 100) for i in range(40)]

        X, y = create_sliding_windows(prices, window_days=10)

        # First sample should be days 0-9, predicting day 10
        assert X[0, 0] == 50000  # First price
        assert X[0, -1] == 50900  # 10th price
        assert y[0] == 51000  # 11th price

        # Last sample should be days 29-38, predicting day 39
        assert X[-1, 0] == 52900
        assert X[-1, -1] == 53800
        assert y[-1] == 53900
