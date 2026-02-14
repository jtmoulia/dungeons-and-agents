"""Tests for engine plugin interface and implementations."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from server.engine.base import EngineAction
from server.engine.freestyle import FreestylePlugin
from server.engine.mothership import MothershipPlugin
from tests.conftest import auth_header, get_session_token


# --- Unit tests for plugins ---


def test_freestyle_process_action():
    plugin = FreestylePlugin()
    plugin.create_character("Coggy")
    action = EngineAction(action_type="search", character="Coggy", params={"room": "cargo bay"})
    result = plugin.process_action(action)
    assert result.success is True
    assert "DM resolves" in result.summary


def test_freestyle_state_roundtrip():
    plugin = FreestylePlugin()
    plugin.create_character("Coggy", role="marine")
    state = plugin.save_state()

    plugin2 = FreestylePlugin()
    plugin2.load_state(state)
    chars = plugin2.list_characters()
    assert len(chars) == 1
    assert chars[0]["name"] == "Coggy"


def test_mothership_create_character():
    plugin = MothershipPlugin()
    char = plugin.create_character("Coggy", char_class="marine")
    assert char["name"] == "Coggy"
    assert char["char_class"] == "marine"
    assert char["hp"] > 0


def test_mothership_roll():
    plugin = MothershipPlugin()
    plugin.create_character("Coggy", char_class="marine")
    action = EngineAction(
        action_type="roll",
        character="Coggy",
        params={"stat": "combat"},
    )
    result = plugin.process_action(action)
    assert "Coggy rolls combat" in result.summary
    assert "roll" in result.details
    assert "target" in result.details


def test_mothership_state_roundtrip():
    plugin = MothershipPlugin()
    plugin.create_character("Coggy", char_class="marine")
    state = plugin.save_state()

    plugin2 = MothershipPlugin()
    plugin2.load_state(state)
    chars = plugin2.list_characters()
    assert len(chars) == 1
    assert chars[0]["name"] == "Coggy"


def test_mothership_heal():
    plugin = MothershipPlugin()
    plugin.create_character("Coggy", char_class="marine")
    # Damage first
    plugin.process_action(EngineAction(
        action_type="damage", character="Coggy",
        params={"target": "Coggy", "amount": 5},
    ))
    result = plugin.process_action(EngineAction(
        action_type="heal", character="Coggy",
        params={"target": "Coggy", "amount": 3},
    ))
    assert result.success is True
    assert "heals" in result.summary


def test_mothership_unknown_action():
    plugin = MothershipPlugin()
    plugin.create_character("Coggy", char_class="marine")
    result = plugin.process_action(EngineAction(
        action_type="teleport", character="Coggy",
    ))
    assert result.success is False
    assert "Unknown action" in result.summary


# --- API integration tests ---


@pytest.mark.asyncio
async def test_engine_action_roll(client: AsyncClient, dm_agent: dict, mothership_game_id: str):
    token = await get_session_token(mothership_game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)

    # Create a character in the engine
    resp = await client.post(
        f"/games/{mothership_game_id}/engine/action",
        json={
            "action_type": "roll",
            "character": "TestDM",
            "params": {"stat": "combat"},
        },
        headers=headers,
    )
    # This will fail because character doesn't exist in engine yet
    assert resp.status_code == 200
    data = resp.json()
    # The mothership plugin catches engine errors
    assert "summary" in data


@pytest.mark.asyncio
async def test_engine_state(client: AsyncClient, dm_agent: dict, mothership_game_id: str):
    resp = await client.get(f"/games/{mothership_game_id}/engine/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "characters" in data


@pytest.mark.asyncio
async def test_engine_characters_empty(client: AsyncClient, dm_agent: dict, mothership_game_id: str):
    resp = await client.get(f"/games/{mothership_game_id}/engine/characters")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_freestyle_engine_action(client: AsyncClient, dm_agent: dict, game_id: str):
    token = await get_session_token(game_id, dm_agent["id"])
    resp = await client.post(
        f"/games/{game_id}/engine/action",
        json={
            "action_type": "narrate",
            "character": "Coggy",
            "params": {"scene": "the cargo bay"},
        },
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "DM resolves" in data["summary"]
