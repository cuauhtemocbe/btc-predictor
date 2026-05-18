"""Router for prediction history endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.predictions import PredictionHistoryResponse
from shared.db.crud import get_evaluated_predictions
from shared.db.database import get_db

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("/history", response_model=list[PredictionHistoryResponse])
async def get_prediction_history(
    from_date: date | None = Query(
        default=None,
        description="Start date filter (inclusive)",
        alias="from",
    ),
    to_date: date | None = Query(
        default=None,
        description="End date filter (inclusive)",
        alias="to",
    ),
    db: Session = Depends(get_db),
) -> list[PredictionHistoryResponse]:
    """
    Get historical predictions with evaluation metrics.

    Returns only evaluated predictions (actual_price IS NOT NULL),
    joined with model information, ordered by prediction date descending.

    Args:
        from_date: Optional start date filter (query param: ?from=2026-05-01)
        to_date: Optional end date filter (query param: ?to=2026-05-15)
        db: Database session (injected)

    Returns:
        List of evaluated predictions with model info. Empty array if no data.

    Examples:
        - GET /api/predictions/history
        - GET /api/predictions/history?from=2026-05-01
        - GET /api/predictions/history?from=2026-05-01&to=2026-05-15
    """
    predictions = get_evaluated_predictions(
        session=db,
        from_date=from_date,
        to_date=to_date,
    )

    # Convert to response models with model info
    return [
        PredictionHistoryResponse(
            predicted_for=p.predicted_for,
            predicted_at=p.predicted_at,
            price_at_prediction=float(p.price_at_prediction),
            predicted_price=float(p.predicted_price),
            actual_price=float(p.actual_price),
            evaluated_at=p.evaluated_at,
            error_abs=float(p.error_abs),
            error_pct=float(p.error_pct),
            direction_correct=p.direction_correct,
            pnl_simulated=float(p.pnl_simulated),
            model_name=p.model.name,
            model_version=p.model.version,
        )
        for p in predictions
    ]
