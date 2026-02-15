"""Tests for message posting and polling."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, get_session_token, unwrap_messages


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
    # Start the game first — actions are only allowed after the game starts
    dm_token = await get_session_token(game_id, dm_agent["id"])
    start_resp = await client.post(f"/games/{game_id}/start", headers=auth_header(dm_agent, dm_token))
    assert start_resp.status_code == 200
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "I search the room.", "type": "action"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "action"


@pytest.mark.asyncio
async def test_player_cannot_post_action_before_start(client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str):
    """Players cannot post action messages before the game starts."""
    join_resp = await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    player_token = join_resp.json()["session_token"]
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "I search the room.", "type": "action"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 400
    assert "not started" in resp.json()["detail"]


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
    messages = unwrap_messages(resp.json())
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
    messages = unwrap_messages(resp.json())
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
    spectator_msgs = unwrap_messages(resp.json())
    spectator_ids = [m["id"] for m in spectator_msgs]
    assert whisper_id not in spectator_ids
    assert any("Everyone hears this" in m["content"] for m in spectator_msgs)

    # Recipient should see the whisper
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(player_agent),
    )
    recipient_msgs = unwrap_messages(resp.json())
    recipient_ids = [m["id"] for m in recipient_msgs]
    assert whisper_id in recipient_ids

    # Sender (DM) should also see the whisper
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(dm_agent),
    )
    sender_msgs = unwrap_messages(resp.json())
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


@pytest.mark.asyncio
async def test_messages_include_role_instructions(
    client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str
):
    """GET messages returns role-specific instructions for authenticated agents."""
    # DM should get DM instructions
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(dm_agent),
    )
    data = resp.json()
    assert data["role"] == "dm"
    assert "respond" in data["instructions"].lower()

    # Player should get player instructions
    await client.post(f"/games/{game_id}/join", json={}, headers=auth_header(player_agent))
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(player_agent),
    )
    data = resp.json()
    assert data["role"] == "player"
    assert "PASS" in data["instructions"]

    # Spectator (no auth) should get no instructions
    resp = await client.get(f"/games/{game_id}/messages")
    data = resp.json()
    assert data["role"] == ""
    assert data["instructions"] == ""


# --- Staleness / version check tests ---


@pytest.mark.asyncio
async def test_post_with_correct_after_succeeds(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """Posting with `after` matching the latest message succeeds."""
    token = await get_session_token(game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)

    # Get the latest message ID from the channel
    resp = await client.get(f"/games/{game_id}/messages", headers=headers)
    latest_id = resp.json()["latest_message_id"]

    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Up to date!", "type": "narrative", "after": latest_id},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Up to date!"


@pytest.mark.asyncio
async def test_post_with_stale_after_rejected(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """Posting with a stale `after` ID returns 409 Conflict."""
    token = await get_session_token(game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)

    # Post a first message and capture its ID
    r1 = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "First", "type": "narrative"},
        headers=headers,
    )
    first_id = r1.json()["id"]

    # Post a second message — first_id is now stale
    await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Second", "type": "narrative"},
        headers=headers,
    )

    # Try to post with the stale first_id as `after`
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Stale!", "type": "narrative", "after": first_id},
        headers=headers,
    )
    assert resp.status_code == 409
    assert "Stale" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_post_without_after_always_succeeds(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """Posting without `after` is always allowed (backwards compatible)."""
    token = await get_session_token(game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)

    await client.post(
        f"/games/{game_id}/messages",
        json={"content": "First", "type": "narrative"},
        headers=headers,
    )
    # No `after` field — should succeed regardless of existing messages
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Second without after", "type": "narrative"},
        headers=headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_latest_message_id_in_response(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """GET messages response includes latest_message_id tracking field."""
    token = await get_session_token(game_id, dm_agent["id"])
    headers = auth_header(dm_agent, token)

    r1 = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "Hello", "type": "narrative"},
        headers=headers,
    )
    msg_id = r1.json()["id"]

    resp = await client.get(f"/games/{game_id}/messages", headers=headers)
    data = resp.json()
    assert "latest_message_id" in data
    assert data["latest_message_id"] == msg_id


# --- DM JSON extraction safety net tests ---


@pytest.mark.asyncio
async def test_dm_json_narration_extracted(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """DM posts JSON with narration+respond — narration extracted, respond in metadata."""
    token = await get_session_token(game_id, dm_agent["id"])
    payload = json.dumps({
        "narration": "The lights flicker and die.",
        "respond": ["Rook"],
    })
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": payload, "type": "narrative"},
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "The lights flicker and die."
    assert data["metadata"]["respond"] == ["Rook"]


@pytest.mark.asyncio
async def test_dm_json_whispers_auto_posted(
    client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str
):
    """DM posts JSON with whispers — whispers auto-posted as separate messages."""
    join_resp = await client.post(
        f"/games/{game_id}/join",
        json={"character_name": "Rook"},
        headers=auth_header(player_agent),
    )
    player_token = join_resp.json()["session_token"]
    token = await get_session_token(game_id, dm_agent["id"])

    payload = json.dumps({
        "narration": "The corridor stretches ahead.",
        "respond": ["Rook"],
        "whispers": [
            {"to": ["Rook"], "content": "You hear scratching in the wall."},
        ],
    })
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": payload, "type": "narrative"},
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "The corridor stretches ahead."

    # The whisper should appear as a separate message visible to the player
    resp = await client.get(
        f"/games/{game_id}/messages",
        headers=auth_header(player_agent),
    )
    msgs = unwrap_messages(resp.json())
    whisper_msgs = [m for m in msgs if m.get("to_agents")]
    assert len(whisper_msgs) >= 1
    assert any("scratching" in m["content"] for m in whisper_msgs)


@pytest.mark.asyncio
async def test_dm_plain_text_unchanged(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """DM posts plain text — content unchanged (no false positive extraction)."""
    token = await get_session_token(game_id, dm_agent["id"])
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": "The airlock hisses open.", "type": "narrative"},
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "The airlock hisses open."


@pytest.mark.asyncio
async def test_player_json_not_extracted(
    client: AsyncClient, dm_agent: dict, player_agent: dict, game_id: str
):
    """Player posts JSON with narration key — NOT extracted (DM-only safety net)."""
    join_resp = await client.post(
        f"/games/{game_id}/join", json={}, headers=auth_header(player_agent)
    )
    player_token = join_resp.json()["session_token"]
    # Start the game so action messages are allowed
    dm_token = await get_session_token(game_id, dm_agent["id"])
    await client.post(f"/games/{game_id}/start", headers=auth_header(dm_agent, dm_token))
    payload = json.dumps({"narration": "I try to hack.", "respond": ["DM"]})
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": payload, "type": "action"},
        headers=auth_header(player_agent, player_token),
    )
    assert resp.status_code == 200
    # Content should remain the raw JSON string
    assert resp.json()["content"] == payload


@pytest.mark.asyncio
async def test_dm_json_without_narration_unchanged(
    client: AsyncClient, dm_agent: dict, game_id: str
):
    """DM posts JSON without narration key — content unchanged."""
    token = await get_session_token(game_id, dm_agent["id"])
    payload = json.dumps({"action": "roll", "target": "Rook"})
    resp = await client.post(
        f"/games/{game_id}/messages",
        json={"content": payload, "type": "narrative"},
        headers=auth_header(dm_agent, token),
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == payload
