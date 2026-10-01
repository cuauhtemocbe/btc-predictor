"""
Tests for trainer module - multi-model training functionality.

Covers:
- train_single_model: Train one model with validation
- train_all_models: Train all 4 models and select best
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from shared.db.crud import get_active_model, get_all_models
from shared.db.models import Price
from workers.daily import trainer
from workers.daily.models import LinearRegressionModel
from workers.daily.trainer import (
    create_sliding_windows,
    train_all_models,
    train_single_model,
)


@pytest.fixture
def sample_prices(db_session):
    """Create 200 days of sample BTC prices for testing.

    Note: 200 days ensures enough data after train/val split (70%/20%):
    - Train: 140 days -> 110 samples with window_days=30
    - Validation: 40 days -> 10 samples with window_days=30
    """
    base_price = 50000
    prices = []

    for i in range(200):
        price_record = Price(
            timestamp=datetime.now(UTC) - timedelta(days=200 - i),
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


class _BiasedModel(LinearRegressionModel):
    """Linear model that is always 10% off, so it validates worse."""

    def predict(self, X):
        return super().predict(X) * 1.1


class _BrokenModel(LinearRegressionModel):
    """Model whose training always fails."""

    def train(self, X, y):
        raise RuntimeError("cannot converge")


@pytest.fixture
def model_registry(monkeypatch):
    """Replace the trained models with cheap ones (no TensorFlow/XGBoost).

    The real LSTM/XGBoost/ARIMA are covered by their own tests
    (``--run-non-linear``, #124); these tests are about the orchestration.
    Returns the registry dict so a test can add models to it.
    """
    registry = {"linear": LinearRegressionModel, "biased": _BiasedModel}
    monkeypatch.setattr(trainer, "model_registry", lambda days_available: registry)
    return registry


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
        import logging

        # Set log level to capture INFO messages
        caplog.set_level(logging.INFO)

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

    @pytest.mark.non_linear
    def test_train_all_models_success(self, db_session, sample_prices):
        """Test successful training of all models with the configured window."""
        # 200 days >= 60, so ARIMA is included next to linear, lstm and xgboost
        models = train_all_models(db_session)

        # Verify we got models back (should be 4: linear, lstm, xgboost, arima)
        assert len(models) >= 3  # At least 3 models should succeed
        assert len(models) <= 4  # Maximum 4 models

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

        # Verify ARIMA is included (200 days >= 60)
        model_names = [m.name for m in models]
        assert any("arima" in name for name in model_names)

    @pytest.mark.usefixtures("model_registry")
    def test_train_all_models_activates_best(self, db_session, sample_prices):
        """
        Test that train_all_models activates the model with lowest error.

        Lowest validation error.
        """
        models = train_all_models(db_session)

        # Get active model
        active = get_active_model(db_session)
        assert active is not None
        assert active.name.startswith("linear")

        # Verify active model has lowest validation error among trained models
        active_error = active.params["validation_error_pct"]

        assert len(models) == 2
        for model in models:
            if model.id != active.id:
                # Other models should have equal or higher error
                assert model.params["validation_error_pct"] > active_error

    @pytest.mark.usefixtures("model_registry")
    def test_train_all_models_uses_same_data(self, db_session, sample_prices):
        """Test that all models are trained on the same training data."""
        models = train_all_models(db_session)

        # All models should have same number of training samples
        training_samples = models[0].params["training_samples"]
        validation_samples = models[0].params["validation_samples"]

        assert len(models) == 2
        for model in models:
            assert model.params["training_samples"] == training_samples
            assert model.params["validation_samples"] == validation_samples

    def test_train_all_models_handles_partial_failures(
        self, db_session, sample_prices, model_registry
    ):
        """Test that train_all_models continues if one model fails."""
        model_registry["broken"] = _BrokenModel

        models = train_all_models(db_session)

        model_names = [m.name for m in models]
        assert any("linear" in name for name in model_names)
        assert not any("broken" in name for name in model_names)
        assert get_active_model(db_session) is not None

    def test_train_all_models_insufficient_data_raises_error(self, db_session):
        """train_all_models fails when fewer rows are stored than the split needs."""
        # 29 rows < (21 + 1) * 5 = 110 required for the default window
        for i in range(29):
            price_record = Price(
                timestamp=datetime.now(UTC) - timedelta(days=29 - i),
                open=Decimal(50000 + i * 100),
                high=Decimal(50000 + i * 100 + 500),
                low=Decimal(50000 + i * 100 - 500),
                close=Decimal(50000 + i * 100),
                volume=Decimal("1000.5"),
                source="binance",
            )
            db_session.add(price_record)

        db_session.commit()

        with pytest.raises(ValueError, match=r"need 110 daily rows.*have 29"):
            train_all_models(db_session)

    @pytest.mark.non_linear
    def test_train_all_models_excludes_arima_with_limited_data(self, db_session):
        """Test that ARIMA is excluded when less than 60 days available."""
        # 55 days: enough for window=10 ((10 + 1) * 5 = 55) but not for ARIMA
        for i in range(55):
            price_record = Price(
                timestamp=datetime.now(UTC) - timedelta(days=55 - i),
                open=Decimal(50000 + i * 100),
                high=Decimal(50000 + i * 100 + 500),
                low=Decimal(50000 + i * 100 - 500),
                close=Decimal(50000 + i * 100),
                volume=Decimal("1000.5"),
                source="coingecko",
            )
            db_session.add(price_record)

        db_session.commit()

        models = train_all_models(db_session, window_days=10)

        # Should have 3 models (linear, lstm, xgboost) but NOT arima
        assert len(models) == 3
        model_names = [m.name for m in models]
        assert not any("arima" in name for name in model_names)
        assert any("linear" in name for name in model_names)
        assert any("lstm" in name for name in model_names)
        assert any("xgboost" in name for name in model_names)


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

    def test_create_sliding_windows_horizon_days_default_matches_1_day_ahead(self):
        """horizon_days defaults to 1, reproducing the original daily behavior."""
        prices = [Decimal(50000 + i * 100) for i in range(40)]

        X_default, y_default = create_sliding_windows(prices, window_days=10)
        X_explicit, y_explicit = create_sliding_windows(
            prices, window_days=10, horizon_days=1
        )

        assert X_default.shape == X_explicit.shape
        assert (X_default == X_explicit).all()
        assert (y_default == y_explicit).all()

    def test_create_sliding_windows_seven_day_horizon(self):
        """
        Scenario: Training creates a seven-day-ahead target (issue #61)

        Given chronological daily prices
        When sliding windows are created with horizon_days=7
        Then each target is 7 days past the end of its window, not 1
        """
        prices = [Decimal(50000 + i * 100) for i in range(40)]

        X, y = create_sliding_windows(prices, window_days=10, horizon_days=7)

        # 40 - 10 - 7 + 1 = 24 samples
        assert X.shape == (24, 10)
        assert y.shape == (24,)

        # First sample: window is days 0-9 (prices 50000..50900), target is
        # 7 days after day 9 -> day 16 (index 16, price 51600)
        assert X[0, 0] == 50000
        assert X[0, -1] == 50900
        assert y[0] == 51600

        # Last sample: window is days 23-32, target is day 39 (index 39,
        # last price in the series)
        assert X[-1, 0] == 52300
        assert X[-1, -1] == 53200
        assert y[-1] == 53900

    def test_create_sliding_windows_minimum_data_for_one_sample(self):
        """Exactly window_days + horizon_days prices yields exactly one sample."""
        window_days, horizon_days = 10, 7
        prices = [Decimal(50000 + i * 100) for i in range(window_days + horizon_days)]

        X, y = create_sliding_windows(
            prices, window_days=window_days, horizon_days=horizon_days
        )

        assert X.shape == (1, window_days)
        assert y.shape == (1,)
        assert y[0] == prices[-1]  # target is the very last (17th) price
