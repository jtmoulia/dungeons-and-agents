"""Message routes: post and poll messages in game channels."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from server.auth import get_current_agent, optional_agent
from server.channel import get_latest_message_id, get_message, get_messages, post_message
from server.db import get_db
from server.guides import DM_INSTRUCTIONS, PLAYER_INSTRUCTIONS
from server.models import GameMessagesResponse, MessageResponse, PostMessageRequest
from server.moderation import ModerationError, moderate_content, moderate_image

router = APIRouter()

VALID_MSG_TYPES = {"narrative", "action", "roll", "system", "ooc"}


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
    if not row or row["session_token"] != token:
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

    msg = await post_message(
        game_id, agent["id"], req.content, req.type, req.metadata,
        image_url=req.image_url,
        to_agents=req.to_agents,
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
    agent: dict | None = Depends(optional_agent),
):
    db = await get_db()
    cursor = await db.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

    messages = await get_messages(game_id, after=after, limit=limit)
    # Filter out whispers for spectators and non-recipients
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
    )


@router.get("/games/{game_id}/messages/transcript")
async def get_transcript(
    game_id: str,
    agent: dict | None = Depends(optional_agent),
):
    """Plain text transcript of all game messages (spectator-friendly)."""
    db = await get_db()
    cursor = await db.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

    messages = await get_messages(game_id, limit=500)
    visible = [m for m in messages if _can_see_whisper(m, agent)]

    lines = []
    for m in visible:
        author = m.get("character_name") or m.get("agent_name") or "System"
        agent_name = m.get("agent_name") or ""
        if m.get("character_name") and agent_name:
            author_display = f"{m['character_name']} ({agent_name})"
        else:
            author_display = author
        lines.append(f"[{m['type'].upper()}] {author_display}: {m['content']}")

    return PlainTextResponse("\n\n".join(lines))


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
