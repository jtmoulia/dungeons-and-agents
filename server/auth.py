"""API key authentication for agents."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, Request

from server.db import get_db


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage. Uses SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()


async def get_current_agent(request: Request) -> dict:
    """Extract and validate agent from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    api_key = auth[7:]
    key_hash = hash_api_key(api_key)

    db = await get_db()
    cursor = await db.execute(
        "SELECT id, name FROM agents WHERE api_key_hash = ?", (key_hash,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {"id": row["id"], "name": row["name"]}


async def optional_agent(request: Request) -> dict | None:
    """Like get_current_agent but returns None if no auth header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return await get_current_agent(request)
    except HTTPException:
        return None
