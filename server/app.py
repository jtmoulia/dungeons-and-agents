"""FastAPI application entry point for Dungeons and Agents play-by-post server."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server.config import settings
from server.db import close_db, get_db, init_db
from server.moderation import configure_moderation

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Dungeons and Agents server")
    await init_db(settings.db_path)
    configure_moderation(
        enabled=settings.moderation_enabled,
        blocked_words=settings.moderation_blocked_words or None,
    )
    if settings.moderation_enabled and not settings.moderation_blocked_words:
        logger.warning(
            "Content moderation is enabled but no blocked words are configured. "
            "Set moderation_blocked_words in config for content filtering."
        )
    logger.info("Server ready")
    yield
    logger.info("Shutting down server")
    await close_db()
    logger.info("Server stopped")


app = FastAPI(
    title="Dungeons and Agents",
    description="Play-by-post RPG service for AI agents and humans",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        loc = " → ".join(str(l) for l in error["loc"])
        errors.append({"field": loc, "message": error["msg"]})
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Token"],
)

# Include routes
from server.routes.admin import router as admin_router
from server.routes.games import router as games_router
from server.routes.lobby import router as lobby_router
from server.routes.messages import router as messages_router

app.include_router(lobby_router, tags=["lobby"])
app.include_router(games_router, tags=["games"])
app.include_router(messages_router, tags=["messages"])
app.include_router(admin_router, tags=["admin"])

from server.guides import DM_GUIDE, DM_INSTRUCTIONS, PLAYER_GUIDE, PLAYER_INSTRUCTIONS


@app.get("/health", tags=["ops"])
async def health_check():
    """Health check endpoint for load balancer probes."""
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})


@app.get("/guide", tags=["guide"])
async def get_guide():
    """Return player and DM guides as JSON for programmatic access."""
    return {
        "player": {
            "guide": PLAYER_GUIDE,
            "instructions": PLAYER_INSTRUCTIONS,
        },
        "dm": {
            "guide": DM_GUIDE,
            "instructions": DM_INSTRUCTIONS,
        },
    }


class HTMLStaticFiles(StaticFiles):
    """StaticFiles that resolves extensionless paths to .html files."""

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        full_path, stat_result = super().lookup_path(path)
        if stat_result is None and not path.endswith(".html"):
            full_path, stat_result = super().lookup_path(path + ".html")
        return full_path, stat_result


# Serve web UI static files
web_dir = Path(settings.web_dir)
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
    app.mount("/web", HTMLStaticFiles(directory=str(web_dir), html=True), name="web")
