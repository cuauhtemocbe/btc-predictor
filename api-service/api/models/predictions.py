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
