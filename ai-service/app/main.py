from fastapi import FastAPI

from app.config import settings
from app.routers import ai

app = FastAPI(title="SmartDesk AI Service", version="0.1.0")
app.include_router(ai.router)


@app.get("/health", tags=["health"])
def health():
    # Reports whether real AI is enabled or the service is running on fallbacks.
    return {"status": "ok", "ai_enabled": settings.ai_enabled}
