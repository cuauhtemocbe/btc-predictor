"""
Tests for trainer module - multi-model training functionality.

Covers:
- train_single_model: Train one model with validation
- train_all_models: Train every enabled model and select the best
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from shared.db.crud import get_active_model, get_all_models
from shared.db.models import Model, Price
from shared.features import LOG_RETURN_TARGET
from workers.daily import trainer
from workers.daily.models import LinearRegressionModel
from workers.daily.trainer import train_all_models, train_single_model


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

    The real LSTM/XGBoost/ARIMA are covered by their own tests and by
    ``test_train_all_models_success``; these tests are about the orchestration.
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

    def test_validation_error_is_measured_on_the_implied_prices(self):
        """With base closes the targets are log returns and the MAPE is on prices."""
        rng = np.random.default_rng(3)
        X_train = rng.normal(0, 0.02, (50, 5))
        y_train = X_train[:, 0]  # next return = last return, perfectly learnable
        X_val = rng.normal(0, 0.02, (10, 5))
        y_val = X_val[:, 0]
        base_close = np.full(10, 84000.0)

        model, error = train_single_model(
            model_class=LinearRegressionModel,
            model_name="linear",
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            window_days=5,
            base_close_val=base_close,
        )

        assert isinstance(model, LinearRegressionModel)
        assert model.n_features == 5
        assert error == pytest.approx(0, abs=1e-6)

        # A model whose return is 10% too large is ~0.1% off in price (a MAPE on the
        # raw returns would say ~10%)
        _, biased_error = train_single_model(
            model_class=_BiasedModel,
            model_name="biased",
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            window_days=5,
            base_close_val=base_close,
        )
        assert 0 < biased_error < 1

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
        """
        Gherkin Scenario: The trainer covers every enabled model again

        Given 200 daily rows, enough for every model
        When train_all_models runs with the configured window
        Then it returns the linear model and the LSTM, XGBoost and ARIMA models
        """
        models = train_all_models(db_session)

        # Linear, LSTM, XGBoost and ARIMA all trained (200 days >= 60 for ARIMA)
        assert {m.name for m in models} == {
            "linear_v1",
            "lstm_v1",
            "xgboost_v1",
            "arima_v1",
        }

        # Verify models are saved to database
        all_models = get_all_models(db_session)
        assert len(all_models) >= len(models)

        # Verify one model is active
        active = get_active_model(db_session)
        assert active is not None
        assert active.is_active is True

        # Verify all saved models have validation error and the return target
        for model in models:
            assert "validation_error_pct" in model.params
            assert "training_samples" in model.params
            assert "validation_samples" in model.params
            assert model.params["target"] == LOG_RETURN_TARGET

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

    def test_train_all_models_excludes_arima_with_limited_data(self, db_session):
        """
        Gherkin Scenario: ARIMA is excluded below its minimum data threshold

        Given 55 daily rows, fewer than the 60 ARIMA needs
        When train_all_models runs
        Then it returns the linear, LSTM and XGBoost models but not ARIMA
        """
        # 55 days: enough for window=5 to build the 70/20 split, but not for ARIMA
        for i in range(55):
            price_record = Price(
                timestamp=datetime.now(UTC) - timedelta(days=55 - i),
                open=Decimal(50000 + i * 100),
                high=Decimal(50000 + i * 100 + 500),
                low=Decimal(50000 + i * 100 - 500),
                close=Decimal(50000 + i * 100),
                volume=Decimal("1000.5"),
                source="binance",
            )
            db_session.add(price_record)

        db_session.commit()

        models = train_all_models(db_session, window_days=5)

        assert {m.name for m in models} == {"linear_v1", "lstm_v1", "xgboost_v1"}


class TestNextVersionNumber:
    """The version a newly trained model gets, derived from the latest saved one."""

    @staticmethod
    def _save_model(db_session, name, version):
        record = Model(
            name=f"{name}_{version}",
            version=version,
            params={},
            artifact=b"",
            trained_at=datetime.now(UTC),
            train_from=date(2026, 1, 1),
            train_to=date(2026, 1, 31),
            timeframe="1d",
            is_active=False,
        )
        db_session.add(record)
        db_session.commit()

    def test_starts_at_one_without_previous_model(self, db_session):
        assert trainer._next_version_number(db_session, "linear") == 1

    def test_increments_the_latest_version(self, db_session):
        self._save_model(db_session, "linear", "v3")

        assert trainer._next_version_number(db_session, "linear") == 4

    def test_restarts_at_one_when_version_is_not_numeric(self, db_session):
        self._save_model(db_session, "linear", "vbeta")

        assert trainer._next_version_number(db_session, "linear") == 1
