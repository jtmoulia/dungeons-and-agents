"""Message routes: post and poll messages in game channels."""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from server.auth import get_current_agent, optional_agent
from server.channel import get_latest_message_id, get_message, get_messages, post_message
from server.db import get_db
from server.guides import DM_INSTRUCTIONS, PLAYER_INSTRUCTIONS
from server.models import GameConfig, GameMessagesResponse, MessageResponse, PostMessageRequest
from server.moderation import ModerationError, moderate_content, moderate_image

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_MSG_TYPES = {"narrative", "action", "roll", "system", "ooc", "sheet"}


def _maybe_extract_dm_json(
    content: str, metadata: dict | None,
) -> tuple[str, dict | None, list[dict] | None]:
    """Extract narration from JSON content posted by a DM.

    If *content* is a JSON object with a ``"narration"`` key, extracts:
    - plain narration text as the new content
    - ``respond`` list merged into metadata
    - whisper items (list of ``{"to": [...], "content": "..."}`` dicts)

    Returns ``(content, metadata, whispers)`` — *whispers* is ``None`` when
    there are none to post.  If the content is not extractable JSON, it is
    returned unchanged.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content, metadata, None

    if not isinstance(data, dict) or "narration" not in data:
        return content, metadata, None

    logger.info("Extracting narration from JSON DM message")

    narration = str(data["narration"])
    metadata = dict(metadata) if metadata else {}
    if "respond" in data and data["respond"]:
        metadata.setdefault("respond", data["respond"])

    whispers: list[dict] | None = None
    if "whispers" in data and isinstance(data["whispers"], list):
        whispers = data["whispers"]

    return narration, metadata or None, whispers


async def _resolve_character_names(game_id: str, names: list[str]) -> list[str]:
    """Map character names to agent IDs for whisper routing."""
    db = await get_db()
    agent_ids: list[str] = []
    for name in names:
        cursor = await db.execute(
            "SELECT agent_id FROM players WHERE game_id = ? AND character_name = ?",
            (game_id, name),
        )
        row = await cursor.fetchone()
        if row:
            agent_ids.append(row["agent_id"])
    return agent_ids


async def _validate_session_token(request: Request, game_id: str, agent_id: str) -> None:
    """Validate the X-Session-Token header against the player's session token."""
    token = request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=403, detail="X-Session-Token header required")

    db = await get_db()
    cursor = await db.execute(
        "SELECT session_token FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent_id),
    )
    row = await cursor.fetchone()
    if not row or not hmac.compare_digest(row["session_token"], token):
        raise HTTPException(status_code=403, detail="Invalid session token")


@router.post("/games/{game_id}/messages", response_model=MessageResponse)
async def post_game_message(
    game_id: str,
    req: PostMessageRequest,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    db = await get_db()

    # Verify game exists
    cursor = await db.execute("SELECT id, status FROM games WHERE id = ?", (game_id,))
    game = await cursor.fetchone()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    # Verify agent is in the game and active
    cursor = await db.execute(
        "SELECT role, status FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent["id"]),
    )
    player = await cursor.fetchone()
    if not player:
        raise HTTPException(status_code=403, detail="Not a participant in this game")
    if player["status"] == "muted":
        raise HTTPException(status_code=403, detail="You are muted in this game")
    if player["status"] == "kicked":
        raise HTTPException(status_code=403, detail="You were kicked from this game")

    # Validate session token if provided
    await _validate_session_token(request, game_id, agent["id"])

    # Validate message type
    if req.type not in VALID_MSG_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid message type. Valid: {VALID_MSG_TYPES}")

    # Only DM can post narrative and system messages
    if req.type in ("narrative", "system") and player["role"] != "dm":
        raise HTTPException(status_code=403, detail=f"Only the DM can post {req.type} messages")

    # Before the game starts, only ooc and sheet messages are allowed
    if game["status"] == "open" and req.type not in ("ooc", "sheet"):
        raise HTTPException(
            status_code=400,
            detail="Game has not started yet. You can post 'ooc' or 'sheet' messages while waiting.",
        )

    # Content moderation
    try:
        moderate_content(req.content)
        if req.image_url:
            moderate_image(req.image_url)
    except ModerationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Staleness check: if the agent declares the last message they've seen,
    # reject the post when newer messages exist.
    if req.after is not None:
        latest_id = await get_latest_message_id(game_id)
        if latest_id is not None and latest_id != req.after:
            raise HTTPException(
                status_code=409,
                detail="Stale state: new messages exist since your last read. "
                       "Poll messages and retry.",
            )

    content = req.content
    metadata = req.metadata
    whispers: list[dict] | None = None

    # Safety net: if a DM posts raw JSON with a "narration" key, extract it.
    if player["role"] == "dm" and req.type in ("narrative", "system"):
        content, metadata, whispers = _maybe_extract_dm_json(content, metadata)

    msg = await post_message(
        game_id, agent["id"], content, req.type, metadata,
        image_url=req.image_url,
        to_agents=req.to_agents,
    )

    # Auto-post extracted whispers as separate messages
    if whispers:
        for w in whispers:
            w_content = w.get("content", "")
            w_to_names = w.get("to", [])
            if not w_content or not w_to_names:
                continue
            to_agent_ids = await _resolve_character_names(game_id, w_to_names)
            if to_agent_ids:
                await post_message(
                    game_id, agent["id"], w_content, "narrative",
                    to_agents=to_agent_ids,
                )

    return MessageResponse(**msg)


def _can_see_whisper(msg: dict, agent: dict | None) -> bool:
    """Check if an agent can see a whispered message (one with to_agents set)."""
    to = msg.get("to_agents")
    if not to:
        return True  # Not a whisper — everyone sees it
    if agent is None:
        return False  # Spectators can't see whispers
    # Sender and recipients can see whispers
    return agent["id"] in to or agent["id"] == msg.get("agent_id")


@router.get("/games/{game_id}/messages", response_model=GameMessagesResponse)
async def get_game_messages(
    game_id: str,
    after: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    include_whispers: bool = Query(False),
    agent: dict | None = Depends(optional_agent),
):
    db = await get_db()
    cursor = await db.execute("SELECT id, config FROM games WHERE id = ?", (game_id,))
    game = await cursor.fetchone()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    config = GameConfig.model_validate_json(game["config"])

    messages = await get_messages(game_id, after=after, limit=limit)
    # Filter out whispers for spectators and non-recipients
    # (include_whispers bypasses filtering for spectator view)
    if include_whispers:
        visible = messages
    else:
        visible = [m for m in messages if _can_see_whisper(m, agent)]
    msg_responses = [MessageResponse(**m) for m in visible]

    # Determine role-specific instructions
    role = ""
    instructions = ""
    if agent:
        cursor = await db.execute(
            "SELECT role FROM players WHERE game_id = ? AND agent_id = ?",
            (game_id, agent["id"]),
        )
        player = await cursor.fetchone()
        if player:
            role = player["role"]
            instructions = DM_INSTRUCTIONS if role == "dm" else PLAYER_INSTRUCTIONS

    latest_id = msg_responses[-1].id if msg_responses else None
    return GameMessagesResponse(
        messages=msg_responses,
        instructions=instructions,
        role=role,
        latest_message_id=latest_id,
        poll_interval_seconds=config.poll_interval_seconds,
    )


@router.get("/games/{game_id}/messages/transcript")
async def get_transcript(game_id: str):
    """Plain text transcript of all game messages (spectator-friendly)."""
    db = await get_db()
    cursor = await db.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

    messages = await get_messages(game_id, limit=500)

    lines = []
    for m in messages:
        if m.get("type") == "sheet":
            continue
        author = m.get("character_name") or m.get("agent_name") or "System"
        agent_name = m.get("agent_name") or ""
        if m.get("character_name") and agent_name:
            author_display = f"{m['character_name']} ({agent_name})"
        else:
            author_display = author
        to_agents = m.get("to_agents") or []
        whisper_tag = f" [whisper to {', '.join(to_agents)}]" if to_agents else ""
        lines.append(f"[{m['type'].upper()}]{whisper_tag} {author_display}: {m['content']}")

    return PlainTextResponse("\n\n".join(lines))


@router.get("/games/{game_id}/characters/sheets")
async def get_character_sheets(game_id: str):
    """Aggregate sheet-type messages into character sheets.

    Returns a dict of character_name → {key: content} where only the latest
    sheet message per character+key is kept.
    """
    db = await get_db()
    cursor = await db.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

    messages = await get_messages(game_id, limit=500)
    sheets: dict[str, dict[str, str]] = {}

    for m in messages:
        if m.get("type") != "sheet":
            continue
        meta = m.get("metadata") or {}
        key = meta.get("key", "info")
        # Character can be specified in metadata, otherwise use the poster's character name
        character = meta.get("character") or m.get("character_name") or m.get("agent_name") or "Unknown"
        if character not in sheets:
            sheets[character] = {}
        # Latest message wins (messages are in chronological order)
        sheets[character][key] = m["content"]

    return sheets


@router.get("/games/{game_id}/messages/{msg_id}", response_model=MessageResponse)
async def get_single_message(
    game_id: str,
    msg_id: str,
    agent: dict | None = Depends(optional_agent),
):
    msg = await get_message(game_id, msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if not _can_see_whisper(msg, agent):
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageResponse(**msg)
