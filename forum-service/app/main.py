from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import connect, disconnect, get_db
from app.routers import forum
from app.seed import seed_boards


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    await seed_boards(get_db())
    yield
    await disconnect()


app = FastAPI(title="SmartDesk Forum Service", version="0.1.0", lifespan=lifespan)

app.include_router(forum.router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
