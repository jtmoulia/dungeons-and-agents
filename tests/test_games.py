"""Tests for game management: join, leave, start, end, config."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_join_game(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/join",
        json={"character_name": "Coggy"},
        headers=auth_header(player_agent),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "joined"


@pytest.mark.asyncio
async def test_join_game_duplicate(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    await client.post(
        f"/games/{game_id}/join",
        json={"character_name": "Coggy"},
        headers=auth_header(player_agent),
    )
    resp = await client.post(
        f"/games/{game_id}/join",
        json={"character_name": "Coggy"},
        headers=auth_header(player_agent),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_join_game_full(client: AsyncClient, dm_agent: dict, game_id: str):
    # Update config to max 1 player
    from server.models import GameConfig

    await client.patch(
        f"/games/{game_id}/config",
        json={"config": GameConfig(max_players=1).model_dump()},
        headers=auth_header(dm_agent),
    )

    # First player joins
    p1 = (await client.post("/agents/register", json={"name": "P1"})).json()
    await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(p1))

    # Second player should be rejected
    p2 = (await client.post("/agents/register", json={"name": "P2"})).json()
    resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(p2))
    assert resp.status_code == 400
    assert "full" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_leave_game(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    await client.post(
        f"/games/{game_id}/join", json={}, headers=auth_header(player_agent)
    )
    resp = await client.post(
        f"/games/{game_id}/leave", headers=auth_header(player_agent)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "left"


@pytest.mark.asyncio
async def test_dm_cannot_leave(client: AsyncClient, dm_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/leave", headers=auth_header(dm_agent)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_game(client: AsyncClient, dm_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/start", headers=auth_header(dm_agent)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_start_game_non_dm(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/start", headers=auth_header(player_agent)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_end_game(client: AsyncClient, dm_agent: dict, game_id: str):
    await client.post(f"/games/{game_id}/start", headers=auth_header(dm_agent))
    resp = await client.post(f"/games/{game_id}/end", headers=auth_header(dm_agent))
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_list_players(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    await client.post(
        f"/games/{game_id}/join",
        json={"character_name": "Coggy"},
        headers=auth_header(player_agent),
    )
    resp = await client.get(f"/games/{game_id}/players")
    assert resp.status_code == 200
    players = resp.json()
    assert len(players) == 2  # DM + player
    roles = {p["role"] for p in players}
    assert "dm" in roles
    assert "player" in roles


@pytest.mark.asyncio
async def test_update_config(client: AsyncClient, dm_agent: dict, game_id: str):
    resp = await client.patch(
        f"/games/{game_id}/config",
        json={"config": {"max_players": 6, "allow_spectators": True,
                         "allow_mid_session_join": False, "skip_action": "defend"}},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["max_players"] == 6


@pytest.mark.asyncio
async def test_mid_session_join_blocked(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    # Disable mid-session join
    await client.patch(
        f"/games/{game_id}/config",
        json={"config": {"max_players": 4, "allow_spectators": True,
                         "allow_mid_session_join": False, "skip_action": "idle"}},
        headers=auth_header(dm_agent),
    )
    # Start game
    await client.post(f"/games/{game_id}/start", headers=auth_header(dm_agent))
    # Try to join
    resp = await client.post(
        f"/games/{game_id}/join", json={}, headers=auth_header(player_agent)
    )
    assert resp.status_code == 400
    assert "Mid-session" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_auto_close_inactive_game(client: AsyncClient, dm_agent: dict, game_id: str):
    """Games with no messages beyond the inactivity timeout are auto-closed."""
    from server.app import _close_inactive_games
    from server.db import get_db

    # Backdate all messages so the game appears inactive
    db = await get_db()
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    await db.execute(
        "UPDATE messages SET created_at = ? WHERE game_id = ?",
        (old_time, game_id),
    )
    await db.commit()

    closed = await _close_inactive_games()
    assert closed == 1

    # Verify the game is now completed
    resp = await client.get(f"/lobby/{game_id}")
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_active_game_not_closed(client: AsyncClient, dm_agent: dict, game_id: str):
    """Games with recent messages are not auto-closed."""
    from server.app import _close_inactive_games

    # Game was just created with a system message — should not be closed
    closed = await _close_inactive_games()
    assert closed == 0
