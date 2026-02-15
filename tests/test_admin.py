"""Tests for DM admin actions: kick, mute, unmute, invite."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, get_session_token, unwrap_messages


@pytest.mark.asyncio
async def test_kick_player(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    # Player joins
    await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))

    # DM kicks player
    resp = await client.post(
        f"/games/{game_id}/admin/kick",
        json={"agent_id": player_agent["id"], "reason": "disruptive"},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "kicked"

    # Verify player can't rejoin
    resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mute_unmute_player(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    join_resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    player_token = join_resp.json()["session_token"]

    # Mute
    resp = await client.post(
        f"/games/{game_id}/admin/mute",
        json={"agent_id": player_agent["id"]},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200

    # Verify player can't post (muted status blocks before session token check)
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Hello", "type": "action"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 403

    # Unmute
    resp = await client.post(
        f"/games/{game_id}/admin/unmute",
        json={"agent_id": player_agent["id"]},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200

    # Verify player can post again
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "I'm back", "type": "action"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invite_player(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/admin/invite",
        json={"agent_id": player_agent["id"]},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200

    # Verify player is in the game
    resp = await client.get(f"/games/{game_id}/players")
    players = resp.json()
    agent_ids = [p["agent_id"] for p in players]
    assert player_agent["id"] in agent_ids


@pytest.mark.asyncio
async def test_non_dm_cannot_kick(client: AsyncClient, dm_agent: dict, player_agent: dict, player_agent2: dict, game_id: str):
    await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent2))

    resp = await client.post(
        f"/games/{game_id}/admin/kick",
        json={"agent_id": player_agent2["id"]},
        headers=auth_header(player_agent),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_kick_system_message(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    await client.post(
        f"/games/{game_id}/admin/kick",
        json={"agent_id": player_agent["id"], "reason": "testing"},
        headers=auth_header(dm_agent),
    )

    # Check that a system message was posted
    resp = await client.get(f"/games/{game_id}/messages")
    messages = unwrap_messages(resp.json())
    kick_msgs = [m for m in messages if "kicked" in m["content"]]
    assert len(kick_msgs) > 0
