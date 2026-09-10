from fastapi import FastAPI

from app.api.v1 import router as api_v1_router

app = FastAPI(title="Scarlet")
app.include_router(api_v1_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
