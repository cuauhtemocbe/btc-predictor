"""Response models for predictions API endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PredictionHistoryResponse(BaseModel):
    """
    Evaluated prediction with error metrics and model information.

    Used by GET /api/predictions/history endpoint to return historical
    predictions with evaluation results.

    Example JSON:
    ```json
    {
        "predicted_for": "2026-05-17",
        "predicted_at": "2026-05-16T19:00:00+00:00",
        "price_at_prediction": 67000.0,
        "predicted_price": 67500.0,
        "actual_price": 67800.0,
        "evaluated_at": "2026-05-17T07:01:00+00:00",
        "error_abs": 300.0,
        "error_pct": 0.44,
        "direction_correct": true,
        "pnl_simulated": 800.0,
        "model_name": "linear_v1",
        "model_version": "1.0.0"
    }
    ```
    """

    predicted_for: date = Field(description="Date the prediction was made for")
    predicted_at: datetime = Field(description="When the prediction was created")
    price_at_prediction: float = Field(
        description="BTC price at the time prediction was made"
    )
    predicted_price: float = Field(description="Predicted BTC price")
    actual_price: float = Field(description="Actual BTC price (evaluated)")
    evaluated_at: datetime = Field(description="When the prediction was evaluated")
    error_abs: float = Field(description="Absolute prediction error")
    error_pct: float = Field(description="Percentage prediction error")
    direction_correct: bool = Field(
        description="Whether predicted direction was correct"
    )
    pnl_simulated: float = Field(description="Simulated profit/loss")
    model_name: str = Field(description="Name of the model used")
    model_version: str = Field(description="Version of the model used")

    model_config = ConfigDict(from_attributes=True)


class PnlResponse(BaseModel):
    """
    Aggregated profit/loss summary across all evaluated predictions.

    Used by GET /api/predictions/pnl endpoint to return total accumulated
    PnL and count of evaluated predictions.

    Example JSON:
    ```json
    {
        "total_pnl": 12345.67,
        "evaluated_predictions": 30
    }
    ```
    """

    total_pnl: float = Field(
        description=(
            "Total accumulated profit/loss in USD "
            "across all evaluated predictions"
        )
    )
    evaluated_predictions: int = Field(
        description="Number of predictions that have been evaluated"
    )


class CumulativePnlPoint(BaseModel):
    """Single point in cumulative PnL time series."""

    date: str = Field(description="Prediction date (ISO format)")
    cumulative_pnl: float = Field(description="Cumulative PnL up to this date")


class StrategyMetrics(BaseModel):
    """
    Performance metrics for a single PnL strategy.

    Example JSON:
    ```json
    {
        "name": "long_short",
        "display_name": "Long Short",
        "color": "green",
        "total_pnl": 2800.50,
        "win_rate": 0.6300,
        "max_drawdown": -450.00,
        "avg_win": 220.30,
        "avg_loss": -180.50,
        "sharpe_ratio": 1.25,
        "trade_count": 30,
        "cumulative_pnl": [...]
    }
    ```
    """

    name: str = Field(description="Strategy identifier (e.g., 'long_short')")
    display_name: str = Field(description="Human-readable strategy name")
    color: str = Field(description="Chart color for this strategy")
    total_pnl: float = Field(description="Total accumulated PnL")
    win_rate: float = Field(description="Percentage of winning trades (0-1)")
    max_drawdown: float = Field(description="Worst single loss")
    avg_win: float = Field(description="Average profit of winning trades")
    avg_loss: float = Field(description="Average loss of losing trades")
    sharpe_ratio: float = Field(description="Risk-adjusted return metric")
    trade_count: int = Field(description="Number of trades executed")
    cumulative_pnl: list[CumulativePnlPoint] = Field(
        description="Time series of cumulative PnL"
    )


class StrategiesResponse(BaseModel):
    """
    Collection of metrics for all trading strategies.

    Used by GET /api/predictions/strategies endpoint.

    Example JSON:
    ```json
    {
        "strategies": [
            {
                "name": "simple",
                "display_name": "Simple",
                "color": "blue",
                "total_pnl": 1200.50,
                ...
            },
            ...
        ]
    }
    ```
    """

    strategies: list[StrategyMetrics] = Field(
        description="List of strategy performance metrics"
    )
