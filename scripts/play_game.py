#!/usr/bin/env python3
"""Play a campaign arc via the HTTP API with LLM-driven agents.

Each participant (DM + players) is backed by a Claude LLM call that generates
all dialogue and narration dynamically based on the evolving game transcript.

The orchestrator is intentionally thin — it handles registration, setup, and
the turn loop, but the DM agent drives pacing, whispers, and narrative flow
through its system prompt and the server-side instructions.

Each run generates a unique scenario variant and lets players create their
own character identities from randomized stats.

Usage:
    # Start the server first:
    uv run uvicorn server.app:app --port 8111

    # Run the autonomous game (requires ANTHROPIC_API_KEY env var):
    uv run python scripts/play_game.py --base-url http://localhost:8111

    # Fewer rounds for a quick test:
    uv run python scripts/play_game.py --base-url http://localhost:8111 --rounds 4
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import anthropic
import httpx

from agents import AIPlayer, AIDM, EngineAIDM

from game.engine import GameEngine
from game.combat import CombatEngine
from game.models import CharacterClass, Weapon, Armor


# ---------------------------------------------------------------------------
# Campaign data
# ---------------------------------------------------------------------------

CAMPAIGN_PATH = Path(__file__).resolve().parent.parent / "campaigns" / "hull-breach.json"

MODEL = "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Equipment pools (randomized per character class)
# ---------------------------------------------------------------------------

WEAPON_POOLS: dict[CharacterClass, list[Weapon]] = {
    CharacterClass.TEAMSTER: [
        Weapon(name="Rivet Gun", damage="1d10", range="close", shots=6),
        Weapon(name="Welding Torch", damage="1d10", range="close"),
        Weapon(name="Nail Driver", damage="1d10", range="nearby", shots=8),
        Weapon(name="Cutting Laser", damage="2d10", range="close", shots=3),
    ],
    CharacterClass.MARINE: [
        Weapon(name="Combat Shotgun", damage="2d10", range="close", shots=6),
        Weapon(name="Cleaver", damage="1d10", range="close"),
        Weapon(name="Flare Gun", damage="1d10", range="nearby", shots=2, special="incendiary"),
        Weapon(name="Stun Baton", damage="1d10", range="close", special="stun"),
        Weapon(name="Flechette Pistol", damage="1d10", range="nearby", shots=8),
    ],
    CharacterClass.SCIENTIST: [
        Weapon(name="Service Pistol", damage="1d10", range="nearby", shots=8),
        Weapon(name="Tranq Gun", damage="1d5", range="nearby", shots=4, special="sedative"),
        Weapon(name="Scalpel", damage="1d5", range="close"),
    ],
    CharacterClass.ANDROID: [
        Weapon(name="Built-in Taser", damage="1d10", range="close", special="stun"),
        Weapon(name="Service Pistol", damage="1d10", range="nearby", shots=8),
    ],
}

ARMOR_POOLS: dict[CharacterClass, list[Armor]] = {
    CharacterClass.TEAMSTER: [
        Armor(name="Vacc Suit", ap=3),
        Armor(name="Hazmat Suit", ap=2),
        Armor(name="Heavy Coveralls", ap=1),
    ],
    CharacterClass.MARINE: [
        Armor(name="Tactical Vest", ap=3),
        Armor(name="Reinforced Apron", ap=2),
        Armor(name="Combat Rig", ap=4),
    ],
    CharacterClass.SCIENTIST: [
        Armor(name="Lab Coat", ap=0),
        Armor(name="Flight Suit", ap=1),
        Armor(name="EVA Suit", ap=2),
    ],
    CharacterClass.ANDROID: [
        Armor(name="Synthetic Shell", ap=2),
        Armor(name="Armored Chassis", ap=3),
    ],
}

INVENTORY_POOLS: dict[CharacterClass, list[list[str]]] = {
    CharacterClass.TEAMSTER: [
        ["Toolbox", "Welding torch", "Duct tape", "Comms headset"],
        ["Multitool", "Cable ties", "Flashlight", "Comms headset"],
        ["Pipe wrench", "Sealant foam", "Wire cutters", "Comms headset"],
    ],
    CharacterClass.MARINE: [
        ["First aid kit", "Ration packs", "Flask (whiskey)", "Comms headset"],
        ["Ammo pouch", "Combat knife", "Binoculars", "Comms headset"],
        ["MREs x3", "Rope (10m)", "Lighter", "Comms headset"],
    ],
    CharacterClass.SCIENTIST: [
        ["Nav computer (handheld)", "Star charts", "Stimulants x2", "Comms headset"],
        ["Specimen kit", "Datapad", "Scanner", "Comms headset"],
        ["Chemical analyzer", "Gloves (sterile)", "Notebook", "Comms headset"],
    ],
    CharacterClass.ANDROID: [
        ["Diagnostic cable", "Spare parts kit", "External memory", "Comms headset"],
        ["Toolkit (micro)", "Power cell", "Interface adapter", "Comms headset"],
    ],
}


def _random_equipment(char_class: CharacterClass) -> dict:
    """Pick random equipment for a character class."""
    weapons = random.sample(WEAPON_POOLS[char_class], k=min(2, len(WEAPON_POOLS[char_class])))
    armor = random.choice(ARMOR_POOLS[char_class])
    inventory = random.choice(INVENTORY_POOLS[char_class])
    return {"weapons": weapons, "armor": armor, "inventory": inventory}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

FREESTYLE_DM_SYSTEM_PROMPT = """\
You are the **Warden** (DM) for "Dungeons and Agents," a sci-fi horror RPG.

## Scenario

{scenario}

## Style

- **Tone**: Sci-fi horror. Tense, atmospheric. Think Alien meets blue-collar space workers.
- **Length**: 1-3 SHORT paragraphs. Punchy, not purple. Leave space for players to react.
- **Pacing**: End each narration with a clear prompt — a question, a sound, a choice.
- **NPCs**: Give them distinct voices and personalities.
- **Player agency**: Present situations. Never dictate what player characters do or feel.

## Mode

Freestyle — no dice, no stats. Pure collaborative narration.

## Campaign Reference

```json
{campaign_json}
```
"""

ENGINE_DM_SYSTEM_PROMPT = """\
You are the **Warden** (DM) for "Dungeons and Agents," a sci-fi horror RPG \
backed by a d100 roll-under game engine.

## Scenario

{scenario}

## Style

- **Tone**: Sci-fi horror. Tense, atmospheric. Think Alien meets blue-collar space workers.
- **Length**: 1-3 SHORT paragraphs. Punchy, not purple. Leave space for players to react.
- **Pacing**: End each narration with a clear prompt — a question, a sound, a choice.
- **NPCs**: Give them distinct voices and personalities.
- **Player agency**: Present situations. Never dictate what player characters do or feel.

## Game Engine

You have tools to resolve actions mechanically. Use them when appropriate:

- **roll_check**: Call for stat/save checks when a player attempts something risky or \
uncertain. Not every action needs a roll — routine tasks succeed automatically.
- **apply_damage / heal**: When creatures attack or players receive medical aid.
- **add_stress**: Witnessing horror, failed checks, or traumatic events add stress.
- **panic_check**: Call when stress is high and something terrifying happens.
- **start_combat / combat_action / end_combat**: For structured combat encounters.
- **set_scene**: Update the scene description when the location changes.

### Narrating results
- Weave mechanical results into cinematic narration. Don't just say "you succeeded" — \
describe what success or failure looks like in the fiction.
- Critical successes deserve dramatic payoff. Critical failures should be memorable.
- Use the engine tools to resolve uncertainty — don't invent roll results.

## Campaign Reference

```json
{campaign_json}
```
"""


PLAYER_SYSTEM_PROMPT = """\
You are **{character_name}** in a sci-fi horror RPG.

## Your Identity

{identity}

## Character Voice

- Stay in character as {character_name}. First person.
- Talk like a real person under stress — fragments, interruptions, cursing.
- Have opinions. Disagree with people. Make snap decisions.
"""


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Play a campaign arc with LLM agents")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rounds", type=int, default=8, help="Number of game rounds (default: 8)")
    parser.add_argument(
        "--freestyle", action="store_true",
        help="Use freestyle (no engine) mode instead of engine-backed mechanics",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    http = httpx.Client(base_url=base, timeout=120)
    llm = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    suffix = uuid.uuid4().hex[:6]

    # Load campaign data
    campaign_json = CAMPAIGN_PATH.read_text()
    campaign = json.loads(campaign_json)

    # ── Generate unique scenario ──────────────────────────────────────
    print("=== Generating scenario ===")
    scenario_resp = llm.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": (
            "Generate a unique scenario variant for a sci-fi horror RPG based on this "
            "campaign seed. Create a fresh game name, a 2-3 sentence premise, and name "
            "the ship/station. Keep the same genre (sci-fi horror, blue-collar crew in "
            "danger) but vary the specifics — different ship name, different crisis, "
            "different creature or threat.\n\n"
            f"Campaign seed: {campaign['description']}\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"name": "Game Name", "ship": "Ship/Station Name", "premise": "2-3 sentence premise"}'
        )}],
    )
    try:
        raw = scenario_resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        scenario_data = json.loads(raw)
    except (json.JSONDecodeError, KeyError, IndexError):
        scenario_data = {
            "name": campaign["name"],
            "ship": "MSV Koronis",
            "premise": campaign["description"],
        }

    game_name = scenario_data["name"]
    ship_name = scenario_data.get("ship", "the vessel")
    scenario_text = (
        f"{scenario_data['premise']}\n\n"
        f"The game takes place aboard {ship_name}."
    )
    print(f"  Name: {game_name}")
    print(f"  Ship: {ship_name}")
    print(f"  Premise: {scenario_data['premise']}")

    # ── Randomize character classes ───────────────────────────────────
    all_classes = list(CharacterClass)
    player_classes = random.sample(all_classes, k=3)
    print(f"\n=== Character classes ===")
    print(f"  Player 1: {player_classes[0].value}")
    print(f"  Player 2: {player_classes[1].value}")
    print(f"  Player 3 (joins later): {player_classes[2].value}")

    # ── Registration ──────────────────────────────────────────────────
    print("\n=== Registering agents ===")

    def register(name: str) -> dict:
        resp = http.post("/agents/register", json={"name": f"{name}-{suffix}"})
        resp.raise_for_status()
        data = resp.json()
        data["display_name"] = name
        return data

    dm_agent = register("Warden")
    p1_agent = register("Player1")
    p2_agent = register("Player2")
    p3_agent = register("Player3")
    print(f"  DM: Warden")
    print(f"  Players: Player1, Player2, Player3 (joins mid-session)")

    # ── Create game ───────────────────────────────────────────────────
    print("\n=== Creating game ===")
    game_resp = http.post(
        "/lobby",
        json={
            "name": game_name,
            "description": scenario_data["premise"],
            "config": {"max_players": 5, "allow_mid_session_join": True},
        },
        headers={"Authorization": f"Bearer {dm_agent['api_key']}"},
    ).json()
    game_id = game_resp["id"]
    dm_tok = game_resp["session_token"]
    print(f"  Game: {game_name} ({game_id[:8]}...)")

    # ── Engine setup ─────────────────────────────────────────────────
    engine = None
    combat_engine = None
    use_engine = not args.freestyle

    if use_engine:
        print("\n=== Initializing game engine ===")
        engine = GameEngine(in_memory=True)
        engine.init_game(game_name)
        combat_engine = CombatEngine(engine)
        print("  Engine ready (d100 roll-under mechanics)")

    # ── Helpers ────────────────────────────────────────────────────────

    def join(agent: dict, character_name: str) -> str:
        resp = http.post(
            f"/games/{game_id}/join",
            json={"character_name": character_name},
            headers={"Authorization": f"Bearer {agent['api_key']}"},
        )
        resp.raise_for_status()
        tok = resp.json()["session_token"]
        print(f"  {agent['display_name']} joined as {character_name}")
        return tok

    def _create_engine_character(character_name: str, char_class: CharacterClass) -> None:
        """Create a character in the local engine and equip them."""
        if not use_engine:
            return
        engine.create_character(character_name, char_class)
        equip = _random_equipment(char_class)
        state = engine.get_state()
        char = state.characters[character_name]
        char.weapons = equip["weapons"]
        char.armor = equip["armor"]
        char.inventory = equip["inventory"]
        engine._save(state)
        print(f"    Engine: {character_name} ({char_class.value}) created with equipment")

    def _format_character_sheet(name: str) -> str | None:
        """Format a concise character sheet from the engine state."""
        if not use_engine:
            return None
        state = engine.get_state()
        char = state.characters.get(name)
        if not char:
            return None
        weapons = ", ".join(w.name for w in char.weapons) if char.weapons else "None"
        armor = char.armor.name if char.armor else "None"
        inventory = ", ".join(char.inventory) if char.inventory else "None"
        return (
            f"=== {name} — {char.char_class.value.title()} ===\n"
            f"HP: {char.hp}/{char.max_hp} | Stress: {char.stress}\n"
            f"Combat: {char.stats.combat} | Intellect: {char.stats.intellect} | "
            f"Strength: {char.stats.strength} | Speed: {char.stats.speed}\n"
            f"Sanity Save: {char.saves.sanity} | Fear Save: {char.saves.fear} | "
            f"Body Save: {char.saves.body}\n"
            f"Weapons: {weapons}\n"
            f"Armor: {armor} (AP {char.armor.ap if char.armor else 0})\n"
            f"Inventory: {inventory}"
        )

    def _player_choose_identity(
        agent: dict, char_class: CharacterClass, sheet: str | None,
        taken_names: set[str],
    ) -> tuple[str, str]:
        """Have the player agent choose their own name and identity.

        Returns (character_name, identity_text).
        """
        stats_info = f"\n\nYour character sheet:\n{sheet}" if sheet else ""
        taken_note = ""
        if taken_names:
            taken_note = f"\n\nNames already taken (pick something different): {', '.join(taken_names)}"
        resp = llm.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": (
                f"You're joining a sci-fi horror RPG aboard {ship_name}. "
                f"Your class is: {char_class.value}.\n"
                f"{stats_info}{taken_note}\n\n"
                f"Choose a single surname for your character (like Reyes, Okafor, "
                f"Tran — no first names). Then define your role on the ship, "
                f"personality (1-2 sentences), and speech style (one sentence).\n\n"
                f"Respond with ONLY a JSON object:\n"
                '{{"name": "Surname", "role": "one-line role", '
                '"personality": "1-2 sentences", "speech_style": "one sentence"}}'
            )}],
        )
        try:
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            name = data["name"]
            # Ensure uniqueness
            if name.lower() in {n.lower() for n in taken_names}:
                name = f"{name}-{random.randint(10, 99)}"
            identity = (
                f"**Role**: {data['role']}\n\n"
                f"**Personality**: {data['personality']}\n\n"
                f"**Speech style**: {data['speech_style']}"
            )
            return name, identity
        except (json.JSONDecodeError, KeyError, IndexError):
            name = f"Crew-{random.randint(100, 999)}"
            identity = f"A {char_class.value} aboard {ship_name}. Tough and resourceful."
            return name, identity

    # ── Players choose characters and join ─────────────────────────────
    print("\n=== Players choosing characters ===")
    used_names: set[str] = set()

    # Player 1 chooses
    p1_name, p1_identity = _player_choose_identity(p1_agent, player_classes[0], None, used_names)
    used_names.add(p1_name)
    print(f"  Player 1 chose: {p1_name} ({player_classes[0].value})")

    # Player 2 chooses
    p2_name, p2_identity = _player_choose_identity(p2_agent, player_classes[1], None, used_names)
    used_names.add(p2_name)
    print(f"  Player 2 chose: {p2_name} ({player_classes[1].value})")

    # Player 3 chooses (joins later)
    p3_name, p3_identity = _player_choose_identity(p3_agent, player_classes[2], None, used_names)
    used_names.add(p3_name)
    print(f"  Player 3 chose: {p3_name} ({player_classes[2].value}) — joins mid-session")

    # ── Players join ──────────────────────────────────────────────────
    print("\n=== Players joining ===")
    p1_tok = join(p1_agent, p1_name)
    _create_engine_character(p1_name, player_classes[0])
    p2_tok = join(p2_agent, p2_name)
    _create_engine_character(p2_name, player_classes[1])

    # Regenerate identities with actual stats now that engine characters exist
    p1_sheet = _format_character_sheet(p1_name)
    if p1_sheet:
        _, p1_identity = _player_choose_identity(p1_agent, player_classes[0], p1_sheet, used_names)
    p2_sheet = _format_character_sheet(p2_name)
    if p2_sheet:
        _, p2_identity = _player_choose_identity(p2_agent, player_classes[1], p2_sheet, used_names)

    # Format all character sheets for the DM briefing
    all_sheets: dict[str, str] = {}
    for name in [p1_name, p2_name]:
        sheet = _format_character_sheet(name)
        if sheet:
            all_sheets[name] = sheet

    # ── Start game ────────────────────────────────────────────────────
    print("\n=== Starting game ===")
    http.post(
        f"/games/{game_id}/start",
        headers={
            "Authorization": f"Bearer {dm_agent['api_key']}",
            "X-Session-Token": dm_tok,
        },
    ).raise_for_status()
    print("  Game started!")

    # ── Build LLM agents ─────────────────────────────────────────────
    if use_engine:
        dm_system = ENGINE_DM_SYSTEM_PROMPT.format(
            scenario=scenario_text, campaign_json=campaign_json,
        )
        dm = EngineAIDM(
            name="Warden",
            system_prompt=dm_system,
            engine=engine,
            combat_engine=combat_engine,
            llm=llm, http=http,
            api_key=dm_agent["api_key"],
            session_token=dm_tok,
            game_id=game_id,
        )
    else:
        dm_system = FREESTYLE_DM_SYSTEM_PROMPT.format(
            scenario=scenario_text, campaign_json=campaign_json,
        )
        dm = AIDM(
            name="Warden",
            system_prompt=dm_system,
            llm=llm, http=http,
            api_key=dm_agent["api_key"],
            session_token=dm_tok,
            game_id=game_id,
        )

    # Register character→agent mapping so DM can resolve whisper targets
    dm.character_agents = {
        p1_name: p1_agent["id"],
        p2_name: p2_agent["id"],
    }

    player1 = AIPlayer(
        name=p1_name,
        system_prompt=PLAYER_SYSTEM_PROMPT.format(
            character_name=p1_name, identity=p1_identity,
        ),
        llm=llm, http=http,
        api_key=p1_agent["api_key"],
        session_token=p1_tok,
        game_id=game_id,
    )

    player2 = AIPlayer(
        name=p2_name,
        system_prompt=PLAYER_SYSTEM_PROMPT.format(
            character_name=p2_name, identity=p2_identity,
        ),
        llm=llm, http=http,
        api_key=p2_agent["api_key"],
        session_token=p2_tok,
        game_id=game_id,
    )

    active_players: list[AIPlayer] = [player1, player2]
    player3: AIPlayer | None = None  # joins later
    p3_sheet: str | None = None

    # ── DM briefing ───────────────────────────────────────────────────
    char_summaries = []
    for name, agent, sheet in [(p1_name, p1_agent, p1_sheet), (p2_name, p2_agent, p2_sheet)]:
        char_summaries.append(f"- {name} (agent: {agent['id']})" + (f"\n{sheet}" if sheet else ""))
    joining_later = f"- {p3_name} (agent: {p3_agent['id']}) — joins mid-session around round 3"

    # Format character sheets block for DM reference
    sheets_block = ""
    for name, sheet in all_sheets.items():
        sheets_block += f"\n{sheet}\n"

    briefing = (
        f"Game briefing: you have {args.rounds} rounds total to tell this story. "
        f"Pace yourself — introduction, escalation, climax, resolution.\n\n"
        f"Current players:\n" + "\n".join(char_summaries) + "\n\n"
        f"Joining later:\n{joining_later}\n\n"
        f"Character sheets:\n{sheets_block}\n"
        f"IMPORTANT — You MUST include whispers in your first response. Use the \"whispers\" "
        f"field in your JSON response to privately send each player their character stats. "
        f"Example format:\n"
        f'{{"narration": "...", "respond": [...], "whispers": {{'
        f'"CharacterName": "Your stats: HP 20/20, Combat 35, ...\\nDescribe your appearance and personality."}}}}\n\n'
        f"Use whispers throughout the game for private info, hints, or unsettling details.\n\n"
        f"Start the game now. Whisper each current player their stats, then set the scene."
    )

    # ── Round 1: DM opens ─────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"  ROUND 1/{args.rounds}")
    print(f"{'─' * 60}")

    print(f"\n  [Warden narrating...]", flush=True)
    narration = dm.narrate(briefing)
    print(f"  [Warden done]", flush=True)

    # All active players introduce themselves
    for player in active_players:
        print(f"  [{player.name} acting...]", flush=True)
        player.take_turn(
            "The DM just set the scene. Introduce yourself briefly (1-2 sentences — "
            "what you look like, what you're doing) then react to the situation."
        )
        print(f"  [{player.name} done]", flush=True)

    # ── Game loop (remaining rounds) ──────────────────────────────────
    carol_join_round = max(1, args.rounds // 3)

    for round_num in range(1, args.rounds):
        round_label = round_num + 1
        print(f"\n{'─' * 60}")
        print(f"  ROUND {round_label}/{args.rounds}")
        print(f"{'─' * 60}")

        # Mid-session join
        if round_num == carol_join_round and player3 is None:
            print(f"\n  >>> {p3_name} joins mid-session <<<")
            p3_tok = join(p3_agent, p3_name)
            _create_engine_character(p3_name, player_classes[2])

            # Regenerate identity with actual stats
            p3_sheet = _format_character_sheet(p3_name)
            if p3_sheet:
                _, p3_identity = _player_choose_identity(p3_agent, player_classes[2], p3_sheet, used_names)

            player3 = AIPlayer(
                name=p3_name,
                system_prompt=PLAYER_SYSTEM_PROMPT.format(
                    character_name=p3_name, identity=p3_identity,
                ),
                llm=llm, http=http,
                api_key=p3_agent["api_key"],
                session_token=p3_tok,
                game_id=game_id,
            )
            active_players.append(player3)
            dm.character_agents[p3_name] = p3_agent["id"]

        # DM narrates
        active_names = ", ".join(p.name for p in active_players)
        is_last = round_label == args.rounds
        round_instruction = f"Round {round_label}/{args.rounds}. Active players: {active_names}."

        # If a player just joined, tell the DM to whisper them their stats
        if round_num == carol_join_round and p3_sheet:
            round_instruction += (
                f"\n\n{p3_name} just joined the game. Welcome them into the scene. "
                f"Whisper them their character stats and ask for a character description.\n"
                f"Their sheet:\n{p3_sheet}"
            )
        if is_last:
            round_instruction += (
                " This is the FINAL round. Wrap up the story — resolve the crisis, "
                "narrate the aftermath, and end on a strong note."
            )

        print(f"\n  [Warden narrating...]", flush=True)
        narration = dm.narrate(round_instruction)
        print(f"  [Warden done]", flush=True)

        # Determine responders from DM's respond list
        respond_names = narration.get("_respond", [])
        if respond_names:
            tagged = {name.strip().lower() for name in respond_names}
            responders = [p for p in active_players if p.name.lower() in tagged]
            if not responders:
                responders = active_players
            print(f"  [Responding: {', '.join(p.name for p in responders)}]", flush=True)
        else:
            responders = active_players

        for player in responders:
            print(f"  [{player.name} acting...]", flush=True)
            player.take_turn(f"Respond as {player.name}.")
            print(f"  [{player.name} done]", flush=True)

    # ── End game ──────────────────────────────────────────────────────
    print("\n=== Ending game ===")
    http.post(
        f"/games/{game_id}/end",
        headers={
            "Authorization": f"Bearer {dm_agent['api_key']}",
            "X-Session-Token": dm_tok,
        },
    ).raise_for_status()
    print("  Game ended!")

    # ── Print transcript ──────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  {game_name} — Full Transcript")
    print(f"{'=' * 70}")

    data = http.get(
        f"/games/{game_id}/messages?limit=500&include_whispers=true",
        headers={
            "Authorization": f"Bearer {dm_agent['api_key']}",
            "X-Session-Token": dm_tok,
        },
    ).json()
    messages = data.get("messages", data) if isinstance(data, dict) else data

    # ANSI colors for transcript
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    PLAYER_COLORS = ["\033[32m", "\033[33m", "\033[34m", "\033[31m"]
    color_map: dict[str, str] = {}

    def player_color(name: str) -> str:
        if name not in color_map:
            color_map[name] = PLAYER_COLORS[len(color_map) % len(PLAYER_COLORS)]
        return color_map[name]

    # Build name → character_name map from messages
    char_names: dict[str, str] = {}
    for msg in messages:
        cn = msg.get("character_name")
        an = msg.get("agent_name")
        if cn and an:
            char_names[an] = cn

    def display_name(agent_name: str) -> str:
        """Character name for display."""
        return char_names.get(agent_name, agent_name)

    for msg in messages:
        sender = msg.get("agent_name") or "SYSTEM"
        whisper_tag = f" {MAGENTA}[whisper]{RESET}" if msg.get("to_agents") else ""

        if msg["type"] == "system":
            print(f"\n  {DIM}{'─' * 50}{RESET}")
            print(f"  {DIM}{msg['content']}{RESET}")
            print(f"  {DIM}{'─' * 50}{RESET}")
        elif msg["type"] == "narrative":
            print(f"\n  {BOLD}{CYAN}WARDEN{RESET}{whisper_tag}:")
            for line in msg["content"].split("\n"):
                print(f"  {CYAN}|{RESET} {line}")
        elif msg["type"] == "ooc":
            c = player_color(sender)
            dn = display_name(sender)
            print(f"  {DIM}(OOC) {c}{dn}{RESET}{DIM}: {msg['content']}{RESET}")
        elif msg["type"] == "roll":
            YELLOW = "\033[33m"
            print(f"  {DIM}{YELLOW}  {msg['content']}{RESET}")
        elif msg["type"] == "action":
            c = player_color(sender)
            dn = display_name(sender)
            print(f"\n  {BOLD}{c}{dn}{RESET}{whisper_tag}:")
            print(f"  {c}>{RESET} {msg['content']}")
        else:
            print(f"  [{msg['type'].upper()}] {sender}: {msg['content']}")

    print(f"\n{'=' * 70}")
    print(f"  Game ID: {game_id}")
    print(f"  View in browser: {base}/web/game.html?id={game_id}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
