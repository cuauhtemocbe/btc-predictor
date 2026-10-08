"""Response models for predictions API endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PredictionHistoryResponse(BaseModel):
    """Evaluated prediction and its model, from ``GET /api/predictions/history``."""

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
    timeframe: str = Field(description="Prediction timeframe ('1d')")
    is_replay: bool = Field(
        description=(
            "True when the model was trained by the history replay (simulated), "
            "false when the running system made the prediction"
        )
    )

    model_config = ConfigDict(from_attributes=True)


class PnlResponse(BaseModel):
    """Total simulated PnL and evaluated count, from ``GET /api/predictions/pnl``."""

    total_pnl: float = Field(
        description=(
            "Total accumulated profit/loss in USD across all evaluated predictions"
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
    """Performance metrics and cumulative PnL series of one PnL strategy."""

    name: str = Field(description="Strategy identifier (e.g., 'long_short')")
    display_name: str = Field(description="Human-readable strategy name")
    color: str = Field(description="Chart color for this strategy")
    total_pnl: float = Field(description="Total accumulated PnL")
    win_rate: float = Field(description="Percentage of winning trades (0-1)")
    worst_trade_pct: float = Field(description="Worst single-day return, in percent")
    max_drawdown_pct: float = Field(
        description="Max drawdown of the compounded equity curve, in percent"
    )
    avg_win: float = Field(description="Average profit of winning trades")
    avg_loss: float = Field(description="Average loss of losing trades")
    sharpe_ratio: float = Field(description="Risk-adjusted return metric")
    trade_count: int = Field(description="Number of trades executed")
    cumulative_pnl: list[CumulativePnlPoint] = Field(
        description="Time series of cumulative PnL"
    )


class StrategiesResponse(BaseModel):
    """Metrics of every strategy, from ``GET /api/predictions/strategies``."""

    strategies: list[StrategyMetrics] = Field(
        description="List of strategy performance metrics"
    )
