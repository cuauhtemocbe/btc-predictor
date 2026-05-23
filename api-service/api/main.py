from pathlib import Path

from btc_shared.strategies import get_all_strategies_metrics
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from shared.db.crud import get_evaluated_predictions
from shared.db.database import get_db
from sqlalchemy.orm import Session

from api.routers import router
from api.routers.backtesting import router as backtesting_router
from api.routers.models import router as models_router
from api.routers.predictions import router as predictions_router
from api.routers.prices import router as prices_router

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
):
    """
    Render the main dashboard showing prediction history.

    Fetches all evaluated predictions from the database and displays them
    in a formatted HTML table with model performance metrics.

    Args:
        request: FastAPI request object
        db: Database session
        timeframe: Optional filter for timeframe ('1d', '1w'). Defaults to '1d' if None.
    """
    # Default to daily predictions if no timeframe specified
    if timeframe is None:
        timeframe = "1d"

    # Fetch evaluated predictions filtered by timeframe
    predictions_data = get_evaluated_predictions(session=db, timeframe=timeframe)

    # Convert to template-friendly format
    predictions = [
        {
            "predicted_for": p.predicted_for,
            "predicted_at": p.predicted_at,
            "price_at_prediction": float(p.price_at_prediction),
            "predicted_price": float(p.predicted_price),
            "actual_price": float(p.actual_price),
            "evaluated_at": p.evaluated_at,
            "error_abs": float(p.error_abs),
            "error_pct": float(p.error_pct),
            "direction_correct": p.direction_correct,
            "pnl_simulated": float(p.pnl_simulated),
            "model_name": p.model.name,
            "model_version": p.model.version,
        }
        for p in predictions_data
    ]

    # Fetch strategy metrics
    strategies = get_all_strategies_metrics(db)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "predictions": predictions,
            "strategies": strategies,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
