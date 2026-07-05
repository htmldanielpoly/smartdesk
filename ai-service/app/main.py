import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import ai
from app.services import model_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Download/load the local models in the background: the service answers
    # immediately (with rule-based fallbacks) and upgrades itself to the
    # local LLM once the models are ready.
    loop = asyncio.get_running_loop()
    prepare = loop.run_in_executor(None, model_manager.prepare)
    yield
    prepare.cancel()


app = FastAPI(title="SmartDesk AI Service", version="0.2.0", lifespan=lifespan)
app.include_router(ai.router)


@app.get("/health", tags=["health"])
def health():
    # Reports whether the local models are ready or the service is running
    # on rule-based fallbacks (status: unloaded/downloading/loading/ready/
    # error/disabled).
    return {"status": "ok", "local_ai": model_manager.status()}
