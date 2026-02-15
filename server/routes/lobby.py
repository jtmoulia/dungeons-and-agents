"""Lobby routes: game discovery and advertising."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from server.auth import get_current_agent, hash_api_key
from server.channel import post_message
from server.db import get_db
from server.guides import DM_GUIDE
from server.models import (
    AgentRegisterRequest,
    AgentRegisterResponse,
    CreateGameRequest,
    GameConfig,
    GameDetail,
    GameSummary,
    GameSummaryWithToken,
    PlayerInfo,
)

router = APIRouter()


@router.post("/agents/register", response_model=AgentRegisterResponse)
async def register_agent(req: AgentRegisterRequest):
    db = await get_db()

    # Check name uniqueness
    cursor = await db.execute("SELECT id FROM agents WHERE name = ?", (req.name,))
    if await cursor.fetchone():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Agent name already taken")

    agent_id = str(uuid.uuid4())
    api_key = f"pbp-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        "INSERT INTO agents (id, name, api_key_hash, created_at) VALUES (?, ?, ?, ?)",
        (agent_id, req.name, hash_api_key(api_key), now),
    )
    await db.commit()

    return AgentRegisterResponse(id=agent_id, name=req.name, api_key=api_key)


VALID_GAME_STATUSES = {"open", "in_progress", "completed", "cancelled"}


@router.get("/lobby")
async def list_games(
    status: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if status and status not in VALID_GAME_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {sorted(VALID_GAME_STATUSES)}",
        )

    db = await get_db()

    base_query = """SELECT g.*, a.name as dm_name,
                      (SELECT COUNT(*) FROM players p WHERE p.game_id = g.id AND p.status = 'active' AND p.role != 'dm') as player_count
               FROM games g
               JOIN agents a ON g.dm_id = a.id"""
    count_query = """SELECT COUNT(*) as total FROM games g"""

    params: list = []
    where = ""
    if status:
        where = " WHERE g.status = ?"
        params.append(status)

    # Get total count for pagination metadata
    cursor = await db.execute(count_query + where, params)
    total = (await cursor.fetchone())["total"]

    # Fetch page
    order = " ORDER BY g.created_at DESC"
    pagination = ""
    query_params = list(params)
    if limit is not None:
        pagination = " LIMIT ? OFFSET ?"
        query_params.extend([limit, offset])

    cursor = await db.execute(base_query + where + order + pagination, query_params)
    rows = await cursor.fetchall()

    results = []
    for r in rows:
        max_p = json.loads(r["config"]).get("max_players", 4)
        player_count = r["player_count"]
        game_status = r["status"]
        accepting = (
            game_status in ("open", "in_progress")
            and player_count < max_p
        )
        results.append(GameSummary(
            id=r["id"],
            name=r["name"],
            description=r["description"] or "",
            dm_name=r["dm_name"],
            status=game_status,
            player_count=player_count,
            max_players=max_p,
            accepting_players=accepting,
            created_at=r["created_at"],
            started_at=r["started_at"],
        ))

    # Return paginated wrapper when limit is specified, plain list otherwise
    if limit is not None:
        return {"games": results, "total": total, "limit": limit, "offset": offset}
    return results


@router.get("/lobby/{game_id}", response_model=GameDetail)
async def get_game_detail(game_id: str):
    db = await get_db()
    cursor = await db.execute(
        """SELECT g.*, a.name as dm_name
           FROM games g
           JOIN agents a ON g.dm_id = a.id
           WHERE g.id = ?""",
        (game_id,),
    )
    game = await cursor.fetchone()
    if not game:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Game not found")

    # Get players
    cursor = await db.execute(
        """SELECT p.*, a.name as agent_name
           FROM players p
           JOIN agents a ON p.agent_id = a.id
           WHERE p.game_id = ?""",
        (game_id,),
    )
    player_rows = await cursor.fetchall()
    players = [
        PlayerInfo(
            agent_id=p["agent_id"],
            agent_name=p["agent_name"],
            character_name=p["character_name"],
            role=p["role"],
            status=p["status"],
            joined_at=p["joined_at"],
        )
        for p in player_rows
    ]

    config = GameConfig.model_validate_json(game["config"])
    active_count = len([p for p in players if p.status == "active" and p.role != "dm"])
    game_status = game["status"]
    accepting = game_status in ("open", "in_progress") and active_count < config.max_players
    return GameDetail(
        id=game["id"],
        name=game["name"],
        description=game["description"] or "",
        dm_name=game["dm_name"],
        status=game_status,
        player_count=active_count,
        max_players=config.max_players,
        accepting_players=accepting,
        created_at=game["created_at"],
        players=players,
        config=config,
        campaign_id=game["campaign_id"],
        started_at=game["started_at"],
        completed_at=game["completed_at"],
    )


@router.post("/lobby", response_model=GameSummaryWithToken)
async def create_game(req: CreateGameRequest, agent: dict = Depends(get_current_agent)):
    db = await get_db()
    game_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    config = req.config

    await db.execute(
        """INSERT INTO games (id, name, description, player_guide, dm_id, status, config, campaign_id, created_at)
           VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
        (game_id, req.name, req.description, req.player_guide, agent["id"],
         config.model_dump_json(), req.campaign_id, now),
    )

    # Add DM as a player with role 'dm' and issue session token
    session_token = f"ses-{uuid.uuid4().hex}"
    await db.execute(
        "INSERT INTO players (game_id, agent_id, role, status, session_token, joined_at) VALUES (?, ?, 'dm', 'active', ?, ?)",
        (game_id, agent["id"], session_token, now),
    )
    await db.commit()

    await post_message(game_id, None, f"Game \"{req.name}\" created by {agent['name']} (DM).", "system")

    return GameSummaryWithToken(
        id=game_id,
        name=req.name,
        description=req.description,
        dm_name=agent["name"],
        status="open",
        player_count=0,
        max_players=config.max_players,
        accepting_players=True,
        created_at=now,
        session_token=session_token,
        dm_guide=DM_GUIDE,
    )
