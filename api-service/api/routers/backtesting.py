"""Router for backtesting results endpoints."""

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.models.backtesting import (
    BacktestMetadata,
    BacktestMetricsResponse,
    BacktestStrategyMetrics,
    DailyPnlPoint,
)
from shared.db.database import get_db
from shared.db.models import BacktestResult

router = APIRouter(tags=["backtesting"])

# Templates for HTML rendering
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def calculate_backtest_strategy_metrics(
    results: list[BacktestResult], strategy_key: str
) -> dict[str, Any]:
    """
    Calculate aggregate performance metrics for a backtest strategy.

    Args:
        results: List of BacktestResult objects
        strategy_key: One of 'pnl_simple', 'pnl_long_short',
            'pnl_threshold', 'pnl_realistic'

    Returns:
        Dictionary with metrics:
        - total_pnl: Sum of all PnL values
        - win_rate: Percentage of winning trades (0-1)
        - max_drawdown: Worst single loss
        - best_day: Best single-day PnL
        - worst_day: Worst single-day PnL
        - sharpe_ratio: Risk-adjusted return metric
        - trade_count: Number of trades
    """
    # Extract PnL values for this strategy (convert Decimal to float)
    pnl_values = [
        float(getattr(result, strategy_key))
        for result in results
        if getattr(result, strategy_key) is not None
    ]

    # Handle zero trades case
    if not pnl_values:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "best_day": 0.0,
            "worst_day": 0.0,
            "sharpe_ratio": 0.0,
            "trade_count": 0,
        }

    # Calculate basic metrics
    total_pnl = sum(pnl_values)
    wins = [p for p in pnl_values if p > 0]
    trade_count = len(pnl_values)

    win_rate = len(wins) / trade_count if trade_count > 0 else 0.0
    max_drawdown = min(pnl_values)
    best_day = max(pnl_values)
    worst_day = min(pnl_values)

    # Calculate Sharpe Ratio (simplified: mean / std_dev)
    if trade_count >= 2 and np.std(pnl_values) > 0:
        sharpe_ratio = float(np.mean(pnl_values) / np.std(pnl_values))
    else:
        sharpe_ratio = 0.0

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(max_drawdown, 2),
        "best_day": round(best_day, 2),
        "worst_day": round(worst_day, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "trade_count": trade_count,
    }


def calculate_cumulative_pnl_backtest(
    results: list[BacktestResult],
) -> list[DailyPnlPoint]:
    """
    Calculate daily PnL values for all strategies.

    Args:
        results: List of BacktestResult objects sorted by predicted_for

    Returns:
        List of DailyPnlPoint with date and PnL for each strategy
    """
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
    db: Session = Depends(get_db),
) -> BacktestMetricsResponse:
    """
    Get backtesting metrics with strategy comparison and daily PnL.

    Queries the most recent backtest run (by backtest_run_id with latest created_at)
    and returns aggregated metrics for all 4 strategies plus daily PnL time series.

    Args:
        start_date: Optional start date filter (query param: ?start=2024-05-01)
        end_date: Optional end date filter (query param: ?end=2024-05-30)
        db: Database session (injected)

    Returns:
        BacktestMetricsResponse with metadata, strategy metrics, and daily PnL.
        Returns 404 if no backtest results exist.

    Examples:
        - GET /api/backtesting/metrics
        - GET /api/backtesting/metrics?start=2024-05-01&end=2024-05-30
    """
    # Find the most recent backtest_run_id
    latest_run_query = (
        db.query(BacktestResult.backtest_run_id)
        .order_by(BacktestResult.created_at.desc())
        .limit(1)
    )
    latest_run = latest_run_query.first()

    if not latest_run:
        raise HTTPException(
            status_code=404,
            detail=(
                "No backtest results found. Run scripts/backtest.py to generate data."
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
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """
    Render backtesting results dashboard with cumulative PnL chart and metrics table.

    Args:
        request: FastAPI request object
        start_date: Optional start date filter
        end_date: Optional end date filter
        db: Database session (injected)

    Returns:
        HTML page with backtesting visualization
    """
    # Try to fetch metrics data
    try:
        metrics_data = await get_backtesting_metrics(
            start_date=start_date,
            end_date=end_date,
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
        },
    )
