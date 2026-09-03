import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import connect, disconnect
from app.middleware import BodySizeLimitMiddleware
from app.routers import admin, ai, assistant, auth, comments, forums, incidents, queue, tickets
from app.services.bootstrap import ensure_admin

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_DEFAULT_SECRET = "change-me-in-prod"


def check_secret() -> None:
    """The example JWT secret is public: anyone who read the repo could mint
    an ADMIN token. Shout about it, and refuse to start where it matters."""
    if settings.jwt_secret != _DEFAULT_SECRET:
        return
    if settings.require_strong_secret:
        raise RuntimeError(
            "JWT_SECRET is the public default; set a long random value before "
            "starting with REQUIRE_STRONG_SECRET=true."
        )
    logger.warning(
        "JWT_SECRET is the public default from .env.example - fine for a laptop, "
        "never for a deployment: anyone can forge admin tokens. Set JWT_SECRET."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_secret()
    await connect()
    await ensure_admin()
    yield
    await disconnect()


app = FastAPI(title="SmartDesk API", version="0.3.0", lifespan=lifespan)
app.add_middleware(BodySizeLimitMiddleware)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(comments.router)
app.include_router(ai.router)
app.include_router(ai.status_router)
app.include_router(assistant.router)
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
