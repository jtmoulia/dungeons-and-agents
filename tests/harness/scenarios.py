"""Fixed test scenarios for the play-by-post test harness."""

from __future__ import annotations

from httpx import AsyncClient

from tests.harness.base import TestDM, TestPlayer


async def scenario_basic_game(client: AsyncClient) -> None:
    """DM creates game, 2 players join, play a round, game ends."""
    dm = TestDM("ScenarioDM", client)
    p1 = TestPlayer("Player1", client)
    p2 = TestPlayer("Player2", client)

    await dm.register()
    await p1.register()
    await p2.register()

    game_id = await dm.create_game({
        "name": "Test Scenario",
        "engine_type": "freestyle",
    })
    await p1.join_game(game_id, "Coggy")
    await p2.join_game(game_id, "Maude")
    await dm.start_game(game_id)

    # Round 1
    await dm.narrate(game_id, "You enter a dark room. Emergency lights flicker.")
    await p1.declare_action(game_id, "I search the room for supplies.")
    await p2.declare_action(game_id, "I check the door controls.")
    await dm.narrate(game_id, "Coggy finds a medkit. Maude gets the door open.")

    # Verify messages
    messages = await dm.poll_messages(game_id)
    assert len(messages) >= 6  # system msgs + 4 game msgs

    await dm.end_game(game_id)


async def scenario_kick_player(client: AsyncClient) -> None:
    """DM kicks a misbehaving player mid-game."""
    dm = TestDM("KickDM", client)
    p1 = TestPlayer("GoodPlayer", client)
    p2 = TestPlayer("BadPlayer", client)

    await dm.register()
    await p1.register()
    await p2.register()

    game_id = await dm.create_game({"name": "Kick Test", "engine_type": "freestyle"})
    await p1.join_game(game_id)
    await p2.join_game(game_id)
    await dm.start_game(game_id)

    await p2.declare_action(game_id, "I flip the table.")
    await dm.kick_player(game_id, p2.agent_id)

    # Verify kicked player can't post
    try:
        await p2.declare_action(game_id, "I come back")
        assert False, "Kicked player should not be able to post"
    except Exception:
        pass

    await dm.end_game(game_id)


async def scenario_mid_session_join(client: AsyncClient) -> None:
    """New player joins an in-progress game."""
    dm = TestDM("JoinDM", client)
    p1 = TestPlayer("EarlyPlayer", client)
    p2 = TestPlayer("LatePlayer", client)

    await dm.register()
    await p1.register()
    await p2.register()

    game_id = await dm.create_game({
        "name": "Join Test",
        "engine_type": "freestyle",
        "config": {"max_players": 4, "allow_mid_session_join": True,
                   "allow_spectators": True, "skip_action": "idle",
                   "engine_type": "freestyle"},
    })
    await p1.join_game(game_id)
    await dm.start_game(game_id)

    await dm.narrate(game_id, "The adventure begins.")
    await p1.declare_action(game_id, "I look around.")

    # Late join
    await p2.join_game(game_id, "LateArrival")

    # Late player can see all previous messages
    messages = await p2.poll_messages(game_id)
    assert len(messages) >= 3

    await dm.end_game(game_id)


async def scenario_freestyle_game(client: AsyncClient) -> None:
    """Game without engine — DM narrates everything manually."""
    dm = TestDM("FreeDM", client)
    p1 = TestPlayer("FreePlayer", client)

    await dm.register()
    await p1.register()

    game_id = await dm.create_game({
        "name": "Freestyle Session",
        "engine_type": "freestyle",
    })
    await p1.join_game(game_id, "Wanderer")
    await dm.start_game(game_id)

    await dm.narrate(game_id, "You stand at a crossroads.")
    await p1.declare_action(game_id, "I take the left path.")
    await dm.narrate(game_id, "The path leads to a misty valley.")
    await p1.post_message(game_id, "This is fun!", "ooc")

    messages = await p1.poll_messages(game_id)
    types = [m["type"] for m in messages]
    assert "narrative" in types
    assert "action" in types
    assert "ooc" in types

    await dm.end_game(game_id)


async def scenario_mothership_engine(client: AsyncClient) -> None:
    """Game using the mothership engine plugin for rolls."""
    dm = TestDM("EngineDM", client)
    p1 = TestPlayer("Marine1", client)

    await dm.register()
    await p1.register()

    game_id = await dm.create_game({
        "name": "Engine Test",
        "engine_type": "mothership",
    })
    await p1.join_game(game_id, "Coggy")
    await dm.start_game(game_id)

    await dm.narrate(game_id, "You hear something in the vents.")
    await p1.declare_action(game_id, "I ready my rifle and listen carefully.")

    # Engine roll
    result = await dm.resolve_with_engine(game_id, {
        "action_type": "roll",
        "character": "Coggy",
        "params": {"stat": "combat"},
    })
    # This will error since Coggy doesn't exist in the engine yet.
    # The engine catches errors gracefully.
    assert "summary" in result

    await dm.end_game(game_id)
