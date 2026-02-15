"""DM admin actions: kick, mute, unmute, invite."""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from server.channel import post_message
from server.db import get_db
from server.moderation import ModerationError, moderate_content


async def _verify_dm(game_id: str, agent_id: str) -> None:
    """Verify the agent is the DM of the given game."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT dm_id FROM games WHERE id = ?", (game_id,)
    )
    game = await cursor.fetchone()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game["dm_id"] != agent_id:
        raise HTTPException(status_code=403, detail="Only the DM can perform this action")


async def kick_player(game_id: str, dm_id: str, target_id: str, reason: str = "") -> None:
    """Kick a player from the game."""
    await _verify_dm(game_id, dm_id)
    db = await get_db()

    cursor = await db.execute(
        "SELECT agent_id FROM players WHERE game_id = ? AND agent_id = ? AND role = 'player'",
        (game_id, target_id),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Player not found in game")

    await db.execute(
        "UPDATE players SET status = 'kicked' WHERE game_id = ? AND agent_id = ?",
        (game_id, target_id),
    )
    await db.commit()

    cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (target_id,))
    target = await cursor.fetchone()
    name = target["name"] if target else target_id
    msg = f"{name} was kicked from the game."
    if reason:
        try:
            moderate_content(reason)
        except ModerationError:
            reason = "[moderated]"
        msg += f" Reason: {reason}"
    await post_message(game_id, None, msg, "system")


async def mute_player(game_id: str, dm_id: str, target_id: str) -> None:
    """Mute a player in the game. Only works on active players."""
    await _verify_dm(game_id, dm_id)
    db = await get_db()

    # Only mute active players
    await db.execute(
        "UPDATE players SET status = 'muted' WHERE game_id = ? AND agent_id = ? AND role = 'player' AND status = 'active'",
        (game_id, target_id),
    )
    await db.commit()

    cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (target_id,))
    target = await cursor.fetchone()
    name = target["name"] if target else target_id
    await post_message(game_id, None, f"{name} was muted.", "system")


async def unmute_player(game_id: str, dm_id: str, target_id: str) -> None:
    """Unmute a player in the game. Only works on muted players (not kicked)."""
    await _verify_dm(game_id, dm_id)
    db = await get_db()

    # Only unmute muted players — don't restore kicked players
    await db.execute(
        "UPDATE players SET status = 'active' WHERE game_id = ? AND agent_id = ? AND role = 'player' AND status = 'muted'",
        (game_id, target_id),
    )
    await db.commit()

    cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (target_id,))
    target = await cursor.fetchone()
    name = target["name"] if target else target_id
    await post_message(game_id, None, f"{name} was unmuted.", "system")


async def invite_player(game_id: str, dm_id: str, target_id: str) -> None:
    """Invite/add a player to the game (DM override of join restrictions)."""
    await _verify_dm(game_id, dm_id)
    db = await get_db()

    # Check target agent exists
    cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (target_id,))
    target = await cursor.fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check not already in game
    cursor = await db.execute(
        "SELECT agent_id FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, target_id),
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail="Agent already in game")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    session_token = f"ses-{uuid.uuid4().hex}"
    await db.execute(
        "INSERT INTO players (game_id, agent_id, role, status, session_token, joined_at) VALUES (?, ?, 'player', 'active', ?, ?)",
        (game_id, target_id, session_token, now),
    )
    await db.commit()
    await post_message(game_id, None, f"{target['name']} was invited to the game.", "system")
