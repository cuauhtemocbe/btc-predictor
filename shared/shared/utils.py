"""
Utility functions for BTC Predictor.

Functions:
- calculate_pnl: Calculate simulated profit/loss from prediction strategy
- calculate_pnl_long_short: Calculate PnL with long/short symmetric strategy
- calculate_pnl_threshold: Calculate PnL with threshold filter
- calculate_pnl_realistic: Calculate PnL with trading fees and stop-loss
- split_train_validation: Split time series data into train/validation sets
- calculate_mape: Calculate Mean Absolute Percentage Error
"""

from decimal import Decimal

import numpy as np


def calculate_pnl(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> Decimal:
    """
    Calculate simulated profit/loss (PnL) from a prediction-based trading strategy.

    Strategy:
    - If predicted_price > price_at_prediction (predicted UP):
      → Go long 1 BTC at price_at_prediction
      → PnL = actual_price - price_at_prediction
    - Else (predicted DOWN or flat):
      → Stay in cash (no trade)
      → PnL = 0

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time

    Returns:
        Simulated PnL in USDT (positive = profit, negative = loss, 0 = no trade)

    Examples:
        >>> calculate_pnl(Decimal("67000"), Decimal("66000"), Decimal("67500"))
        Decimal('1500.00')  # Predicted UP, actual UP → profit

        >>> calculate_pnl(Decimal("67000"), Decimal("66000"), Decimal("65000"))
        Decimal('-1000.00')  # Predicted UP, actual DOWN → loss

        >>> calculate_pnl(Decimal("65000"), Decimal("66000"), Decimal("64000"))
        Decimal('0.00')  # Predicted DOWN → no trade
    """
    # If predicted UP (prediction higher than current), go long
    if predicted_price > price_at_prediction:
        pnl = actual_price - price_at_prediction
    else:
        # Predicted DOWN or flat → stay in cash
        pnl = Decimal("0.00")

    return pnl


def calculate_pnl_long_short(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
) -> Decimal:
    """
    Calculate PnL from long/short symmetric trading strategy.

    Strategy:
    - If predicted_price > price_at_prediction (predicted UP):
      → Go long 1 BTC at price_at_prediction
      → PnL = actual_price - price_at_prediction
    - Else (predicted DOWN):
      → Go short 1 BTC at price_at_prediction
      → PnL = price_at_prediction - actual_price

    This strategy profits from correct predictions in BOTH directions.

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time

    Returns:
        PnL in USDT (positive = profit, negative = loss)
    """
    if predicted_price > price_at_prediction:
        # Long position
        pnl = actual_price - price_at_prediction
    else:
        # Short position
        pnl = price_at_prediction - actual_price

    return pnl


def calculate_pnl_threshold(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
    threshold: Decimal = Decimal("1.0"),
) -> Decimal:
    """
    Calculate PnL with threshold filter: only trade if predicted change > threshold %.

    Strategy:
    - Calculate predicted change percentage
    - If abs(change) < threshold → no trade, PnL = 0
    - Else → apply long/short symmetric strategy

    This avoids trading on weak signals and reduces transaction costs.

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time
        threshold: Minimum predicted change % to trigger trade (default 1.0%)

    Returns:
        PnL in USDT (positive = profit, negative = loss, 0 = no trade)
    """
    # Calculate predicted change percentage
    change_pct = abs(
        (predicted_price - price_at_prediction) / price_at_prediction * 100
    )

    # If change below threshold, no trade
    if change_pct < threshold:
        return Decimal("0.00")

    # Otherwise, use long/short symmetric strategy
    return calculate_pnl_long_short(predicted_price, price_at_prediction, actual_price)


def calculate_pnl_realistic(
    predicted_price: Decimal,
    price_at_prediction: Decimal,
    actual_price: Decimal,
    fee_pct: Decimal = Decimal("0.1"),
    stop_loss_pct: Decimal = Decimal("2.0"),
) -> Decimal:
    """
    Calculate PnL with realistic trading conditions: fees and stop-loss.

    Strategy:
    - Apply long/short symmetric strategy
    - Deduct trading fees: fee_pct * price_at_prediction * 2 (entry + exit)
    - Apply stop-loss: cap loss at stop_loss_pct * price_at_prediction

    This simulates real trading with transaction costs and risk management.

    Args:
        predicted_price: The predicted BTC price
        price_at_prediction: BTC price when prediction was made
        actual_price: Actual BTC price at evaluation time
        fee_pct: Trading fee percentage per trade (default 0.1%)
        stop_loss_pct: Maximum loss percentage before stop-loss triggers (default 2%)

    Returns:
        PnL in USDT after fees and stop-loss (positive = profit, negative = loss)
    """
    # Calculate gross PnL using long/short symmetric strategy
    gross_pnl = calculate_pnl_long_short(
        predicted_price, price_at_prediction, actual_price
    )

    # Calculate trading fees (entry + exit = 2 trades)
    fees = price_at_prediction * (fee_pct / 100) * 2

    # Calculate maximum loss (stop-loss limit)
    max_loss = price_at_prediction * (stop_loss_pct / 100)

    # Apply stop-loss: cap gross loss at max_loss
    if gross_pnl < -max_loss:
        gross_pnl = -max_loss

    # Net PnL after fees
    net_pnl = gross_pnl - fees

    return net_pnl


def split_train_validation(
    prices: np.ndarray,
    train_pct: float = 0.7,
    val_pct: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Split time series price data into training and validation sets.

    Uses 70% for training, 20% for validation, and discards remaining 10%
    (buffer for time series continuity).

    Args:
        prices: 1D array of historical prices (chronological order)
        train_pct: Percentage of data for training (default 0.7 = 70%)
        val_pct: Percentage of data for validation (default 0.2 = 20%)

    Returns:
        Tuple of (train_data, val_data) as numpy arrays

    Raises:
        ValueError: If train_pct + val_pct > 1.0 or if not enough data

    Examples:
        >>> prices = np.array([50000, 51000, 52000, ..., 67000])  # 100 days
        >>> train, val = split_train_validation(prices)
        >>> len(train)  # 70 days
        70
        >>> len(val)  # 20 days
        20
    """
    if train_pct + val_pct > 1.0:
        raise ValueError(
            f"train_pct ({train_pct}) + val_pct ({val_pct}) must be <= 1.0"
        )

    n = len(prices)
    if n < 10:
        raise ValueError(f"Need at least 10 data points, got {n}")

    # Calculate split indices
    train_size = int(n * train_pct)
    val_size = int(n * val_pct)

    if train_size < 1 or val_size < 1:
        raise ValueError(
            f"Not enough data: train_size={train_size}, val_size={val_size}"
        )

    # Split chronologically
    train_data = prices[:train_size]
    val_data = prices[train_size : train_size + val_size]
    # Buffer (remaining 10%) is discarded

    return train_data, val_data


def calculate_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Calculate Mean Absolute Percentage Error (MAPE).

    MAPE = mean(|y_true - y_pred| / |y_true|) * 100

    Args:
        y_true: Array of true values
        y_pred: Array of predicted values

    Returns:
        MAPE as percentage (0-100 scale)

    Raises:
        ValueError: If arrays have different lengths or contain zeros

    Examples:
        >>> y_true = np.array([50000, 51000, 52000])
        >>> y_pred = np.array([50500, 50800, 52100])
        >>> calculate_mape(y_true, y_pred)
        1.05  # ~1% average error
    """
    if len(y_true) != len(y_pred):
        raise ValueError(
            f"Arrays must have same length: {len(y_true)} != {len(y_pred)}"
        )

    if len(y_true) == 0:
        raise ValueError("Cannot calculate MAPE on empty arrays")

    # Avoid division by zero
    if np.any(y_true == 0):
        raise ValueError("y_true contains zeros, cannot calculate MAPE")

    # Calculate absolute percentage errors
    abs_errors = np.abs((y_true - y_pred) / y_true)

    # Return mean as percentage
    mape = float(np.mean(abs_errors) * 100)

    return mape
