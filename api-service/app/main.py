from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import connect, disconnect
from app.routers import admin, ai, auth, comments, tickets


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    yield
    await disconnect()


app = FastAPI(title="SmartDesk API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(comments.router)
app.include_router(ai.router)
app.include_router(admin.router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
