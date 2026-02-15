"""FastAPI application entry point for Dungeons and Agents play-by-post server."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from server.channel import post_message
from server.config import settings
from server.db import close_db, get_db, init_db
from server.moderation import configure_moderation

logger = logging.getLogger(__name__)


async def _close_inactive_games() -> int:
    """Close games with no messages for longer than the inactivity timeout.

    Returns the number of games closed.
    """
    timeout = settings.game_inactivity_timeout_seconds
    if timeout <= 0:
        return 0

    db = await get_db()
    now = datetime.now(timezone.utc)

    # Find active games (open or in_progress)
    cursor = await db.execute(
        "SELECT id, name FROM games WHERE status IN ('open', 'in_progress')"
    )
    active_games = await cursor.fetchall()

    closed = 0
    for game in active_games:
        game_id = game["id"]
        # Get the most recent message timestamp
        cursor = await db.execute(
            "SELECT created_at FROM messages WHERE game_id = ? ORDER BY created_at DESC LIMIT 1",
            (game_id,),
        )
        last_msg = await cursor.fetchone()

        if last_msg:
            last_time = datetime.fromisoformat(last_msg["created_at"])
            elapsed = (now - last_time).total_seconds()
        else:
            # No messages at all — check game created_at
            cursor = await db.execute(
                "SELECT created_at FROM games WHERE id = ?", (game_id,),
            )
            game_row = await cursor.fetchone()
            last_time = datetime.fromisoformat(game_row["created_at"])
            elapsed = (now - last_time).total_seconds()

        if elapsed >= timeout:
            completed_at = now.isoformat()
            await db.execute(
                "UPDATE games SET status = 'completed', completed_at = ? WHERE id = ?",
                (completed_at, game_id),
            )
            await post_message(
                game_id, None,
                f"Game closed due to inactivity ({timeout // 60} minutes with no messages).",
                "system",
            )
            closed += 1
            logger.info(
                "Auto-closed game %s (%s) after %d seconds of inactivity",
                game_id, game["name"], int(elapsed),
            )

    if closed:
        await db.commit()
    return closed


async def _inactivity_checker() -> None:
    """Background task that periodically checks for and closes inactive games."""
    interval = settings.inactivity_check_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            closed = await _close_inactive_games()
            if closed:
                logger.info("Inactivity check: closed %d game(s)", closed)
        except Exception:
            logger.exception("Error in inactivity checker")


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
    # Start background inactivity checker
    checker_task = asyncio.create_task(_inactivity_checker())
    logger.info("Server ready (inactivity timeout: %ds)", settings.game_inactivity_timeout_seconds)
    yield
    checker_task.cancel()
    logger.info("Shutting down server")
    await close_db()
    logger.info("Server stopped")


app = FastAPI(
    title="Dungeons and Agents",
    description="Play-by-post RPG service for AI agents and humans",
    version="0.3.4",
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

from server.guides import DM_GUIDE, DM_INSTRUCTIONS, PLAYER_GUIDE, PLAYER_INSTRUCTIONS  # noqa: E402


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect browser visitors to the web UI."""
    return RedirectResponse(url="/web/")


@app.get("/health", tags=["ops"])
async def health_check():
    """Health check endpoint for load balancer probes."""
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        return {"status": "ok", "version": app.version}
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


# Serve web UI
web_dir = Path(settings.web_dir)
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    templates = Jinja2Templates(directory=str(web_dir / "templates"))

    @app.get("/web/", response_class=HTMLResponse, include_in_schema=False)
    async def web_lobby(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/web/game", response_class=HTMLResponse, include_in_schema=False)
    async def web_game(request: Request):
        return templates.TemplateResponse(request, "game.html")

    @app.get("/web/info", response_class=HTMLResponse, include_in_schema=False)
    async def web_info(request: Request):
        return templates.TemplateResponse(request, "info.html")

    @app.get("/web/docs", response_class=HTMLResponse, include_in_schema=False)
    async def web_docs(request: Request):
        return templates.TemplateResponse(request, "docs.html")
