"""Engine action routes: interact with game engine plugins."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from server.auth import get_current_agent
from server.channel import post_message
from server.db import get_db
from server.engine.base import EngineAction, GameEnginePlugin
from server.engine.freestyle import FreestylePlugin
from server.engine.mothership import MothershipPlugin
from server.models import EngineActionRequest, EngineActionResponse, MessageResponse

router = APIRouter()


def _create_plugin(engine_type: str) -> GameEnginePlugin:
    """Create a fresh engine plugin instance."""
    if engine_type == "mothership":
        return MothershipPlugin()
    return FreestylePlugin()


async def _load_engine(game_id: str) -> tuple[dict, GameEnginePlugin]:
    """Load game and its engine plugin with state."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = await cursor.fetchone()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    game_dict = dict(game)
    plugin = _create_plugin(game_dict["engine_type"])
    if game_dict["engine_state"]:
        plugin.load_state(game_dict["engine_state"])
    return game_dict, plugin


async def _save_engine(game_id: str, plugin: GameEnginePlugin) -> None:
    """Save engine state back to the database."""
    db = await get_db()
    state = plugin.save_state()
    await db.execute("UPDATE games SET engine_state = ? WHERE id = ?", (state, game_id))
    await db.commit()


@router.get("/games/{game_id}/engine/state")
async def get_engine_state(game_id: str):
    _, plugin = await _load_engine(game_id)
    return plugin.get_state()


@router.post("/games/{game_id}/engine/action", response_model=EngineActionResponse)
async def engine_action(
    game_id: str,
    req: EngineActionRequest,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    db = await get_db()

    # Verify agent is in game
    cursor = await db.execute(
        "SELECT role, status FROM players WHERE game_id = ? AND agent_id = ?",
        (game_id, agent["id"]),
    )
    player = await cursor.fetchone()
    if not player:
        raise HTTPException(status_code=403, detail="Not a participant in this game")
    if player["status"] != "active":
        raise HTTPException(status_code=403, detail=f"Player status: {player['status']}")

    # Validate session token
    from server.routes.messages import _validate_session_token
    await _validate_session_token(request, game_id, agent["id"])

    # DM-only engine actions
    dm_only_actions = {"damage", "start_combat", "end_combat"}
    if req.action_type in dm_only_actions and player["role"] != "dm":
        raise HTTPException(
            status_code=403,
            detail=f"Only the DM can perform '{req.action_type}' engine actions",
        )

    game_dict, plugin = await _load_engine(game_id)
    action = EngineAction(
        action_type=req.action_type,
        character=req.character,
        params=req.params,
    )
    result = plugin.process_action(action)

    if result.state_changed:
        await _save_engine(game_id, plugin)

    # Post the result as a roll message
    msg = await post_message(
        game_id, agent["id"], result.summary, "roll",
        metadata={"engine_result": result.details, "action": req.model_dump()},
    )

    return EngineActionResponse(
        success=result.success,
        summary=result.summary,
        details=result.details,
        message=MessageResponse(**msg),
    )


@router.get("/games/{game_id}/engine/characters")
async def list_engine_characters(game_id: str):
    _, plugin = await _load_engine(game_id)
    return plugin.list_characters()


@router.get("/games/{game_id}/engine/characters/{name}")
async def get_engine_character(game_id: str, name: str):
    _, plugin = await _load_engine(game_id)
    char = plugin.get_character(name)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found in engine")
    return char
