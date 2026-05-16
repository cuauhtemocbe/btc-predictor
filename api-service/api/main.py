from fastapi import FastAPI

from api.routers import router

app = FastAPI(title="BTC Predictor", version="0.1.0")
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
