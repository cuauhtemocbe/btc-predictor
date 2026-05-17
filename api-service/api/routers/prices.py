"""Router for BTC price endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.responses import BtcPriceResponse
from shared.db.database import get_db
from shared.db.models import BtcPrice

router = APIRouter(prefix="/api")


@router.get("/prices", response_model=list[BtcPriceResponse])
async def get_prices(
    limit: int = Query(
        default=24,
        ge=1,
        le=1000,
        description="Number of recent prices to return (1-1000)",
    ),
    db: Session = Depends(get_db),
) -> list[BtcPriceResponse]:
    """
    Get recent BTC prices.

    Returns the most recent BTC OHLCV prices from the database,
    ordered by timestamp descending (newest first).

    Args:
        limit: Number of records to return (default: 24, max: 1000)
        db: Database session (injected)

    Returns:
        List of BTC price records

    Example:
        GET /api/prices?limit=24
    """
    prices = (
        db.query(BtcPrice)
        .order_by(BtcPrice.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [BtcPriceResponse.model_validate(price) for price in prices]
