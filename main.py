"""Application entry point.

Creates the FastAPI app, registers middleware, mounts routers,
and initialises the database on startup via the lifespan handler.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.engine.url import make_url
from app.config import settings
from app.database import init_db
from app.routers.analysis import router as analysis_router
from app.routers.knowledge import router as knowledge_router
from app.routers.webhooks import router as webhooks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

_DASHBOARD_FILE = Path(__file__).parent / "static" / "dashboard.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler — runs startup logic before the app begins serving."""
    init_db()
    yield


app = FastAPI(
    title="PR Agent API",
    description="Webhook-driven PR metadata, diff, rules, and risk scoring service.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(analysis_router)
app.include_router(knowledge_router)


@app.get("/dashboard", tags=["dashboard"], include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the live pipeline status dashboard (HTML page)."""
    return FileResponse(_DASHBOARD_FILE)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Health check endpoint. Returns server status and configuration summary."""
    db_url = make_url(settings.database_url)
    return {
        "status": "ok",
        "host": settings.host,
        "port": settings.port,
        "database": {
            "driver": db_url.drivername,
            "host": db_url.host,
            "port": db_url.port,
            "name": db_url.database,
        },
        "retention_days": {
            "webhook_payload": settings.webhook_payload_retention_days,
            "analysis_logs": settings.analysis_log_retention_days,
            "ai_cache": settings.ai_cache_retention_days,
        },
    }
