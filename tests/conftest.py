"""Shared test fixtures for the play-by-post server."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    """Create a test client with a fresh in-memory database."""
    from server.config import settings

    # Use in-memory SQLite for tests
    settings.db_path = ":memory:"

    from server.app import app
    from server.db import close_db, init_db

    await init_db(":memory:")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await close_db()


@pytest_asyncio.fixture
async def dm_agent(client: AsyncClient) -> dict:
    """Register a DM agent and return its info."""
    resp = await client.post("/agents/register", json={"name": "TestDM"})
    assert resp.status_code == 200
    return resp.json()


@pytest_asyncio.fixture
async def player_agent(client: AsyncClient) -> dict:
    """Register a player agent and return its info."""
    resp = await client.post("/agents/register", json={"name": "TestPlayer"})
    assert resp.status_code == 200
    return resp.json()


@pytest_asyncio.fixture
async def player_agent2(client: AsyncClient) -> dict:
    """Register a second player agent."""
    resp = await client.post("/agents/register", json={"name": "TestPlayer2"})
    assert resp.status_code == 200
    return resp.json()


def auth_header(agent: dict, session_token: str | None = None) -> dict:
    """Create auth headers for an agent, optionally including session token."""
    headers = {"Authorization": f"Bearer {agent['api_key']}"}
    if session_token:
        headers["X-Session-Token"] = session_token
    return headers


def unwrap_messages(resp_data: dict | list) -> list[dict]:
    """Unwrap the GameMessagesResponse envelope to get the messages list."""
    if isinstance(resp_data, dict):
        return resp_data.get("messages", [])
    return resp_data


async def get_session_token(game_id: str, agent_id: str) -> str:
    """Look up an agent's session token for a game from the database."""
    from server.db import get_db

    db = await get_db()
    cursor = await db.execute(
        "SELECT session_token FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent_id),
    )
    row = await cursor.fetchone()
    assert row, f"No player record for agent {agent_id} in game {game_id}"
    return row["session_token"]


@pytest_asyncio.fixture
async def game_id(client: AsyncClient, dm_agent: dict) -> str:
    """Create a game and return its ID."""
    resp = await client.post(
        "/lobby",
        json={"name": "Test Game"},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest_asyncio.fixture
async def started_game_id(client: AsyncClient, dm_agent: dict) -> str:
    """Create and start a game, return its ID."""
    resp = await client.post(
        "/lobby",
        json={"name": "Started Test Game"},
        headers=auth_header(dm_agent),
    )
    assert resp.status_code == 200
    gid = resp.json()["id"]
    token = await get_session_token(gid, dm_agent["id"])
    resp = await client.post(
        f"/games/{gid}/start",
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    return gid
