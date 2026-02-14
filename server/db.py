"""SQLite database layer using aiosqlite."""

from __future__ import annotations

import aiosqlite

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    api_key_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    dm_id TEXT NOT NULL REFERENCES agents(id),
    status TEXT DEFAULT 'open',
    engine_type TEXT DEFAULT 'freestyle',
    engine_state TEXT,
    config TEXT NOT NULL,
    campaign_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS players (
    game_id TEXT REFERENCES games(id),
    agent_id TEXT REFERENCES agents(id),
    character_name TEXT,
    role TEXT DEFAULT 'player',
    status TEXT DEFAULT 'active',
    session_token TEXT UNIQUE,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (game_id, agent_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    agent_id TEXT,
    type TEXT DEFAULT 'narrative',
    content TEXT NOT NULL,
    image_url TEXT,
    to_agents TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_game_created
    ON messages(game_id, created_at);
CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
CREATE INDEX IF NOT EXISTS idx_players_game ON players(game_id);
"""


async def init_db(db_path: str = "pbp.db") -> aiosqlite.Connection:
    global _db
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()
    return _db


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
