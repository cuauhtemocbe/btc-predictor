"""Strategy metrics calculation utilities."""

from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from shared.db.crud import source_filter
from shared.db.models import Model, Prediction, PredictionSource
from shared.returns import (
    max_drawdown_pct,
    returns_from_pnl,
    sharpe_ratio,
    worst_trade_pct,
)


def calculate_strategy_metrics(
    predictions: list[Prediction], strategy_key: str
) -> dict[str, Any]:
    """Aggregate metrics of one PnL strategy.

    Dollar figures (total, average win and loss) come from the stored ``pnl_*``
    column. Risk figures come from returns, ``pnl / price_at_prediction``, compounded
    from 1.0 and recomputed on read (#177). A prediction whose price is not positive
    counts in the dollar figures and the trade count, not in the risk figures.

    Args:
        predictions: Predictions with evaluated PnL values.
        strategy_key: ``pnl_simulated``, ``pnl_long_short``, ``pnl_threshold`` or
            ``pnl_realistic``.

    Returns:
        ``total_pnl``, ``win_rate`` (0-1), ``worst_trade_pct``, ``max_drawdown_pct``,
        ``avg_win``, ``avg_loss``, ``sharpe_ratio`` (annualized, risk-free rate 0; 0.0
        with fewer than 2 returns or no variance) and ``trade_count``.
    """
    # Evaluated predictions of this strategy, oldest first so the equity curve is in
    # time order; Decimal is converted to float for numpy.
    evaluated = sorted(
        (
            pred
            for pred in predictions
            if pred.actual_price is not None and getattr(pred, strategy_key) is not None
        ),
        key=lambda p: p.predicted_for,
    )
    pnl_values = [float(getattr(pred, strategy_key)) for pred in evaluated]

    # Handle zero trades case
    if not pnl_values:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "worst_trade_pct": 0.0,
            "max_drawdown_pct": 0.0,
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

    win_rate = len(wins) / trade_count
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0

    returns = returns_from_pnl(
        (getattr(pred, strategy_key), pred.price_at_prediction) for pred in evaluated
    )
    worst_trade = worst_trade_pct(returns)
    max_drawdown = max_drawdown_pct(returns)
    sharpe = sharpe_ratio(returns)

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4),
        "worst_trade_pct": round(worst_trade or 0.0, 2),
        "max_drawdown_pct": round(max_drawdown or 0.0, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "sharpe_ratio": round(sharpe or 0.0, 2),
        "trade_count": trade_count,
    }


def calculate_cumulative_pnl(
    predictions: list[Prediction], strategy_key: str
) -> list[dict[str, Any]]:
    """Running sum of the strategy PnL by prediction date.

    Returns:
        Dicts with ``date`` (ISO) and ``cumulative_pnl``.
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
    db: Session,
    timeframe: str | None = None,
    symbol: str | None = None,
    source: PredictionSource = PredictionSource.ALL,
) -> list[dict[str, Any]]:
    """Metrics of the four PnL strategies, one dict per strategy with its name.

    Args:
        db: Database session.
        timeframe: Optional filter; ``None`` mixes every timeframe in one series.
        symbol: Optional filter on the predicting model's symbol.
        source: ``live``, ``replay`` or ``all`` (default), by the predicting model.
    """
    strategies = [
        {"name": "simple", "key": "pnl_simulated", "color": "blue"},
        {"name": "long_short", "key": "pnl_long_short", "color": "green"},
        {"name": "threshold", "key": "pnl_threshold", "color": "orange"},
        {"name": "realistic", "key": "pnl_realistic", "color": "purple"},
    ]

    # Fetch all predictions (will reuse for all strategies)
    query = db.query(Prediction).join(Model, Prediction.model_id == Model.id)
    if symbol:
        query = query.filter(Model.symbol == symbol)
    query = query.filter(source_filter(source))
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
