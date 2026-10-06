from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.numeric import required_float
from api.routers import router
from api.routers.backtesting import router as backtesting_router
from api.routers.models import router as models_router
from api.routers.predictions import router as predictions_router
from api.routers.prices import router as prices_router
from api.summaries import source_summaries
from api.symbols import (
    DEFAULT_SYMBOL,
    SourceQuery,
    SymbolQuery,
    asset_context,
    source_context,
)
from btc_shared.strategies import get_all_strategies_metrics
from shared.db.crud import get_evaluated_predictions
from shared.db.database import get_db
from shared.db.models import PredictionSource
from shared.utils import DEFAULT_TIMEFRAME

app = FastAPI(title="BTC Predictor", version="0.1.0")
app.include_router(router)
app.include_router(prices_router)
app.include_router(predictions_router)
app.include_router(backtesting_router)
app.include_router(models_router)

# Configure Jinja2 templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    timeframe: str | None = None,
    symbol: SymbolQuery = DEFAULT_SYMBOL,
    source: SourceQuery = PredictionSource.ALL,
) -> HTMLResponse:
    """
    Render the main dashboard showing prediction history.

    Fetches all evaluated predictions from the database and displays them
    in a formatted HTML table with model performance metrics.

    Args:
        request: FastAPI request object
        db: Database session
        timeframe: Optional filter for timeframe ('1d'). Defaults to '1d' if None.
        symbol: Asset to show (default BTCUSDT); every table and chart is scoped to it.
        source: ``live``, ``replay`` or ``all`` (default). Live and replay get
            separate headline blocks; the combined one appears only under ``all``.
    """
    # Default timeframe if none specified -- shared across every metrics
    # endpoint so results of different timeframes are never silently combined.
    if timeframe is None:
        timeframe = DEFAULT_TIMEFRAME

    # Fetch evaluated predictions filtered by timeframe
    predictions_data = get_evaluated_predictions(
        session=db, timeframe=timeframe, symbol=symbol, source=source
    )

    # Convert to template-friendly format
    predictions = [
        {
            "predicted_for": p.predicted_for,
            "predicted_at": p.predicted_at,
            "price_at_prediction": float(p.price_at_prediction),
            "predicted_price": float(p.predicted_price),
            "actual_price": required_float(p.actual_price, "actual_price"),
            "evaluated_at": p.evaluated_at,
            "error_abs": required_float(p.error_abs, "error_abs"),
            "error_pct": required_float(p.error_pct, "error_pct"),
            "direction_correct": p.direction_correct,
            "pnl_simulated": required_float(p.pnl_simulated, "pnl_simulated"),
            "model_name": p.model.name,
            "model_version": p.model.version,
            "is_replay": p.model.is_replay,
        }
        for p in predictions_data
    ]

    # Fetch strategy metrics for the same timeframe as the predictions above
    strategies = get_all_strategies_metrics(
        db, timeframe=timeframe, symbol=symbol, source=source
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "predictions": predictions,
            "strategies": strategies,
            "summaries": source_summaries(
                db, symbol, timeframe, source, predictions_data
            ),
            **source_context(request, source),
            **asset_context(request, symbol),
        },
    )


@app.get("/health", response_model=None)
async def health(
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse | dict[str, str]:
    """
    Report API and database health.

    Returns 200 when the database is reachable, 503 otherwise. Railway's
    container HEALTHCHECK (see Dockerfile) probes this endpoint, so a
    non-2xx response here can trigger a container restart.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "unreachable"},
        )
    return {"status": "ok", "database": "reachable"}
