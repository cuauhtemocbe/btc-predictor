from fastapi import FastAPI

from api.routers import router
from api.routers.prices import router as prices_router

app = FastAPI(title="BTC Predictor", version="0.1.0")
app.include_router(router)
app.include_router(prices_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
