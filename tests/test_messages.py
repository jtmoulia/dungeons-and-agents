"""Tests for message posting and polling."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, get_session_token


@pytest.mark.asyncio
async def test_post_message(client: AsyncClient, dm_agent: dict, game_id: str):
    token = await get_session_token(game_id, dm_agent["id"])
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "The airlock hisses open.", "type": "narrative"},
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "The airlock hisses open."
    assert data["type"] == "narrative"
    assert data["agent_name"] == "TestDM"


@pytest.mark.asyncio
async def test_post_message_not_in_game(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Hello", "type": "action"},
        headers=auth_header(player_agent),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_message_missing_session_token(client: AsyncClient, dm_agent: dict, game_id: str):
    """Session token is mandatory for posting messages."""
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "No token", "type": "narrative"},
        headers=auth_header(dm_agent),  # no session token
    )
    assert resp.status_code == 403
    assert "Session-Token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_player_cannot_post_narrative(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    # Join game first
    join_resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    player_token = join_resp.json()["session_token"]
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "I narrate.", "type": "narrative"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_player_can_post_action(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    join_resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    player_token = join_resp.json()["session_token"]
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "I search the room.", "type": "action"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "action"


@pytest.mark.asyncio
async def test_get_messages(client: AsyncClient, dm_agent: dict, game_id: str):
    token = await get_session_token(game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)
    await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Message 1", "type": "narrative"},
        headers=headers,
    )
    await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Message 2", "type": "narrative"},
        headers=headers,
    )

    resp = await client.get(f"/games/{game_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    # System message from game creation + 2 posted messages
    assert len(messages) >= 2


@pytest.mark.asyncio
async def test_poll_messages_after(client: AsyncClient, dm_agent: dict, game_id: str):
    token = await get_session_token(game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)
    r1 = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "First", "type": "narrative"},
        headers=headers,
    )
    first_id = r1.json()["id"]

    await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Second", "type": "narrative"},
        headers=headers,
    )

    resp = await client.get(f"/games/{game_id}/messages?after={first_id}")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 1
    assert messages[0]["content"] == "Second"


@pytest.mark.asyncio
async def test_get_single_message(client: AsyncClient, dm_agent: dict, game_id: str):
    token = await get_session_token(game_id, dm_agent["id"])
    r = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Test msg", "type": "narrative"},
        headers=auth_header(dm_agent, token),
    )
    msg_id = r.json()["id"]
    resp = await client.get(f"/games/{game_id}/messages/{msg_id}")
    assert resp.status_code == 200
    assert resp.json()["content"] == "Test msg"


@pytest.mark.asyncio
async def test_message_not_found(client: AsyncClient, dm_agent: dict, game_id: str):
    resp = await client.get(f"/games/{game_id}/messages/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ooc_message(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    join_resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    player_token = join_resp.json()["session_token"]
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "brb grabbing coffee", "type": "ooc"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "ooc"


@pytest.mark.asyncio
async def test_whisper_hidden_from_spectators(
    client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str
):
    """Whispered messages (to_agents set) should be hidden from unauthenticated spectators."""
    join_resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    player_token = join_resp.json()["session_token"]
    dm_token = await get_session_token(game_id, dm_agent["id"])

    # DM whispers to the player
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={
            "content": "Secret info for you only",
            "type": "narrative",
            "to_agents": [player_agent["id"]],
        },
        headers=auth_header(dm_agent, dm_token),
    )
    assert resp.status_code == 200
    whisper_id = resp.json()["id"]

    # DM posts a public message
    await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Everyone hears this", "type": "narrative"},
        headers=auth_header(dm_agent, dm_token),
    )

    # Spectator (no auth) should not see the whisper
    resp = await client.get(f"/games/{game_id}/messages")
    spectator_msgs = resp.json()
    spectator_ids = [m["id"] for m in spectator_msgs]
    assert whisper_id not in spectator_ids
    assert any("Everyone hears this" in m["content"] for m in spectator_msgs)

    # Recipient should see the whisper
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(player_agent),
    )
    recipient_msgs = resp.json()
    recipient_ids = [m["id"] for m in recipient_msgs]
    assert whisper_id in recipient_ids

    # Sender (DM) should also see the whisper
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(dm_agent),
    )
    sender_msgs = resp.json()
    sender_ids = [m["id"] for m in sender_msgs]
    assert whisper_id in sender_ids

    # Single message endpoint: spectator should get 404
    resp = await client.get(f"/games/{game_id}/messages/{whisper_id}")
    assert resp.status_code == 404

    # Single message endpoint: recipient should see it
    resp = await client.get(
        f"/games/{game_id}/messages/{whisper_id}",
        headers=auth_header(player_agent),
    )
    assert resp.status_code == 200
