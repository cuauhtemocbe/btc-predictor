"""Router for prediction history endpoints."""

from datetime import date
from typing import Annotated

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
from api.numeric import required_float
from api.symbols import DEFAULT_SYMBOL, SourceQuery, SymbolQuery
from btc_shared.strategies import get_all_strategies_metrics
from shared.db.crud import get_evaluated_predictions
from shared.db.database import get_db
from shared.db.models import Model, Prediction, PredictionSource
from shared.utils import DEFAULT_TIMEFRAME

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

# One definition of the timeframe filter (description and pattern) for every endpoint.
_TIMEFRAME_QUERY = Query(
    description="Timeframe filter: '1d' (the only supported value)",
    pattern="^1d$",
)
TimeframeQuery = Annotated[str, _TIMEFRAME_QUERY]
OptionalTimeframeQuery = Annotated[str | None, _TIMEFRAME_QUERY]


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
    timeframe: OptionalTimeframeQuery = None,
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    source: SourceQuery = PredictionSource.ALL,
    db: Session = Depends(get_db),
) -> list[PredictionHistoryResponse]:
    """
    Get historical predictions with evaluation metrics.

    Returns only evaluated predictions (actual_price IS NOT NULL),
    joined with model information, ordered by prediction date descending.

    Args:
        from_date: Optional start date filter (query param: ?from=2026-05-01)
        to_date: Optional end date filter (query param: ?to=2026-05-15)
        timeframe: Optional timeframe filter (query param: ?timeframe=1d)
        symbol: Asset to show (query param: ?symbol=PAXGUSDT, default BTCUSDT)
        source: Predictions to include (query param: ?source=live|replay|all,
            default all). Each row carries ``is_replay`` either way.
        db: Database session (injected)

    Returns:
        List of evaluated predictions with model info. Empty array if no data.

    Examples:
        - GET /api/predictions/history
        - GET /api/predictions/history?from=2026-05-01
        - GET /api/predictions/history?from=2026-05-01&to=2026-05-15
        - GET /api/predictions/history?timeframe=1d&from=2026-05-01
        - GET /api/predictions/history?source=live
    """
    predictions = get_evaluated_predictions(
        session=db,
        from_date=from_date,
        to_date=to_date,
        timeframe=timeframe,
        symbol=symbol,
        source=source,
    )

    # Convert to response models with model info
    return [
        PredictionHistoryResponse(
            predicted_for=p.predicted_for,
            predicted_at=p.predicted_at,
            price_at_prediction=float(p.price_at_prediction),
            predicted_price=float(p.predicted_price),
            actual_price=required_float(p.actual_price, "actual_price"),
            evaluated_at=p.evaluated_at,
            error_abs=required_float(p.error_abs, "error_abs"),
            error_pct=required_float(p.error_pct, "error_pct"),
            direction_correct=p.direction_correct,
            pnl_simulated=required_float(p.pnl_simulated, "pnl_simulated"),
            model_name=p.model.name,
            model_version=p.model.version,
            timeframe=p.timeframe,
            is_replay=p.model.is_replay,
        )
        for p in predictions
    ]


@router.get("/pnl", response_model=PnlResponse)
async def get_total_pnl(
    timeframe: TimeframeQuery = DEFAULT_TIMEFRAME,
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    db: Session = Depends(get_db),
) -> PnlResponse:
    """
    Get total accumulated profit/loss across all evaluated predictions for
    one timeframe.

    This endpoint aggregates the simulated PnL from all predictions that have
    been evaluated (actual_price IS NOT NULL). Useful for assessing overall
    model profitability. Defaults to DEFAULT_TIMEFRAME so PnL of different
    timeframes is never silently summed into one misleading figure.

    Args:
        timeframe: Timeframe to aggregate (query param: ?timeframe=1d)
        symbol: Asset to aggregate (query param: ?symbol=PAXGUSDT, default BTCUSDT)
        db: Database session (injected)

    Returns:
        Aggregated PnL summary with total_pnl and evaluated_predictions count.
        If no predictions have been evaluated yet, returns total_pnl=0 and
        evaluated_predictions=0.

    Examples:
        - GET /api/predictions/pnl
          Response: {"total_pnl": 12345.67, "evaluated_predictions": 30}
    """
    # Query for SUM(pnl_simulated) and COUNT(*) where pnl_simulated IS NOT NULL
    result = (
        db.query(
            func.sum(Prediction.pnl_simulated),
            func.count(Prediction.id),
        )
        .join(Model, Prediction.model_id == Model.id)
        .filter(
            Prediction.pnl_simulated.isnot(None),
            Prediction.timeframe == timeframe,
            Model.symbol == symbol,
        )
        .one()
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
    timeframe: TimeframeQuery = DEFAULT_TIMEFRAME,
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    db: Session = Depends(get_db),
) -> StrategiesResponse:
    """
    Get performance metrics for all trading strategies, for one timeframe.

    Returns aggregate metrics (Total PnL, Win Rate, Sharpe Ratio, etc.) and
    cumulative PnL time series for all 4 strategies: Simple, Long/Short,
    Threshold, and Realistic. Defaults to DEFAULT_TIMEFRAME so results of
    different timeframes are never silently combined.

    Args:
        timeframe: Timeframe to aggregate (query param: ?timeframe=1d)
        symbol: Asset to aggregate (query param: ?symbol=PAXGUSDT, default BTCUSDT)
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
                      "worst_trade_pct": -0.65,
                      "max_drawdown_pct": -4.50,
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
    strategies_data = get_all_strategies_metrics(db, timeframe=timeframe, symbol=symbol)

    # Convert to Pydantic models
    strategies = [
        StrategyMetrics(
            name=s["name"],
            display_name=s["display_name"],
            color=s["color"],
            total_pnl=s["total_pnl"],
            win_rate=s["win_rate"],
            worst_trade_pct=s["worst_trade_pct"],
            max_drawdown_pct=s["max_drawdown_pct"],
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
