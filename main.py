# ===========================================================
# SpeakSecure — Main Entry Point
# FastAPI application setup with CORS, routes, static files,
# demo frontend, background cleanup, and structured logging.
# ===========================================================

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from constants import API_TITLE, API_DESCRIPTION, API_VERSION
from API.router import api_router
from Storage.database import init_database
from Utils.logger import setup_logger
from Utils.cleanup import CleanupScheduler
from Utils.model_loader import ModelLoader
from Services.dependencies import (
    audio_service,
    oauth_service,
    api_key_rate_limiter,
)

# --- Initialize structured logging ---
logger = setup_logger()

# --- Background cleanup ---
# Sweeps stale temp files, expired OAuth codes, and old usage rows.
cleanup_scheduler = CleanupScheduler(
    audio_service=audio_service,
    oauth_service=oauth_service,
    api_key_rate_limiter=api_key_rate_limiter,
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage startup and shutdown events for the application."""
    logger.info("SpeakSecure API starting up...")

    # Initialise SQLite schema for API keys, OAuth codes, usage.
    # Idempotent — safe to call on every startup. Creates tables only
    # if they don't exist; does not touch existing data.
    init_database()
    logger.info("Database schema ready")

    # Load all ML models eagerly with retry logic.
    # If any model fails after retries, the server will not start.
    model_loader = ModelLoader(max_retries=3, retry_delay_seconds=5)
    model_loader.load_all()

    # Start background cleanup task (runs every 10 min)
    cleanup_task = asyncio.create_task(cleanup_scheduler.start())

    logger.info("SpeakSecure API ready to accept requests")
    yield

    # Graceful shutdown
    cleanup_scheduler.stop()
    cleanup_task.cancel()
    logger.info("SpeakSecure API shut down.")


app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    lifespan=lifespan,
)

# --- CORS middleware ---
# Wildcard origins allow the demo frontend and other clients to call
# the API. Per-key origin enforcement happens in the require_api_key
# dependency — CORS is the browser-side convention; our origin check
# is authoritative for the API itself.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API routes under /api/v1 prefix ---
app.include_router(api_router, prefix="/api/v1")

# --- Frontend directories ---
# The frontend is split into two single-purpose applications:
#   - Demo/             → SpeakSecure's own self-service web app
#                         (register / sign in / improve / delete)
#                         Served at GET / and uses the public API.
#   - OAuthFrontend/    → OAuth authorization page used by third-party
#                         integrators (e.g. Acme Shop). Served via
#                         GET /api/v1/authorize.
# Static assets are mounted under separate URL prefixes so they don't
# collide with each other.
BASE_DIR = Path(__file__).resolve().parent
DEMO_DIR = BASE_DIR / "Demo"
OAUTH_FRONTEND_DIR = BASE_DIR / "OAuthFrontend"

app.mount("/static", StaticFiles(directory=str(DEMO_DIR)), name="static")
app.mount(
    "/oauth-static",
    StaticFiles(directory=str(OAUTH_FRONTEND_DIR)),
    name="oauth-static",
)


# --- Demo frontend served at root URL ---
@app.get("/", response_class=HTMLResponse)
def serve_demo():
    """Serve the demo frontend at http://localhost:8000/"""
    index_path = DEMO_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse(
        "<h1>SpeakSecure API is running</h1>"
        "<p>Visit <a href='/docs'>/docs</a> for API documentation.</p>"
    )