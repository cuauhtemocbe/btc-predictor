"""
Utility functions for BTC Predictor.

Functions:
- calculate_pnl: Calculate simulated profit/loss from prediction strategy
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
