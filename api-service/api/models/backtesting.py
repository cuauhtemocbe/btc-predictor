"""Response models for backtesting API endpoints."""

from datetime import date

from pydantic import BaseModel, Field


class BacktestMetadata(BaseModel):
    """Metadata about a backtest run."""

    backtest_run_id: str = Field(description="UUID of the backtest run")
    start_date: date = Field(description="First prediction date in backtest")
    end_date: date = Field(description="Last prediction date in backtest")
    total_days: int = Field(description="Number of days in backtest period")
    model_name: str | None = Field(
        default=None, description="Model name from params (if available)"
    )


class BacktestStrategyMetrics(BaseModel):
    """Performance metrics for a single strategy in backtesting."""

    name: str = Field(description="Strategy identifier (e.g., 'simple', 'long_short')")
    display_name: str = Field(description="Human-readable strategy name")
    color: str = Field(description="Chart color for this strategy")
    total_pnl: float = Field(description="Total accumulated PnL")
    win_rate: float = Field(description="Percentage of winning trades (0-1)")
    max_drawdown: float = Field(description="Worst single-day loss")
    best_day: float = Field(description="Best single-day PnL")
    worst_day: float = Field(description="Worst single-day PnL")
    sharpe_ratio: float = Field(description="Risk-adjusted return metric")
    trade_count: int = Field(description="Number of trades executed")


class DailyPnlPoint(BaseModel):
    """PnL values for all strategies on a single date."""

    date: str = Field(description="Date in ISO format (YYYY-MM-DD)")
    simple: float | None = Field(default=None, description="Simple strategy PnL")
    long_short: float | None = Field(
        default=None, description="Long/Short strategy PnL"
    )
    threshold: float | None = Field(default=None, description="Threshold strategy PnL")
    realistic: float | None = Field(default=None, description="Realistic strategy PnL")


class BacktestMetricsResponse(BaseModel):
    """
    Complete backtesting results with metadata, strategy metrics, and daily PnL.

    Used by GET /api/backtesting/metrics endpoint.

    Example JSON:
    ```json
    {
        "metadata": {
            "backtest_run_id": "abc-123-...",
            "start_date": "2024-05-01",
            "end_date": "2024-05-30",
            "total_days": 30,
            "model_name": "linear_v1"
        },
        "strategies": [
            {
                "name": "simple",
                "display_name": "Simple",
                "color": "blue",
                "total_pnl": 1200.50,
                "win_rate": 0.63,
                "max_drawdown": -450.00,
                "best_day": 320.00,
                "worst_day": -450.00,
                "sharpe_ratio": 1.25,
                "trade_count": 30
            },
            ...
        ],
        "daily_pnl": [
            {
                "date": "2024-05-01",
                "simple": 100.0,
                "long_short": 120.0,
                "threshold": 90.0,
                "realistic": 85.0
            },
            ...
        ]
    }
    ```
    """

    metadata: BacktestMetadata = Field(description="Backtest run metadata")
    strategies: list[BacktestStrategyMetrics] = Field(
        description="Performance metrics for each strategy"
    )
    daily_pnl: list[DailyPnlPoint] = Field(
        description="Daily PnL values for all strategies"
    )
