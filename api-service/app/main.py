from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import connect, disconnect
from app.routers import admin, ai, auth, comments, forums, incidents, queue, tickets
from app.services.bootstrap import ensure_admin

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    await ensure_admin()
    yield
    await disconnect()


app = FastAPI(title="SmartDesk API", version="0.3.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(comments.router)
app.include_router(ai.router)
app.include_router(queue.router)
app.include_router(incidents.router)
app.include_router(forums.router)
app.include_router(admin.router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


# --- Web UI (static single-page app) ---
# Served from the gateway itself, so the whole product is reachable on :8080.
# API routers above are registered first and take precedence over these routes.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")
