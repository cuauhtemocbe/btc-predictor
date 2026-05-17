"""
Shared test fixtures for workers.daily tests.
"""

import numpy as np
import pytest


@pytest.fixture
def synthetic_prices_60_days() -> np.ndarray:
    """
    Generate 60 days of synthetic BTC close prices.

    Returns a linear trend with small random noise to simulate
    realistic price movement for testing purposes.

    Returns:
        numpy array of shape (60,) with float64 values representing
        BTC close prices in USD.

    Example:
        >>> prices = synthetic_prices_60_days()
        >>> assert prices.shape == (60,)
        >>> assert all(price > 0 for price in prices)
    """
    # Start at $50,000, end around $51,500 (upward trend)
    base_prices = np.linspace(50000, 51500, 60)
    # Add random noise (+/- $500)
    noise = np.random.uniform(-500, 500, 60)
    prices = base_prices + noise
    return prices


@pytest.fixture
def sliding_window_data(
    synthetic_prices_60_days: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate sliding window features and labels from 60 days of prices.

    Uses a 30-day window to predict the next day's price.
    With 60 days of data, this creates 30 training samples:
    - Sample 1: days 1-30 → predict day 31
    - Sample 2: days 2-31 → predict day 32
    - ...
    - Sample 30: days 30-59 → predict day 60

    Args:
        synthetic_prices_60_days: 60 days of close prices

    Returns:
        Tuple (X, y) where:
        - X: Feature matrix of shape (30, 30) - 30 samples, 30 features each
        - y: Target vector of shape (30,) - next day's price for each sample

    Example:
        >>> X, y = sliding_window_data(synthetic_prices_60_days)
        >>> assert X.shape == (30, 30)
        >>> assert y.shape == (30,)
    """
    window_days = 30
    prices = synthetic_prices_60_days

    n_samples = len(prices) - window_days
    X = np.zeros((n_samples, window_days))
    y = np.zeros(n_samples)

    for i in range(n_samples):
        X[i] = prices[i : i + window_days]
        y[i] = prices[i + window_days]

    return X, y


@pytest.fixture
def last_30_days(synthetic_prices_60_days: np.ndarray) -> np.ndarray:
    """
    Get the last 30 days of prices for making a single prediction.

    This fixture is used to test the predict() method.

    Args:
        synthetic_prices_60_days: 60 days of close prices

    Returns:
        numpy array of shape (1, 30) - last 30 close prices

    Example:
        >>> X_new = last_30_days(synthetic_prices_60_days)
        >>> assert X_new.shape == (1, 30)
    """
    return synthetic_prices_60_days[-30:].reshape(1, -1)
