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
from shared.db.crud import get_evaluated_predictions
from shared.db.database import get_db
from shared.db.models import Model, Prediction, PredictionSource
from shared.strategies import get_all_strategies_metrics
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
    """Evaluated predictions with their model, newest ``predicted_for`` first.

    Args:
        from_date: Query ``from``, inclusive lower bound on ``predicted_for``.
        to_date: Query ``to``, inclusive upper bound.
        timeframe: Query ``timeframe`` filter.
        symbol: Query ``symbol``; default BTCUSDT.
        source: Query ``source``, ``live``, ``replay`` or ``all`` (default); each row
            carries ``is_replay`` either way.
        db: Database session (injected).

    Returns:
        The evaluated predictions; an empty list if there are none.
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
    """Total simulated PnL and count of evaluated predictions of one timeframe.

    Defaults to ``DEFAULT_TIMEFRAME`` so timeframes are never summed into one figure.

    Args:
        timeframe: Query ``timeframe``.
        symbol: Query ``symbol``; default BTCUSDT.
        db: Database session (injected).

    Returns:
        ``total_pnl`` and ``evaluated_predictions``, both 0 if nothing is evaluated.
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
    """Metrics and cumulative PnL series of the four strategies for one timeframe.

    The strategies are Simple, Long/Short, Threshold and Realistic. Defaults to
    ``DEFAULT_TIMEFRAME`` so timeframes are never combined.

    Args:
        timeframe: Query ``timeframe``.
        symbol: Query ``symbol``; default BTCUSDT.
        db: Database session (injected).

    Returns:
        The strategies, with zero metrics if nothing is evaluated.
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
