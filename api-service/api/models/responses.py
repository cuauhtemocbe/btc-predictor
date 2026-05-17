"""Response models for API endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BtcPriceResponse(BaseModel):
    """
    Bitcoin OHLCV price data response.

    Used by GET /api/prices endpoint to return historical price data.

    Example JSON:
    ```json
    {
        "timestamp": "2024-01-15T14:00:00+00:00",
        "open": 42350.50,
        "high": 42580.75,
        "low": 42280.00,
        "close": 42500.25,
        "volume": 1250.75,
        "source": "coingecko"
    }
    ```
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str

    model_config = ConfigDict(from_attributes=True)
