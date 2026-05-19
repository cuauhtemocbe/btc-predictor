"""
Utility functions for BTC Predictor.

Functions:
- calculate_pnl: Calculate simulated profit/loss from prediction strategy
- calculate_pnl_long_short: Calculate PnL with long/short symmetric strategy
- calculate_pnl_threshold: Calculate PnL with threshold filter
- calculate_pnl_realistic: Calculate PnL with trading fees and stop-loss
"""

from decimal import Decimal


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
