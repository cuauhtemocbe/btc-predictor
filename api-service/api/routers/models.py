"""Model comparison (US-026): ``GET /models`` and ``GET /api/models/metrics``.

A model here is a family, compared by accuracy, MAPE, total PnL, win rate, Sharpe
ratio and max drawdown of the compounded equity curve.
"""

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.symbols import (
    DEFAULT_SYMBOL,
    SourceQuery,
    SymbolQuery,
    asset_context,
    source_context,
)
from shared.db.database import get_db
from shared.db.models import PredictionSource
from shared.utils import (
    DEFAULT_TIMEFRAME,
    get_all_models_metrics,
    get_family_cumulative_pnl,
)

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
        description="Timeframe filter: '1d' (the only supported value)",
        pattern="^1d$",
    ),
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    source: SourceQuery = PredictionSource.ALL,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render the comparison table and the cumulative PnL chart.

    Args:
        request: FastAPI request.
        start_date: Optional lower bound on ``predicted_for``.
        end_date: Optional upper bound.
        timeframe: Defaults to ``DEFAULT_TIMEFRAME`` so timeframes are never combined.
        symbol: Asset shown, default BTCUSDT; only its models are compared.
        source: ``live``, ``replay`` or ``all`` (default); simulated models are marked
            either way.
        db: Database session.
    """
    # Get metrics for all model families
    models_metrics = get_all_models_metrics(
        db, start_date, end_date, timeframe=timeframe, symbol=symbol, source=source
    )

    # Identify best performing model (highest Total PnL)
    best_model_id = None
    if models_metrics:
        models_with_pnl = [m for m in models_metrics if m["total_pnl"] is not None]
        if models_with_pnl:
            best_model = max(models_with_pnl, key=lambda m: m["total_pnl"])
            best_model_id = best_model["id"]

    # Get cumulative PnL for all model families (for chart)
    daily_pnl = get_family_cumulative_pnl(
        db, start_date, end_date, timeframe=timeframe, symbol=symbol, source=source
    )

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
            **source_context(request, source),
            **asset_context(request, symbol),
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
        description="Timeframe filter: '1d' (the only supported value)",
        pattern="^1d$",
    ),
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    source: SourceQuery = PredictionSource.ALL,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Model metrics as JSON, one row per family (#178).

    A model is a family (``linear`` for ``linear_v1``, ``linear_v2``, ...): one row per
    (symbol, family, timeframe) over the predictions of every version.

    Args:
        start_date: Optional lower bound on ``predicted_for``.
        end_date: Optional upper bound.
        pnl_column: PnL column to use.
        timeframe: Defaults to ``DEFAULT_TIMEFRAME`` so timeframes are never combined.
        symbol: Asset shown, default BTCUSDT.
        source: ``live``, ``replay`` or ``all`` (default); only versions of that source
            count; ``is_replay`` is true when every version of the family is simulated.
        db: Database session.

    Returns:
        ``models``, the rows of ``get_all_models_metrics``, and ``daily_pnl``, the
        cumulative PnL series per family name.
    """
    # Get metrics for all model families
    models_metrics = get_all_models_metrics(
        db,
        start_date,
        end_date,
        pnl_column,
        timeframe,
        symbol=symbol,
        source=source,
    )

    # Get daily cumulative PnL for all model families
    daily_pnl = get_family_cumulative_pnl(
        db, start_date, end_date, pnl_column, timeframe, symbol=symbol, source=source
    )

    # Convert datetime to ISO format for JSON serialization
    for model in models_metrics:
        if model["trained_at"]:
            model["trained_at"] = model["trained_at"].isoformat()
        model["first_train_to"] = model["first_train_to"].isoformat()
        model["last_train_to"] = model["last_train_to"].isoformat()

    return {
        "models": models_metrics,
        "daily_pnl": daily_pnl,
        "filters": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "pnl_column": pnl_column,
            "timeframe": timeframe,
            "symbol": symbol,
            "source": source.value,
        },
    }
