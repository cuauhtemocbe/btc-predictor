"""Router for backtesting results endpoints."""

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.backtesting import (
    BacktestMetadata,
    BacktestMetricsResponse,
    BacktestStrategyMetrics,
    DailyPnlPoint,
)
from api.symbols import DEFAULT_SYMBOL, SymbolQuery, asset_context
from shared.db.database import get_db
from shared.db.models import BacktestResult
from shared.returns import max_drawdown_pct, returns_from_pnl, sharpe_ratio

router = APIRouter(tags=["backtesting"])

# Asset of a stored run. Runs saved before the backtest recorded ``symbol`` were
# all BTCUSDT.
RUN_SYMBOL = func.coalesce(BacktestResult.model_params["symbol"].astext, DEFAULT_SYMBOL)

# Templates for HTML rendering
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def calculate_backtest_strategy_metrics(
    results: list[BacktestResult], strategy_key: str
) -> dict[str, Any]:
    """Aggregate metrics of one strategy over the results of a backtest run.

    Dollar figures come from the stored PnL column; the Sharpe ratio and max drawdown
    come from returns, ``pnl / price_at_prediction``, compounded from 1.0 and
    recomputed on read (#177).

    Args:
        results: Results ordered by ``predicted_for``.
        strategy_key: ``pnl_simple``, ``pnl_long_short``, ``pnl_threshold``,
        ``pnl_realistic``.

    Returns:
        ``total_pnl``, ``win_rate`` (0-1), ``max_drawdown_pct``, ``best_day``,
        ``worst_day``, ``sharpe_ratio`` (annualized; 0.0 with fewer than 2 returns or
        no variance) and ``trade_count``.
    """
    evaluated = [r for r in results if getattr(r, strategy_key) is not None]
    pnl_values = [float(getattr(result, strategy_key)) for result in evaluated]

    # Handle zero trades case
    if not pnl_values:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "max_drawdown_pct": 0.0,
            "best_day": 0.0,
            "worst_day": 0.0,
            "sharpe_ratio": 0.0,
            "trade_count": 0,
        }

    total_pnl = sum(pnl_values)
    wins = [p for p in pnl_values if p > 0]
    trade_count = len(pnl_values)

    returns = returns_from_pnl(
        (getattr(r, strategy_key), r.price_at_prediction) for r in evaluated
    )

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(len(wins) / trade_count, 4),
        "max_drawdown_pct": round(max_drawdown_pct(returns) or 0.0, 2),
        "best_day": round(max(pnl_values), 2),
        "worst_day": round(min(pnl_values), 2),
        "sharpe_ratio": round(sharpe_ratio(returns) or 0.0, 2),
        "trade_count": trade_count,
    }


def calculate_cumulative_pnl_backtest(
    results: list[BacktestResult],
) -> list[DailyPnlPoint]:
    """Daily PnL of every strategy, one ``DailyPnlPoint`` per result."""
    daily_points = []

    for result in results:
        daily_points.append(
            DailyPnlPoint(
                date=result.predicted_for.isoformat(),
                simple=(
                    float(result.pnl_simple) if result.pnl_simple is not None else None
                ),
                long_short=(
                    float(result.pnl_long_short)
                    if result.pnl_long_short is not None
                    else None
                ),
                threshold=(
                    float(result.pnl_threshold)
                    if result.pnl_threshold is not None
                    else None
                ),
                realistic=(
                    float(result.pnl_realistic)
                    if result.pnl_realistic is not None
                    else None
                ),
            )
        )

    return daily_points


@router.get("/api/backtesting/metrics", response_model=BacktestMetricsResponse)
async def get_backtesting_metrics(
    start_date: date | None = Query(
        default=None,
        description="Filter start date (inclusive)",
        alias="start",
    ),
    end_date: date | None = Query(
        default=None,
        description="Filter end date (inclusive)",
        alias="end",
    ),
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    db: Session = Depends(get_db),
) -> BacktestMetricsResponse:
    """Metrics of the four strategies and the daily PnL of the latest backtest run.

    The latest run of ``symbol`` is the ``backtest_run_id`` created last.

    Args:
        start_date: Query ``start``, optional lower bound.
        end_date: Query ``end``, optional upper bound.
        symbol: Asset whose latest run is shown, default BTCUSDT.
        db: Database session (injected).

    Raises:
        HTTPException: 404 if no backtest results exist.
    """
    # Find the most recent backtest_run_id
    latest_run_query = (
        db.query(BacktestResult.backtest_run_id)
        .filter(RUN_SYMBOL == symbol)
        .order_by(BacktestResult.created_at.desc())
        .limit(1)
    )
    latest_run = latest_run_query.first()

    if not latest_run:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No backtest results found for {symbol}. "
                "Run scripts/backtest.py to generate data."
            ),
        )

    backtest_run_id = latest_run[0]

    # Query all results for this backtest run
    query = db.query(BacktestResult).filter(
        BacktestResult.backtest_run_id == backtest_run_id
    )

    # Apply date filters if provided
    if start_date:
        query = query.filter(BacktestResult.predicted_for >= start_date)
    if end_date:
        query = query.filter(BacktestResult.predicted_for <= end_date)

    results = query.order_by(BacktestResult.predicted_for).all()

    if not results:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No backtest results found for run {backtest_run_id} "
                "with given filters."
            ),
        )

    # Extract metadata
    first_result = results[0]
    last_result = results[-1]
    model_name = (
        first_result.model_params.get("model_name")
        if first_result.model_params
        else None
    )

    metadata = BacktestMetadata(
        backtest_run_id=str(backtest_run_id),
        start_date=first_result.predicted_for,
        end_date=last_result.predicted_for,
        total_days=len(results),
        model_name=model_name,
    )

    # Calculate metrics for all strategies
    strategies_config = [
        {"name": "simple", "key": "pnl_simple", "color": "rgb(75, 192, 192)"},
        {"name": "long_short", "key": "pnl_long_short", "color": "rgb(54, 162, 235)"},
        {"name": "threshold", "key": "pnl_threshold", "color": "rgb(255, 159, 64)"},
        {"name": "realistic", "key": "pnl_realistic", "color": "rgb(153, 102, 255)"},
    ]

    strategies = []
    for config in strategies_config:
        metrics = calculate_backtest_strategy_metrics(results, config["key"])
        strategies.append(
            BacktestStrategyMetrics(
                name=config["name"],
                display_name=config["name"].replace("_", " ").title(),
                color=config["color"],
                **metrics,
            )
        )

    # Calculate daily PnL
    daily_pnl = calculate_cumulative_pnl_backtest(results)

    return BacktestMetricsResponse(
        metadata=metadata,
        strategies=strategies,
        daily_pnl=daily_pnl,
    )


@router.get("/backtesting", response_class=HTMLResponse)
async def get_backtesting_dashboard(
    request: Request,
    start_date: date | None = Query(
        default=None,
        description="Filter start date (inclusive)",
        alias="start",
    ),
    end_date: date | None = Query(
        default=None,
        description="Filter end date (inclusive)",
        alias="end",
    ),
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render the backtest dashboard: cumulative PnL chart and metrics table.

    Args: same as ``get_backtesting_metrics``, plus the FastAPI ``request``.
    """
    # Try to fetch metrics data
    try:
        metrics_data = await get_backtesting_metrics(
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
            db=db,
        )
        has_data = True
        error_message = None
    except HTTPException as e:
        has_data = False
        error_message = e.detail
        metrics_data = None

    return templates.TemplateResponse(
        request=request,
        name="backtesting.html",
        context={
            "has_data": has_data,
            "error_message": error_message,
            "metrics": metrics_data.model_dump() if metrics_data else None,
            "start_date": start_date.isoformat() if start_date else "",
            "end_date": end_date.isoformat() if end_date else "",
            **asset_context(request, symbol),
        },
    )
