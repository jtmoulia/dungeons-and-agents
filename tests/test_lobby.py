"""Tests for lobby routes: agent registration, game creation, discovery."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_register_agent(client: AsyncClient):
    resp = await client.post("/agents/register", json={"name": "Coggy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Coggy"
    assert data["id"]
    assert data["api_key"].startswith("pbp-")


@pytest.mark.asyncio
async def test_register_duplicate_name(client: AsyncClient):
    await client.post("/agents/register", json={"name": "Dup"})
    resp = await client.post("/agents/register", json={"name": "Dup"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_games_empty(client: AsyncClient):
    resp = await client.get("/lobby")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_game(client: AsyncClient, dm_agent: dict):
    resp = await client.post(
        "/lobby",
        json={"name": "Dragon Quest", "description": "A fantasy adventure"},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Dragon Quest"
    assert data["status"] == "open"
    assert data["dm_name"] == "TestDM"


@pytest.mark.asyncio
async def test_create_game_requires_auth(client: AsyncClient):
    resp = await client.post("/lobby", json={"name": "No Auth"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_games_with_filter(client: AsyncClient, dm_agent: dict):
    headers = auth_header(dm_agent)
    await client.post("/lobby", json={"name": "Game1"}, headers=headers)
    await client.post("/lobby", json={"name": "Game2"}, headers=headers)

    resp = await client.get("/lobby?status=open")
    assert resp.status_code == 200
    games = resp.json()
    assert len(games) == 2
    assert all(g["status"] == "open" for g in games)


@pytest.mark.asyncio
async def test_get_game_detail(client: AsyncClient, dm_agent: dict, game_id: str):
    resp = await client.get(f"/lobby/{game_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Game"
    assert data["dm_name"] == "TestDM"
    assert len(data["players"]) == 1  # DM is a player
    assert data["players"][0]["role"] == "dm"


@pytest.mark.asyncio
async def test_get_game_detail_not_found(client: AsyncClient):
    resp = await client.get("/lobby/nonexistent")
    assert resp.status_code == 404


# --- Voting ---


@pytest.mark.asyncio
async def test_vote_game(client: AsyncClient, dm_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/vote",
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["voted"] is True
    assert data["vote_count"] == 1


@pytest.mark.asyncio
async def test_unvote_game(client: AsyncClient, dm_agent: dict, game_id: str):
    headers = auth_header(dm_agent)
    # Vote
    await client.post(f"/games/{game_id}/vote", headers=headers)
    # Un-vote (toggle)
    resp = await client.post(f"/games/{game_id}/vote", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["voted"] is False
    assert data["vote_count"] == 0


@pytest.mark.asyncio
async def test_vote_requires_auth(client: AsyncClient, game_id: str):
    resp = await client.post(f"/games/{game_id}/vote")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_vote_game_not_found(client: AsyncClient, dm_agent: dict):
    resp = await client.post(
        "/games/nonexistent/vote",
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_vote_count(client: AsyncClient, dm_agent: dict, game_id: str):
    # Initially zero
    resp = await client.get(f"/games/{game_id}/votes")
    assert resp.status_code == 200
    assert resp.json()["vote_count"] == 0

    # Vote and check
    await client.post(f"/games/{game_id}/vote", headers=auth_header(dm_agent))
    resp = await client.get(f"/games/{game_id}/votes")
    assert resp.json()["vote_count"] == 1


@pytest.mark.asyncio
async def test_vote_count_in_lobby(client: AsyncClient, dm_agent: dict, game_id: str):
    # Vote for the game
    await client.post(f"/games/{game_id}/vote", headers=auth_header(dm_agent))

    resp = await client.get("/lobby")
    games = resp.json()
    assert len(games) == 1
    assert games[0]["vote_count"] == 1


@pytest.mark.asyncio
async def test_closed_game_without_messages_hidden(client: AsyncClient, dm_agent: dict):
    """Completed/cancelled games with no user messages are excluded from the lobby."""
    headers = auth_header(dm_agent)
    # Create and immediately end a game (no user messages posted)
    resp = await client.post("/lobby", json={"name": "Dead Game"}, headers=headers)
    game_id = resp.json()["id"]
    token_resp = resp.json()["session_token"]
    await client.post(
        f"/games/{game_id}/end",
        headers=auth_header(dm_agent, token_resp),
    )

    # Should not appear in unfiltered lobby listing
    resp = await client.get("/lobby")
    games = resp.json()
    assert not any(g["id"] == game_id for g in games)

    # Should not appear when filtering for completed games either
    resp = await client.get("/lobby?status=completed")
    games = resp.json()
    assert not any(g["id"] == game_id for g in games)


@pytest.mark.asyncio
async def test_closed_game_with_messages_shown(client: AsyncClient, dm_agent: dict):
    """Completed games that had real messages still appear in the lobby."""
    headers = auth_header(dm_agent)
    resp = await client.post("/lobby", json={"name": "Played Game"}, headers=headers)
    game_id = resp.json()["id"]
    session_token = resp.json()["session_token"]

    # Start the game and post a real message
    await client.post(f"/games/{game_id}/start", headers=auth_header(dm_agent, session_token))
    await client.post(
        f"/games/{game_id}/messages",
        json={"type": "narrative", "content": "The story begins..."},
        headers=auth_header(dm_agent, session_token),
    )
    await client.post(f"/games/{game_id}/end", headers=auth_header(dm_agent, session_token))

    # Should still appear
    resp = await client.get("/lobby?status=completed")
    games = resp.json()
    assert any(g["id"] == game_id for g in games)


@pytest.mark.asyncio
async def test_poll_interval_in_lobby_list(client: AsyncClient, dm_agent: dict):
    """poll_interval_seconds appears as a top-level field in lobby listings."""
    headers = auth_header(dm_agent)
    await client.post(
        "/lobby",
        json={"name": "Slow Game", "config": {"poll_interval_seconds": 30}},
        headers=headers,
    )
    resp = await client.get("/lobby")
    games = resp.json()
    assert len(games) >= 1
    slow = [g for g in games if g["name"] == "Slow Game"][0]
    assert slow["poll_interval_seconds"] == 30


@pytest.mark.asyncio
async def test_poll_interval_in_game_detail(client: AsyncClient, dm_agent: dict):
    """poll_interval_seconds appears as a top-level field in game detail."""
    headers = auth_header(dm_agent)
    resp = await client.post(
        "/lobby",
        json={"name": "Fast Game", "config": {"poll_interval_seconds": 1}},
        headers=headers,
    )
    game_id = resp.json()["id"]
    resp = await client.get(f"/lobby/{game_id}")
    data = resp.json()
    assert data["poll_interval_seconds"] == 1


@pytest.mark.asyncio
async def test_poll_interval_default_in_lobby(client: AsyncClient, dm_agent: dict, game_id: str):
    """Games created without explicit poll_interval use default (300s) in lobby."""
    resp = await client.get("/lobby")
    games = resp.json()
    game = [g for g in games if g["id"] == game_id][0]
    assert game["poll_interval_seconds"] == 300


@pytest.mark.asyncio
async def test_lobby_sort_by_top(
    client: AsyncClient, dm_agent: dict, player_agent: dict
):
    headers = auth_header(dm_agent)
    # Create two games
    resp1 = await client.post("/lobby", json={"name": "Unpopular"}, headers=headers)
    game1_id = resp1.json()["id"]
    resp2 = await client.post("/lobby", json={"name": "Popular"}, headers=headers)
    game2_id = resp2.json()["id"]

    # Vote for game2 with both agents
    await client.post(f"/games/{game2_id}/vote", headers=auth_header(dm_agent))
    await client.post(f"/games/{game2_id}/vote", headers=auth_header(player_agent))
    # Vote for game1 with one agent
    await client.post(f"/games/{game1_id}/vote", headers=auth_header(dm_agent))

    # Default sort (newest) — game2 should be first (created later)
    resp = await client.get("/lobby")
    games = resp.json()
    assert games[0]["id"] == game2_id

    # Sort by top — game2 (2 votes) first, game1 (1 vote) second
    resp = await client.get("/lobby?sort=top")
    games = resp.json()
    assert games[0]["name"] == "Popular"
    assert games[0]["vote_count"] == 2
    assert games[1]["name"] == "Unpopular"
    assert games[1]["vote_count"] == 1
