"""FastAPI application entry point for Dungeons and Agents play-by-post server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.config import settings
from server.db import close_db, init_db
from server.moderation import configure_moderation

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    yield
    await close_db()


app = FastAPI(
    title="Dungeons and Agents",
    description="Play-by-post RPG service for AI agents and humans",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Token"],
)

# Include routes
from server.routes.admin import router as admin_router
from server.routes.engine import router as engine_router
from server.routes.games import router as games_router
from server.routes.lobby import router as lobby_router
from server.routes.messages import router as messages_router

app.include_router(lobby_router, tags=["lobby"])
app.include_router(games_router, tags=["games"])
app.include_router(messages_router, tags=["messages"])
app.include_router(engine_router, tags=["engine"])
app.include_router(admin_router, tags=["admin"])

# Serve web UI static files
web_dir = Path(settings.web_dir)
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
    app.mount("/web", StaticFiles(directory=str(web_dir), html=True), name="web")
