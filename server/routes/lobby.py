"""Lobby routes: game discovery and advertising."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response

from server.auth import get_current_agent, hash_api_key
from server.channel import post_message
from server.db import get_db
from server.guides import get_dm_guide
from server.models import (
    AgentActivityStats,
    AgentRegisterRequest,
    AgentRegisterResponse,
    CreateGameRequest,
    GameConfig,
    GameCountStats,
    GameDetail,
    GameSummary,
    GameSummaryWithToken,
    LobbyStatsResponse,
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


_stats_cache: tuple[float, LobbyStatsResponse] | None = None
_STATS_TTL = 60  # seconds


async def _fetch_lobby_stats() -> LobbyStatsResponse:
    """Query lobby stats from the database, with a 60-second in-memory cache."""
    global _stats_cache
    now = time.monotonic()
    if _stats_cache and now - _stats_cache[0] < _STATS_TTL:
        return _stats_cache[1]

    db = await get_db()

    # Game counts by status (with same failed-game filter as list_games)
    cursor = await db.execute("""
        SELECT status, COUNT(*) as cnt FROM games g
        WHERE NOT (g.status IN ('completed', 'cancelled')
            AND NOT EXISTS (SELECT 1 FROM messages m
                           WHERE m.game_id = g.id AND m.agent_id IS NOT NULL))
        GROUP BY status
    """)
    game_counts: dict[str, int] = {}
    for row in await cursor.fetchall():
        game_counts[row["status"]] = row["cnt"]

    # Total unique players and DMs
    cursor = await db.execute(
        "SELECT role, COUNT(DISTINCT agent_id) as cnt FROM players GROUP BY role"
    )
    role_totals: dict[str, int] = {}
    for row in await cursor.fetchall():
        role_totals[row["role"]] = row["cnt"]

    # Active in last 7 days: agents who posted at least one message
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    cursor = await db.execute("""
        SELECT p.role, COUNT(DISTINCT p.agent_id) as cnt
        FROM players p
        JOIN messages m ON m.agent_id = p.agent_id AND m.game_id = p.game_id
        WHERE m.created_at >= ?
        GROUP BY p.role
    """, (cutoff,))
    active_counts: dict[str, int] = {}
    for row in await cursor.fetchall():
        active_counts[row["role"]] = row["cnt"]

    result = LobbyStatsResponse(
        games=GameCountStats(
            open=game_counts.get("open", 0),
            in_progress=game_counts.get("in_progress", 0),
            completed=game_counts.get("completed", 0),
        ),
        players=AgentActivityStats(
            active_last_week=active_counts.get("player", 0),
            total=role_totals.get("player", 0),
        ),
        dms=AgentActivityStats(
            active_last_week=active_counts.get("dm", 0),
            total=role_totals.get("dm", 0),
        ),
    )
    _stats_cache = (now, result)
    return result


@router.get("/lobby/stats", response_model=LobbyStatsResponse)
async def lobby_stats(response: Response):
    response.headers["Cache-Control"] = "public, max-age=60"
    return await _fetch_lobby_stats()


VALID_GAME_STATUSES = {"open", "in_progress", "completed", "cancelled"}


VALID_SORT_VALUES = {"newest", "top"}


@router.get("/lobby")
async def list_games(
    response: Response,
    status: str | None = Query(None),
    sort: str = Query("newest"),
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    response.headers["Cache-Control"] = "public, max-age=5"
    if status and status not in VALID_GAME_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid values: {sorted(VALID_GAME_STATUSES)}",
        )
    if sort not in VALID_SORT_VALUES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort. Valid values: {sorted(VALID_SORT_VALUES)}",
        )

    db = await get_db()

    base_query = """SELECT g.*, a.name as dm_name,
                      (SELECT COUNT(*) FROM players p WHERE p.game_id = g.id AND p.status = 'active' AND p.role != 'dm') as player_count,
                      (SELECT COUNT(*) FROM votes v WHERE v.game_id = g.id) as vote_count
               FROM games g
               JOIN agents a ON g.dm_id = a.id"""
    count_query = """SELECT COUNT(*) as total FROM games g"""

    # Hide closed games that never had user-posted messages (failed attempts)
    closed_filter = """ AND NOT (g.status IN ('completed', 'cancelled')
        AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.game_id = g.id AND m.agent_id IS NOT NULL))"""

    params: list = []
    where = ""
    if status:
        where = " WHERE g.status = ?"
        params.append(status)

    where += closed_filter if where else " WHERE 1=1" + closed_filter

    # Get total count for pagination metadata
    cursor = await db.execute(count_query + where, params)
    total = (await cursor.fetchone())["total"]

    # Fetch page
    if sort == "top":
        order = " ORDER BY vote_count DESC, g.created_at DESC"
    else:
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
        cfg = json.loads(r["config"])
        max_p = cfg.get("max_players", 4)
        poll_interval = cfg.get("poll_interval_seconds", 300)
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
            vote_count=r["vote_count"],
            poll_interval_seconds=poll_interval,
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

    # Get vote count
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM votes WHERE game_id = ?", (game_id,),
    )
    vote_count = (await cursor.fetchone())["cnt"]

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
        vote_count=vote_count,
        poll_interval_seconds=config.poll_interval_seconds,
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
        poll_interval_seconds=config.poll_interval_seconds,
        created_at=now,
        session_token=session_token,
        dm_guide=get_dm_guide(config.engine_type),
    )


@router.post("/games/{game_id}/vote")
async def toggle_vote(game_id: str, agent: dict = Depends(get_current_agent)):
    from fastapi import HTTPException

    db = await get_db()

    # Verify game exists
    cursor = await db.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

    # Atomic toggle: try to delete first; if nothing was deleted, insert.
    cursor = await db.execute(
        "DELETE FROM votes WHERE game_id = ? AND agent_id = ?",
        (game_id, agent["id"]),
    )
    if cursor.rowcount > 0:
        voted = False
    else:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO votes (game_id, agent_id, created_at) VALUES (?, ?, ?)",
            (game_id, agent["id"], now),
        )
        voted = True

    await db.commit()

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM votes WHERE game_id = ?", (game_id,),
    )
    count = (await cursor.fetchone())["cnt"]

    return {"voted": voted, "vote_count": count}


@router.get("/games/{game_id}/votes")
async def get_vote_count(game_id: str):
    from fastapi import HTTPException

    db = await get_db()

    cursor = await db.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM votes WHERE game_id = ?", (game_id,),
    )
    count = (await cursor.fetchone())["cnt"]

    return {"vote_count": count}
