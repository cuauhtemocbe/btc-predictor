"""
API router for model comparison dashboard (US-026).

Provides endpoints for:
- GET /models - HTML dashboard with model comparison table and chart
- GET /api/models/metrics - JSON API for model metrics

Models are compared by:
- Accuracy (% direction correct)
- MAPE (Mean Absolute Percentage Error)
- Total PnL
- Win Rate
- Sharpe Ratio
- Max Drawdown
"""

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from shared.db.database import get_db
from shared.utils import DEFAULT_TIMEFRAME, get_all_models_metrics, get_cumulative_pnl

router = APIRouter(prefix="/models", tags=["models"])

# Configure Jinja2 templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def models_dashboard(
    request: Request,
    start_date: date | None = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date filter (YYYY-MM-DD)"),
    timeframe: str = Query(
        default=DEFAULT_TIMEFRAME,
        description="Timeframe filter: '1h', '1d', or '1w'",
        pattern="^(1h|1d|1w)$",
    ),
    db: Session = Depends(get_db),
):
    """
    Render model comparison dashboard with metrics table and cumulative PnL chart.

    Args:
        request: FastAPI request object
        start_date: Optional start date for filtering metrics
        end_date: Optional end date for filtering metrics
        timeframe: Timeframe to aggregate (default: DEFAULT_TIMEFRAME), so
            daily and weekly metrics are never silently combined
        db: Database session

    Returns:
        HTML template with model comparison table and chart
    """
    # Get metrics for all models
    models_metrics = get_all_models_metrics(
        db, start_date, end_date, timeframe=timeframe
    )

    # Identify best performing model (highest Total PnL)
    best_model_id = None
    if models_metrics:
        models_with_pnl = [m for m in models_metrics if m["total_pnl"] is not None]
        if models_with_pnl:
            best_model = max(models_with_pnl, key=lambda m: m["total_pnl"])
            best_model_id = best_model["id"]

    # Get cumulative PnL for all models (for chart)
    daily_pnl = {}
    for model_metrics in models_metrics:
        model_id = model_metrics["id"]
        model_name = model_metrics["name"]
        cumulative = get_cumulative_pnl(
            db, model_id, start_date, end_date, timeframe=timeframe
        )
        daily_pnl[model_name] = cumulative

    return templates.TemplateResponse(
        request=request,
        name="models.html",
        context={
            "models": models_metrics,
            "best_model_id": best_model_id,
            "daily_pnl": daily_pnl,
            "start_date": start_date.isoformat() if start_date else "",
            "end_date": end_date.isoformat() if end_date else "",
            "timeframe": timeframe,
        },
    )


@router.get("/metrics", response_class=JSONResponse)
async def models_metrics_api(
    start_date: date | None = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date filter (YYYY-MM-DD)"),
    pnl_column: str = Query(
        "pnl_simulated",
        description="PnL column to use",
        pattern="^(pnl_simulated|pnl_long_short|pnl_threshold|pnl_realistic)$",
    ),
    timeframe: str = Query(
        default=DEFAULT_TIMEFRAME,
        description="Timeframe filter: '1h', '1d', or '1w'",
        pattern="^(1h|1d|1w)$",
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get model performance metrics as JSON.

    This endpoint returns metrics for all models, useful for AJAX requests
    or mobile clients.

    Args:
        start_date: Optional start date for filtering metrics
        end_date: Optional end date for filtering metrics
        pnl_column: Which PnL column to use (default: pnl_simulated)
        timeframe: Timeframe to aggregate (default: DEFAULT_TIMEFRAME), so
            daily and weekly metrics are never silently combined
        db: Database session

    Returns:
        JSON with structure:
        {
            "models": [
                {
                    "id": 1,
                    "name": "linear_v1",
                    "version": "1.0.0",
                    "is_active": true,
                    "trained_at": "2024-05-18T10:00:00",
                    "predictions_count": 30,
                    "accuracy": 0.65,
                    "avg_error_pct": 2.5,
                    "total_pnl": 1200.50,
                    "win_rate": 0.60,
                    "sharpe_ratio": 1.25,
                    "max_drawdown": -450.00,
                    "max_drawdown_pct": -4.50
                },
                ...
            ],
            "daily_pnl": {
                "linear_v1": [
                    {"date": "2024-05-01", "cumulative_pnl": 100.0},
                    ...
                ],
                ...
            }
        }
    """
    # Get metrics for all models
    models_metrics = get_all_models_metrics(
        db, start_date, end_date, pnl_column, timeframe
    )

    # Get daily cumulative PnL for all models
    daily_pnl = {}
    for model_metrics in models_metrics:
        model_id = model_metrics["id"]
        model_name = model_metrics["name"]
        cumulative = get_cumulative_pnl(
            db, model_id, start_date, end_date, pnl_column, timeframe
        )
        daily_pnl[model_name] = cumulative

    # Convert datetime to ISO format for JSON serialization
    for model in models_metrics:
        if model["trained_at"]:
            model["trained_at"] = model["trained_at"].isoformat()

    return {
        "models": models_metrics,
        "daily_pnl": daily_pnl,
        "filters": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "pnl_column": pnl_column,
            "timeframe": timeframe,
        },
    }
