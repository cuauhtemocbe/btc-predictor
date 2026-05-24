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
from shared.db.models import BtcPrice

from workers.daily.models import LinearRegressionModel
from workers.daily.trainer import (
    calculate_dynamic_window,
    count_available_days,
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
        price_record = BtcPrice(
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

    def test_train_all_models_success(self, db_session, sample_prices):
        """Test successful training of all models with dynamic window."""
        # Train all models (200 days -> Phase 5 Optimal: window=30, min=60)
        # Should train all 4 models including ARIMA (200 days >= 60)
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

    def test_train_all_models_activates_best(self, db_session, sample_prices):
        """
        Test that train_all_models activates the model with lowest error.

        Lowest validation error.
        """
        models = train_all_models(db_session)

        # Get active model
        active = get_active_model(db_session)
        assert active is not None

        # Verify active model has lowest validation error among trained models
        active_error = active.params["validation_error_pct"]

        for model in models:
            if model.id != active.id:
                # Other models should have equal or higher error
                assert (
                    model.params["validation_error_pct"] >= active_error
                    or abs(model.params["validation_error_pct"] - active_error) < 0.01
                )

    def test_train_all_models_uses_same_data(self, db_session, sample_prices):
        """Test that all models are trained on the same training data."""
        models = train_all_models(db_session)

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
        models = train_all_models(db_session)

        # At minimum, Linear Regression should always work
        model_names = [m.name for m in models]
        assert any("linear" in name for name in model_names)

    def test_train_all_models_insufficient_data_raises_error(self, db_session):
        """Test that train_all_models raises ValueError with insufficient data."""
        # Create only 39 days of data (< 40 min for Phase 1)
        for i in range(39):
            price_record = BtcPrice(
                timestamp=datetime.now(UTC) - timedelta(days=39 - i),
                open=Decimal(50000 + i * 100),
                high=Decimal(50000 + i * 100 + 500),
                low=Decimal(50000 + i * 100 - 500),
                close=Decimal(50000 + i * 100),
                volume=Decimal("1000.5"),
                source="binance",
            )
            db_session.add(price_record)

        db_session.commit()

        # Should raise ValueError (39 days < 40 minimum)
        with pytest.raises(ValueError, match="Insufficient data for training"):
            train_all_models(db_session)

    def test_train_all_models_excludes_arima_with_limited_data(self, db_session):
        """Test that ARIMA is excluded when less than 60 days available."""
        # Create 55 days of data (Phase 2: enough for training but not for ARIMA)
        for i in range(55):
            price_record = BtcPrice(
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

        # Train with automatic configuration (55 days -> Phase 2: window=10, min=55)
        models = train_all_models(db_session)

        # Should have 3 models (linear, lstm, xgboost) but NOT arima
        assert len(models) == 3
        model_names = [m.name for m in models]
        assert not any("arima" in name for name in model_names)
        assert any("linear" in name for name in model_names)
        assert any("lstm" in name for name in model_names)
        assert any("xgboost" in name for name in model_names)


class TestCalculateDynamicWindow:
    """Test calculate_dynamic_window function."""

    def test_phase_1_initial(self):
        """Test Phase 1: 40-54 days -> window=7, min=40."""
        window, min_days = calculate_dynamic_window(45)
        assert window == 7
        assert min_days == 40

    def test_phase_2_growth(self):
        """Test Phase 2: 55-74 days -> window=10, min=55."""
        window, min_days = calculate_dynamic_window(60)
        assert window == 10
        assert min_days == 55

    def test_phase_3_intermediate(self):
        """Test Phase 3: 75-109 days -> window=14, min=75."""
        window, min_days = calculate_dynamic_window(90)
        assert window == 14
        assert min_days == 75

    def test_phase_4_mature(self):
        """Test Phase 4: 110-154 days -> window=21, min=110."""
        window, min_days = calculate_dynamic_window(120)
        assert window == 21
        assert min_days == 110

    def test_phase_5_optimal(self):
        """Test Phase 5: 155+ days -> window=30, min=155."""
        window, min_days = calculate_dynamic_window(200)
        assert window == 30
        assert min_days == 155

    def test_insufficient_data_raises_error(self):
        """Test that less than 40 days raises ValueError."""
        with pytest.raises(ValueError, match="Insufficient data for training"):
            calculate_dynamic_window(39)

    def test_edge_case_boundaries(self):
        """Test boundary values between phases."""
        # Exactly 40 days -> Phase 1
        assert calculate_dynamic_window(40) == (7, 40)
        # Exactly 55 days -> Phase 2
        assert calculate_dynamic_window(55) == (10, 55)
        # Exactly 75 days -> Phase 3
        assert calculate_dynamic_window(75) == (14, 75)
        # Exactly 110 days -> Phase 4
        assert calculate_dynamic_window(110) == (21, 110)
        # Exactly 155 days -> Phase 5
        assert calculate_dynamic_window(155) == (30, 155)


class TestCountAvailableDays:
    """Test count_available_days function."""

    def test_count_available_days(self, db_session):
        """Test counting distinct days of price data."""
        # Create 10 days of data with 6 records per day (4-hour candles)
        # Start from a fixed date to avoid timezone issues
        from datetime import datetime as dt

        base_time = dt(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        for day in range(10):
            for hour in [0, 4, 8, 12, 16, 20]:  # 6 candles per day
                price_record = BtcPrice(
                    timestamp=base_time + timedelta(days=day, hours=hour),
                    open=Decimal(50000),
                    high=Decimal(51000),
                    low=Decimal(49000),
                    close=Decimal(50000),
                    volume=Decimal("1000.5"),
                    source="coingecko",
                )
                db_session.add(price_record)

        db_session.commit()

        # Should count 10 distinct days despite having 60 records
        count = count_available_days(db_session)
        assert count == 10

    def test_count_available_days_empty_database(self, db_session):
        """Test counting with empty database."""
        count = count_available_days(db_session)
        assert count == 0


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
