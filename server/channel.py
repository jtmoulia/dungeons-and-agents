"""Message channel logic for play-by-post games."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from server.db import get_db

logger = logging.getLogger(__name__)


def _row_to_msg(r) -> dict:
    """Convert a message row to a dict."""
    msg_type = r["type"]
    return {
        "id": r["id"],
        "game_id": r["game_id"],
        "agent_id": r["agent_id"],
        "agent_name": r["agent_name"],
        "type": msg_type,
        "content": r["content"],
        "image_url": r["image_url"],
        "to_agents": json.loads(r["to_agents"]) if r["to_agents"] else None,
        "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
        "created_at": r["created_at"],
        "content_type": "system" if msg_type in ("system", "roll") else "user_generated",
    }


def _append_log(game_id: str, msg: dict) -> None:
    """Append a message to the game's JSONL log file (best-effort)."""
    from server.config import settings

    log_dir = Path(settings.log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{game_id}.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(msg, default=str) + "\n")
    except OSError:
        logger.warning("Failed to append to log file for game %s", game_id, exc_info=True)


async def post_message(
    game_id: str,
    agent_id: str | None,
    content: str,
    msg_type: str = "narrative",
    metadata: dict | None = None,
    image_url: str | None = None,
    to_agents: list[str] | None = None,
) -> dict:
    """Post a message to a game's channel."""
    db = await get_db()
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        """INSERT INTO messages (id, game_id, agent_id, type, content, image_url, to_agents, metadata, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, game_id, agent_id, msg_type, content, image_url,
         json.dumps(to_agents) if to_agents else None,
         json.dumps(metadata) if metadata else None, now),
    )
    await db.commit()

    # Fetch agent name if available
    agent_name = None
    if agent_id:
        cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (agent_id,))
        row = await cursor.fetchone()
        if row:
            agent_name = row["name"]

    msg = {
        "id": msg_id,
        "game_id": game_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "type": msg_type,
        "content": content,
        "image_url": image_url,
        "to_agents": to_agents,
        "metadata": metadata,
        "created_at": now,
        "content_type": "system" if msg_type in ("system", "roll") else "user_generated",
    }
    _append_log(game_id, msg)
    return msg


async def get_messages(
    game_id: str,
    after: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get messages from a game's channel, optionally after a given message."""
    db = await get_db()

    if after:
        cursor = await db.execute(
            "SELECT created_at FROM messages WHERE id = ? AND game_id = ?",
            (after, game_id),
        )
        row = await cursor.fetchone()
        if row:
            cursor = await db.execute(
                """SELECT m.*, a.name as agent_name
                   FROM messages m
                   LEFT JOIN agents a ON m.agent_id = a.id
                   WHERE m.game_id = ? AND m.created_at > ?
                   ORDER BY m.created_at ASC
                   LIMIT ?""",
                (game_id, row["created_at"], limit),
            )
        else:
            return []
    else:
        cursor = await db.execute(
            """SELECT m.*, a.name as agent_name
               FROM messages m
               LEFT JOIN agents a ON m.agent_id = a.id
               WHERE m.game_id = ?
               ORDER BY m.created_at ASC
               LIMIT ?""",
            (game_id, limit),
        )

    rows = await cursor.fetchall()
    return [_row_to_msg(r) for r in rows]


async def get_message(game_id: str, msg_id: str) -> dict | None:
    """Get a single message by ID."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT m.*, a.name as agent_name
           FROM messages m
           LEFT JOIN agents a ON m.agent_id = a.id
           WHERE m.id = ? AND m.game_id = ?""",
        (msg_id, game_id),
    )
    r = await cursor.fetchone()
    if not r:
        return None
    return _row_to_msg(r)
