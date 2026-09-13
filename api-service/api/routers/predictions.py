"""Router for prediction history endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.predictions import (
    CumulativePnlPoint,
    PnlResponse,
    PredictionHistoryResponse,
    StrategiesResponse,
    StrategyMetrics,
)
from btc_shared.strategies import get_all_strategies_metrics
from shared.db.crud import get_evaluated_predictions
from shared.db.database import get_db
from shared.db.models import Prediction
from shared.utils import DEFAULT_TIMEFRAME

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
    timeframe: str | None = Query(
        default=None,
        description="Timeframe filter: '1h', '1d', or '1w'",
        pattern="^(1h|1d|1w)$",
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
        timeframe: Optional timeframe filter (query param: ?timeframe=1w)
        db: Database session (injected)

    Returns:
        List of evaluated predictions with model info. Empty array if no data.

    Examples:
        - GET /api/predictions/history
        - GET /api/predictions/history?from=2026-05-01
        - GET /api/predictions/history?from=2026-05-01&to=2026-05-15
        - GET /api/predictions/history?timeframe=1w
        - GET /api/predictions/history?timeframe=1d&from=2026-05-01
    """
    predictions = get_evaluated_predictions(
        session=db,
        from_date=from_date,
        to_date=to_date,
        timeframe=timeframe,
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
            timeframe=p.timeframe,
        )
        for p in predictions
    ]


@router.get("/pnl", response_model=PnlResponse)
async def get_total_pnl(
    timeframe: str = Query(
        default=DEFAULT_TIMEFRAME,
        description="Timeframe filter: '1h', '1d', or '1w'",
        pattern="^(1h|1d|1w)$",
    ),
    db: Session = Depends(get_db),
) -> PnlResponse:
    """
    Get total accumulated profit/loss across all evaluated predictions for
    one timeframe.

    This endpoint aggregates the simulated PnL from all predictions that have
    been evaluated (actual_price IS NOT NULL). Useful for assessing overall
    model profitability. Defaults to DEFAULT_TIMEFRAME so daily and weekly
    PnL are never silently summed into one misleading figure.

    Args:
        timeframe: Timeframe to aggregate (query param: ?timeframe=1w)
        db: Database session (injected)

    Returns:
        Aggregated PnL summary with total_pnl and evaluated_predictions count.
        If no predictions have been evaluated yet, returns total_pnl=0 and
        evaluated_predictions=0.

    Examples:
        - GET /api/predictions/pnl
          Response: {"total_pnl": 12345.67, "evaluated_predictions": 30}
        - GET /api/predictions/pnl?timeframe=1w
    """
    # Query for SUM(pnl_simulated) and COUNT(*) where pnl_simulated IS NOT NULL
    result = (
        db.query(
            func.sum(Prediction.pnl_simulated),
            func.count(Prediction.id),
        )
        .filter(
            Prediction.pnl_simulated.isnot(None),
            Prediction.timeframe == timeframe,
        )
        .first()
    )

    # Handle case where no evaluated predictions exist (result[0] will be None)
    total_pnl = float(result[0]) if result[0] is not None else 0.0
    evaluated_predictions = result[1]

    return PnlResponse(
        total_pnl=total_pnl,
        evaluated_predictions=evaluated_predictions,
    )


@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies_comparison(
    timeframe: str = Query(
        default=DEFAULT_TIMEFRAME,
        description="Timeframe filter: '1h', '1d', or '1w'",
        pattern="^(1h|1d|1w)$",
    ),
    db: Session = Depends(get_db),
) -> StrategiesResponse:
    """
    Get performance metrics for all trading strategies, for one timeframe.

    Returns aggregate metrics (Total PnL, Win Rate, Sharpe Ratio, etc.) and
    cumulative PnL time series for all 4 strategies: Simple, Long/Short,
    Threshold, and Realistic. Defaults to DEFAULT_TIMEFRAME so daily and
    weekly results are never silently combined.

    Args:
        timeframe: Timeframe to aggregate (query param: ?timeframe=1w)
        db: Database session (injected)

    Returns:
        Collection of strategy metrics with cumulative PnL time series.
        If no predictions have been evaluated yet, returns all strategies
        with zero metrics.

    Examples:
        - GET /api/predictions/strategies
          Response: {
              "strategies": [
                  {
                      "name": "simple",
                      "display_name": "Simple",
                      "color": "blue",
                      "total_pnl": 1200.50,
                      "win_rate": 0.63,
                      "max_drawdown": -450.00,
                      "avg_win": 220.30,
                      "avg_loss": -180.50,
                      "sharpe_ratio": 1.25,
                      "trade_count": 30,
                      "cumulative_pnl": [...]
                  },
                  ...
              ]
          }
    """
    strategies_data = get_all_strategies_metrics(db, timeframe=timeframe)

    # Convert to Pydantic models
    strategies = [
        StrategyMetrics(
            name=s["name"],
            display_name=s["display_name"],
            color=s["color"],
            total_pnl=s["total_pnl"],
            win_rate=s["win_rate"],
            max_drawdown=s["max_drawdown"],
            avg_win=s["avg_win"],
            avg_loss=s["avg_loss"],
            sharpe_ratio=s["sharpe_ratio"],
            trade_count=s["trade_count"],
            cumulative_pnl=[
                CumulativePnlPoint(
                    date=point["date"], cumulative_pnl=point["cumulative_pnl"]
                )
                for point in s["cumulative_pnl"]
            ],
        )
        for s in strategies_data
    ]

    return StrategiesResponse(strategies=strategies)
