"""Strategy metrics calculation utilities."""

from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from shared.db.models import Prediction


def calculate_strategy_metrics(
    predictions: list[Prediction], strategy_key: str
) -> dict[str, Any]:
    """
    Calculate aggregate performance metrics for a given PnL strategy.

    Args:
        predictions: List of Prediction objects with evaluated PnL values
        strategy_key: One of 'pnl_simulated', 'pnl_long_short',
            'pnl_threshold', 'pnl_realistic'

    Returns:
        Dictionary with metrics:
        - total_pnl: Sum of all PnL values
        - win_rate: Percentage of winning trades (0-1)
        - max_drawdown: Worst single loss
        - avg_win: Average of positive PnL values
        - avg_loss: Average of negative PnL values
        - sharpe_ratio: Risk-adjusted return metric (simplified, risk-free rate = 0)
        - trade_count: Number of trades
    """
    # Extract PnL values for this strategy (only evaluated predictions)
    # Convert Decimal to float to avoid type issues with numpy operations
    pnl_values = [
        float(getattr(pred, strategy_key))
        for pred in predictions
        if pred.actual_price is not None and getattr(pred, strategy_key) is not None
    ]

    # Handle zero trades case
    if not pnl_values:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "sharpe_ratio": 0.0,
            "trade_count": 0,
        }

    # Calculate basic metrics
    total_pnl = sum(pnl_values)
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p < 0]
    trade_count = len(pnl_values)

    win_rate = len(wins) / trade_count if trade_count > 0 else 0.0
    max_drawdown = min(pnl_values) if pnl_values else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0

    # Calculate Sharpe Ratio (simplified)
    # Note: Using PnL values directly as "returns"
    # In production, you'd calculate actual percentage returns
    if trade_count >= 2 and np.std(pnl_values) > 0:
        sharpe_ratio = float(np.mean(pnl_values) / np.std(pnl_values))
    else:
        sharpe_ratio = 0.0

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(max_drawdown, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "trade_count": trade_count,
    }


def calculate_cumulative_pnl(
    predictions: list[Prediction], strategy_key: str
) -> list[dict[str, Any]]:
    """
    Calculate cumulative PnL over time for a given strategy.

    Args:
        predictions: List of Prediction objects with evaluated PnL values
        strategy_key: One of 'pnl_simulated', 'pnl_long_short',
            'pnl_threshold', 'pnl_realistic'

    Returns:
        List of dicts with:
        - date: Prediction date (ISO format)
        - cumulative_pnl: Running sum of PnL up to that date
    """
    # Filter and sort predictions by date
    evaluated_preds = [
        pred
        for pred in predictions
        if pred.actual_price is not None and getattr(pred, strategy_key) is not None
    ]
    evaluated_preds.sort(key=lambda p: p.predicted_for)

    cumulative = 0.0
    result = []

    for pred in evaluated_preds:
        pnl = getattr(pred, strategy_key)
        cumulative += float(pnl)
        result.append(
            {
                "date": pred.predicted_for.isoformat(),
                "cumulative_pnl": round(cumulative, 2),
            }
        )

    return result


def get_all_strategies_metrics(
    db: Session, timeframe: str | None = None
) -> list[dict[str, Any]]:
    """
    Calculate metrics for all 4 PnL strategies.

    Args:
        db: Database session
        timeframe: Optional timeframe filter ('1h', '1d', '1w'). If None,
            every timeframe is mixed together in one series.

    Returns:
        List of dicts, one per strategy with name and metrics
    """
    strategies = [
        {"name": "simple", "key": "pnl_simulated", "color": "blue"},
        {"name": "long_short", "key": "pnl_long_short", "color": "green"},
        {"name": "threshold", "key": "pnl_threshold", "color": "orange"},
        {"name": "realistic", "key": "pnl_realistic", "color": "purple"},
    ]

    # Fetch all predictions (will reuse for all strategies)
    query = db.query(Prediction)
    if timeframe:
        query = query.filter(Prediction.timeframe == timeframe)
    predictions = query.order_by(Prediction.predicted_for).all()

    results = []
    for strategy in strategies:
        metrics = calculate_strategy_metrics(predictions, strategy["key"])
        cumulative = calculate_cumulative_pnl(predictions, strategy["key"])

        results.append(
            {
                "name": strategy["name"],
                "display_name": strategy["name"].replace("_", " ").title(),
                "color": strategy["color"],
                **metrics,
                "cumulative_pnl": cumulative,
            }
        )

    return results
