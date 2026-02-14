"""Game management routes: join, leave, start, end, config."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from server.auth import get_current_agent
from server.channel import post_message
from server.db import get_db
from server.models import (
    GameConfig,
    JoinGameRequest,
    JoinGameResponse,
    PlayerInfo,
    UpdateConfigRequest,
)

router = APIRouter()


async def _get_game(game_id: str) -> dict:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = await cursor.fetchone()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return dict(game)


async def _verify_dm(game_id: str, agent_id: str) -> None:
    game = await _get_game(game_id)
    if game["dm_id"] != agent_id:
        raise HTTPException(status_code=403, detail="Only the DM can perform this action")


@router.post("/games/{game_id}/join")
async def join_game(game_id: str, req: JoinGameRequest, agent: dict = Depends(get_current_agent)):
    db = await get_db()
    game = await _get_game(game_id)
    config = GameConfig.model_validate_json(game["config"])

    # Check game status
    if game["status"] == "completed" or game["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="Game is no longer active")
    if game["status"] == "in_progress" and not config.allow_mid_session_join:
        raise HTTPException(status_code=400, detail="Mid-session join not allowed")

    # Check if already in game
    cursor = await db.execute(
        "SELECT agent_id, status FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent["id"]),
    )
    existing = await cursor.fetchone()
    if existing:
        if existing["status"] == "kicked":
            raise HTTPException(status_code=403, detail="You were kicked from this game")
        raise HTTPException(status_code=409, detail="Already in game")

    # Check player count
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE game_id = ? AND role = 'player' AND status = 'active'",
        (game_id,),
    )
    count = (await cursor.fetchone())["cnt"]
    if count >= config.max_players:
        raise HTTPException(status_code=400, detail="Game is full")

    now = datetime.now(timezone.utc).isoformat()
    session_token = f"ses-{uuid.uuid4().hex}"
    await db.execute(
        "INSERT INTO players (game_id, agent_id, character_name, role, status, session_token, joined_at) VALUES (?, ?, ?, 'player', 'active', ?, ?)",
        (game_id, agent["id"], req.character_name, session_token, now),
    )
    await db.commit()

    char_info = f" as {req.character_name}" if req.character_name else ""
    await post_message(game_id, None, f"{agent['name']} joined{char_info}.", "system")

    return JoinGameResponse(status="joined", game_id=game_id, session_token=session_token)


@router.post("/games/{game_id}/leave")
async def leave_game(game_id: str, agent: dict = Depends(get_current_agent)):
    db = await get_db()
    await _get_game(game_id)

    cursor = await db.execute(
        "SELECT role FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent["id"]),
    )
    player = await cursor.fetchone()
    if not player:
        raise HTTPException(status_code=404, detail="Not in game")
    if player["role"] == "dm":
        raise HTTPException(status_code=400, detail="DM cannot leave their own game")

    await db.execute(
        "DELETE FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent["id"]),
    )
    await db.commit()
    await post_message(game_id, None, f"{agent['name']} left the game.", "system")

    return {"status": "left", "game_id": game_id}


@router.post("/games/{game_id}/start")
async def start_game(game_id: str, agent: dict = Depends(get_current_agent)):
    await _verify_dm(game_id, agent["id"])
    db = await get_db()
    game = await _get_game(game_id)

    if game["status"] != "open":
        raise HTTPException(status_code=400, detail=f"Game cannot be started (status: {game['status']})")

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE games SET status = 'in_progress', started_at = ? WHERE id = ?",
        (now, game_id),
    )
    await db.commit()
    await post_message(game_id, None, "Game started!", "system")

    return {"status": "in_progress", "game_id": game_id}


@router.post("/games/{game_id}/end")
async def end_game(game_id: str, agent: dict = Depends(get_current_agent)):
    await _verify_dm(game_id, agent["id"])
    db = await get_db()
    game = await _get_game(game_id)

    if game["status"] not in ("open", "in_progress"):
        raise HTTPException(status_code=400, detail=f"Game cannot be ended (status: {game['status']})")

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE games SET status = 'completed', completed_at = ? WHERE id = ?",
        (now, game_id),
    )
    await db.commit()
    await post_message(game_id, None, "Game ended.", "system")

    return {"status": "completed", "game_id": game_id}


@router.get("/games/{game_id}/players", response_model=list[PlayerInfo])
async def list_players(game_id: str):
    db = await get_db()
    await _get_game(game_id)

    cursor = await db.execute(
        """SELECT p.*, a.name as agent_name
           FROM players p
           JOIN agents a ON p.agent_id = a.id
           WHERE p.game_id = ?""",
        (game_id,),
    )
    rows = await cursor.fetchall()
    return [
        PlayerInfo(
            agent_id=r["agent_id"],
            agent_name=r["agent_name"],
            character_name=r["character_name"],
            role=r["role"],
            status=r["status"],
            joined_at=r["joined_at"],
        )
        for r in rows
    ]


@router.patch("/games/{game_id}/config")
async def update_config(game_id: str, req: UpdateConfigRequest, agent: dict = Depends(get_current_agent)):
    await _verify_dm(game_id, agent["id"])
    db = await get_db()

    await db.execute(
        "UPDATE games SET config = ? WHERE id = ?",
        (req.config.model_dump_json(), game_id),
    )
    await db.commit()

    return {"status": "updated", "config": req.config.model_dump()}
