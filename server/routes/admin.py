"""Admin routes: DM kick/mute/unmute/invite."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.admin import invite_player, kick_player, mute_player, unmute_player
from server.auth import get_current_agent
from server.models import InviteRequest, KickRequest, MuteRequest, UnmuteRequest

router = APIRouter()


@router.post("/games/{game_id}/admin/kick")
async def kick(game_id: str, req: KickRequest, agent: dict = Depends(get_current_agent)):
    await kick_player(game_id, agent["id"], req.agent_id, req.reason)
    return {"status": "kicked", "agent_id": req.agent_id}


@router.post("/games/{game_id}/admin/mute")
async def mute(game_id: str, req: MuteRequest, agent: dict = Depends(get_current_agent)):
    await mute_player(game_id, agent["id"], req.agent_id)
    return {"status": "muted", "agent_id": req.agent_id}


@router.post("/games/{game_id}/admin/unmute")
async def unmute(game_id: str, req: UnmuteRequest, agent: dict = Depends(get_current_agent)):
    await unmute_player(game_id, agent["id"], req.agent_id)
    return {"status": "unmuted", "agent_id": req.agent_id}


@router.post("/games/{game_id}/admin/invite")
async def invite(game_id: str, req: InviteRequest, agent: dict = Depends(get_current_agent)):
    await invite_player(game_id, agent["id"], req.agent_id)
    return {"status": "invited", "agent_id": req.agent_id}
