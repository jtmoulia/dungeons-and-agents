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
        json={"name": "Hull Breach", "engine_type": "mothership", "description": "A sci-fi horror game"},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Hull Breach"
    assert data["engine_type"] == "mothership"
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
