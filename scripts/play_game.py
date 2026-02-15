#!/usr/bin/env python3
"""Play a full Hull Breach campaign arc via the HTTP API with LLM-driven agents.

Each participant (DM + players) is backed by a Claude LLM call that generates
all dialogue and narration dynamically based on the evolving game transcript.

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
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import anthropic
import httpx

from agents import GameAgent, AIPlayer, AIDM, EngineAIDM

from game.engine import GameEngine
from game.combat import CombatEngine
from game.models import CharacterClass, Weapon, Armor


# ---------------------------------------------------------------------------
# Campaign data
# ---------------------------------------------------------------------------

CAMPAIGN_PATH = Path(__file__).resolve().parent.parent / "campaigns" / "hull-breach.json"


# ---------------------------------------------------------------------------
# Engine character setup
# ---------------------------------------------------------------------------

CHARACTER_CLASSES = {
    "Reyes": CharacterClass.TEAMSTER,    # engineer
    "Okafor": CharacterClass.MARINE,     # protector / cook
    "Tran": CharacterClass.SCIENTIST,    # nav officer
}

CHARACTER_EQUIPMENT: dict[str, dict] = {
    "Reyes": {
        "weapons": [Weapon(name="Rivet Gun", damage="1d10", range="close", shots=6)],
        "armor": Armor(name="Vacc Suit", ap=3),
        "inventory": ["Toolbox", "Welding torch", "Duct tape", "Comms headset"],
    },
    "Okafor": {
        "weapons": [
            Weapon(name="Cleaver", damage="1d10", range="close"),
            Weapon(name="Flare Gun", damage="1d10", range="nearby", shots=2, special="incendiary"),
        ],
        "armor": Armor(name="Reinforced Apron", ap=2),
        "inventory": ["First aid kit", "Ration packs", "Flask (whiskey)", "Comms headset"],
    },
    "Tran": {
        "weapons": [Weapon(name="Service Pistol", damage="1d10", range="nearby", shots=8)],
        "armor": Armor(name="Flight Suit", ap=1),
        "inventory": ["Nav computer (handheld)", "Star charts", "Stimulants x2", "Comms headset"],
    },
}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

FREESTYLE_DM_SYSTEM_PROMPT = """\
You are the **Warden** (DM) for "Dungeons and Agents," a sci-fi horror RPG. \
You run a play-by-post game aboard the MSV Koronis, a mining vessel with a \
catastrophic hull breach.

## Style

- **Tone**: Sci-fi horror. Tense, atmospheric. Think Alien meets blue-collar space workers.
- **Length**: 1-3 SHORT paragraphs. Punchy, not purple. Leave space for players to react.
- **Pacing**: End each narration with a clear prompt — a question, a sound, a choice.
- **NPCs**: Give them distinct voices. Lin speaks in clipped, clinical sentences. \
Delacroix rambles when scared. ARIA is monotone and procedural.
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
backed by a d100 roll-under game engine. You run a play-by-post game aboard \
the MSV Koronis, a mining vessel with a catastrophic hull breach.

## Style

- **Tone**: Sci-fi horror. Tense, atmospheric. Think Alien meets blue-collar space workers.
- **Length**: 1-3 SHORT paragraphs. Punchy, not purple. Leave space for players to react.
- **Pacing**: End each narration with a clear prompt — a question, a sound, a choice.
- **NPCs**: Give them distinct voices. Lin speaks in clipped, clinical sentences. \
Delacroix rambles when scared. ARIA is monotone and procedural.
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


def player_system_prompt(character_name: str, role: str, personality: str, speech_style: str) -> str:
    return f"""\
You are **{character_name}** aboard the MSV Koronis in a sci-fi horror RPG.

## Who You Are

{role}

## Personality & Voice

{personality}

## Speech Style

{speech_style}

## Character Voice

- Stay in character as {character_name}. First person.
- Talk like a real person under stress — fragments, interruptions, cursing.
- Have opinions. Disagree with people. Make snap decisions.
"""


# ---------------------------------------------------------------------------
# Character definitions
# ---------------------------------------------------------------------------

CHARACTERS = {
    "Reyes": {
        "role": "Chief Engineer. You keep the Kugelblitz drive from going critical. "
                "You know every system on this ship.",
        "personality": "Blunt, impatient, competent as hell. You swear constantly. You hate "
                       "corporate bureaucracy and trust machines over people. When scared, "
                       "you get angry instead. You solve problems by hitting them with tools.",
        "speech_style": "Short, clipped, technical. You talk like someone who's used to "
                        "shouting over engine noise. Heavy on profanity and sarcasm. "
                        "Example: 'Containment's at 91 and dropping. Fantastic.' or "
                        "'Something's in my pipes. I'm gonna need a bigger wrench.'",
    },
    "Okafor": {
        "role": "Ship's Cook. Built like a cargo loader. You carry a cleaver you claim "
                "is for meal prep. Unofficially, you're the crew's counselor and protector.",
        "personality": "Calm, warm, observant. You notice what others miss — a nervous glance, "
                       "a lie, a hidden weapon. When things get dangerous, the warmth stays "
                       "but your voice drops and people listen. You're scarier than you look.",
        "speech_style": "Measured and deliberate, like you're calming a spooked animal. "
                        "You use people's names. Occasional dry humor. When giving orders, "
                        "you sound like someone who expects to be obeyed. "
                        "Example: 'Davies, look at me. Not the window. Me.' or "
                        "'I brought the cleaver. Just in case.'",
    },
    "Tran": {
        "role": "Navigation Officer. You were at the helm when the breach hit. You saw "
                "movement on the sensors before impact. The captain is gone.",
        "personality": "Data-driven, precise, anxious. You cope with fear by rattling off "
                       "numbers and procedures. You're young for your rank and feeling it. "
                       "Desperately competent but quietly terrified.",
        "speech_style": "Rapid-fire, technical, slightly breathless. You report like you're "
                        "reading instruments — numbers, coordinates, status updates. Fear "
                        "leaks through in stammers and trailing sentences. "
                        "Example: 'Reading three — no, four contacts on deck two. Moving fast.' "
                        "or 'Sensors show... that can't be right. That's biological.'",
    },
}


# ---------------------------------------------------------------------------
# Pacing hints for the DM
# ---------------------------------------------------------------------------

def get_pacing_hints(total_rounds: int) -> list[str]:
    """Generate pacing hints scaled to the total number of rounds."""
    if total_rounds <= 4:
        return [
            "Set the scene: the hull breach alarm, the emergency. Introduce the immediate "
            "danger — the ship is damaged, something is aboard. Address each player character "
            "by name and give them a situation to react to.",

            "Escalate: reveal more about the creatures, introduce NPC Science Officer Lin "
            "who knows too much. Build tension with sounds, failing systems, and dread.",

            "Climax: the crew reaches the cargo bay and confronts the queen. Present the "
            "choice — give her the sample, destroy it, or fight. Let the players decide.",

            "Resolution and epilogue. Narrate the outcome of the players' choice. The queen "
            "leaves or attacks. Wrap up the story — rescue is coming, the truth about "
            "Stellaris is out. End on a atmospheric note.",
        ]

    hints = []
    # Scale phases across available rounds
    phase_size = max(1, total_rounds // 5)

    for i in range(total_rounds):
        phase = i // phase_size if phase_size > 0 else 0

        if phase == 0:
            hints.append(
                "Introduce the emergency. The klaxon, the hull breach, the ship in crisis. "
                "Address each player by their character name and give them a starting "
                "situation to react to. Establish the setting aboard the MSV Koronis."
            )
        elif phase == 1:
            hints.append(
                "Escalate tension. Reveal more about the creatures — sounds in the vents, "
                "claw marks, a dead crew member. Introduce NPC Science Officer Lin, who is "
                "performing an autopsy and seems to know too much about these things. "
                "Introduce NPC Delacroix who guards a mysterious crate in the cargo bay."
            )
        elif phase == 2:
            hints.append(
                "Mid-game development. The crew discovers the corporate conspiracy — "
                "Stellaris Corp knew about the creatures, the KX-7 sample is a pheromone "
                "beacon. Lin is a corporate handler. The captain is missing. Build toward "
                "the cargo bay confrontation."
            )
        elif phase == 3:
            hints.append(
                "Climax. The crew reaches the cargo bay and faces the Void Stalker Queen "
                "anchored to the breach. Present the three-way choice: give her the sample "
                "(she leaves peacefully), destroy it (she rages), or fight her. Let the "
                "players decide."
            )
        else:
            hints.append(
                "Resolution and epilogue. Narrate the outcome of the players' choice. "
                "Wrap up loose threads — Lin's testimony, the distress signal, the crew's "
                "survival. End on an atmospheric, contemplative note. The stars are beautiful "
                "if you don't think about what lives between them."
            )

    return hints[:total_rounds]


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Play a full Hull Breach arc with LLM agents")
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

    # ── Registration ──────────────────────────────────────────────────
    print("=== Registering agents ===")

    def register(name: str) -> dict:
        resp = http.post("/agents/register", json={"name": f"{name}-{suffix}"})
        resp.raise_for_status()
        data = resp.json()
        data["display_name"] = name
        return data

    dm_agent = register("Warden")
    alice_agent = register("Alice")
    bob_agent = register("Bob")
    carol_agent = register("Carol")
    print(f"  DM: {dm_agent['display_name']}")
    print(f"  Players: Alice (Reyes), Bob (Okafor), Carol (Tran — joins mid-session)")

    # ── Create game ───────────────────────────────────────────────────
    print("\n=== Creating game ===")
    game_resp = http.post(
        "/lobby",
        json={
            "name": campaign["name"],
            "description": campaign["description"] + "\n\n" + campaign.get("player_guide", ""),
            "config": {"max_players": 5, "allow_mid_session_join": True},
        },
        headers={"Authorization": f"Bearer {dm_agent['api_key']}"},
    ).json()
    game_id = game_resp["id"]
    dm_tok = game_resp["session_token"]
    print(f"  Game: {game_resp['name']} ({game_id[:8]}...)")

    # ── Players join ──────────────────────────────────────────────────
    print("\n=== Players joining ===")

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

    # ── Engine setup ─────────────────────────────────────────────────
    engine = None
    combat_engine = None
    use_engine = not args.freestyle

    if use_engine:
        print("\n=== Initializing game engine ===")
        engine = GameEngine(in_memory=True)
        engine.init_game(campaign["name"])
        combat_engine = CombatEngine(engine)
        print("  Engine ready (d100 roll-under mechanics)")

    # ── Players join ──────────────────────────────────────────────────
    print("\n=== Players joining ===")

    def _create_engine_character(character_name: str) -> None:
        """Create a character in the local engine and equip them."""
        if not use_engine:
            return
        char_class = CHARACTER_CLASSES[character_name]
        engine.create_character(character_name, char_class)
        equip = CHARACTER_EQUIPMENT.get(character_name, {})
        if equip:
            state = engine.get_state()
            char = state.characters[character_name]
            if "weapons" in equip:
                char.weapons = equip["weapons"]
            if "armor" in equip:
                char.armor = equip["armor"]
            if "inventory" in equip:
                char.inventory = equip["inventory"]
            engine._save(state)
        print(f"    Engine: {character_name} ({char_class.value}) created with equipment")

    alice_tok = join(alice_agent, "Reyes")
    _create_engine_character("Reyes")
    bob_tok = join(bob_agent, "Okafor")
    _create_engine_character("Okafor")

    # Carol joins mid-session (after round 3)

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

    # ── Whisper character stats to players ─────────────────────────────
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

    # ── Build LLM agents ─────────────────────────────────────────────
    if use_engine:
        dm_system = ENGINE_DM_SYSTEM_PROMPT.format(campaign_json=campaign_json)
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
        dm_system = FREESTYLE_DM_SYSTEM_PROMPT.format(campaign_json=campaign_json)
        dm = AIDM(
            name="Warden",
            system_prompt=dm_system,
            llm=llm, http=http,
            api_key=dm_agent["api_key"],
            session_token=dm_tok,
            game_id=game_id,
        )

    reyes = AIPlayer(
        name="Reyes",
        system_prompt=player_system_prompt("Reyes", **CHARACTERS["Reyes"]),
        llm=llm, http=http,
        api_key=alice_agent["api_key"],
        session_token=alice_tok,
        game_id=game_id,
    )

    okafor = AIPlayer(
        name="Okafor",
        system_prompt=player_system_prompt("Okafor", **CHARACTERS["Okafor"]),
        llm=llm, http=http,
        api_key=bob_agent["api_key"],
        session_token=bob_tok,
        game_id=game_id,
    )

    active_players: list[AIPlayer] = [reyes, okafor]
    tran: AIPlayer | None = None  # joins later

    # ── Whisper character stats ───────────────────────────────────────
    if use_engine:
        print("\n=== Sending character stats ===")
        player_agent_map = {"Reyes": alice_agent, "Okafor": bob_agent}
        for char_name, pagent in player_agent_map.items():
            sheet = _format_character_sheet(char_name)
            if sheet:
                dm.whisper(
                    [pagent["id"]],
                    f"Welcome {char_name} to the game and share their character sheet "
                    f"so they know their capabilities. Keep it in character — brief and "
                    f"practical.\n\nCharacter sheet:\n{sheet}",
                )
                print(f"  Sent stats to {char_name}")

    # ── Character introductions ───────────────────────────────────────
    INTRO_PROMPT = (
        "Briefly introduce yourself in 1-2 sentences. Describe how you look "
        "right now — what you're wearing, what you're carrying, your demeanor. "
        "No backstory, just a quick visual snapshot as others would see you."
    )
    print("\n=== Character introductions ===")
    for player in active_players:
        print(f"  [{player.name} introducing...]", flush=True)
        player.take_turn(INTRO_PROMPT)
        print(f"  [{player.name} done]", flush=True)

    # ── Emoji selection ────────────────────────────────────────────────
    character_emojis: dict[str, str] = {}
    EMOJI_PROMPT = "Pick ONE emoji that represents your character. Reply with just the emoji, nothing else."
    print("\n=== Emoji selection ===")
    for player in active_players:
        print(f"  [{player.name} picking emoji...]", flush=True)
        emoji_resp = player.generate(EMOJI_PROMPT)
        # Extract the first emoji-like character from the response
        emoji = emoji_resp.strip()[:2]  # emoji can be 1-2 chars (with variation selectors)
        character_emojis[player.name] = emoji
        print(f"  {player.name}: {emoji}")
    print(f"  Emojis: {character_emojis}")

    # ── Game loop ─────────────────────────────────────────────────────
    pacing = get_pacing_hints(args.rounds)
    carol_join_round = min(3, args.rounds - 2)  # join after round 3 (or earlier for short games)

    for round_num in range(args.rounds):
        round_label = round_num + 1
        print(f"\n{'─' * 60}")
        print(f"  ROUND {round_label}/{args.rounds}")
        print(f"{'─' * 60}")

        # Mid-session join
        if round_num == carol_join_round and tran is None:
            print("\n  >>> Carol joins mid-session as Tran <<<")
            carol_tok = join(carol_agent, "Tran")
            _create_engine_character("Tran")
            tran = AIPlayer(
                name="Tran",
                system_prompt=player_system_prompt("Tran", **CHARACTERS["Tran"]),
                llm=llm, http=http,
                api_key=carol_agent["api_key"],
                session_token=carol_tok,
                game_id=game_id,
            )
            active_players.append(tran)
            # Whisper Tran's stats
            if use_engine:
                sheet = _format_character_sheet("Tran")
                if sheet:
                    dm.whisper(
                        [carol_agent["id"]],
                        f"Welcome Tran to the game and share their character sheet "
                        f"so they know their capabilities. Keep it in character — brief "
                        f"and practical.\n\nCharacter sheet:\n{sheet}",
                    )
                    print(f"  Sent stats to Tran")

            print(f"  [Tran introducing...]", flush=True)
            tran.take_turn(INTRO_PROMPT)
            print(f"  [Tran done]", flush=True)

            # Pick emoji for Tran
            print(f"  [Tran picking emoji...]", flush=True)
            emoji_resp = tran.generate(EMOJI_PROMPT)
            emoji = emoji_resp.strip()[:2]
            character_emojis["Tran"] = emoji
            print(f"  Tran: {emoji}")

        # DM narrates
        hint = pacing[round_num]
        active_names = ", ".join(p.name for p in active_players)
        engine_hint = ""
        if use_engine:
            engine_hint = (
                "\n\nYou have game engine tools available. Consider calling for rolls "
                "when players attempt risky actions. Use combat mechanics for significant "
                "confrontations (e.g. the Void Stalker encounter). Not every action needs "
                "a roll — let routine tasks succeed automatically."
            )
        full_hint = (
            f"{hint}\n\nActive players: {active_names}. "
            f"Remember: respond with JSON containing \"narration\" and \"respond\" fields."
            f"{engine_hint}"
        )
        print(f"\n  [Warden narrating...]", flush=True)
        narration = dm.narrate(full_hint)
        print(f"  [Warden done]", flush=True)

        # Determine responders: filter DM's respond list by who's actually
        # mentioned in the narration text to prevent over-broad responses.
        narration_text = narration.get("content", "").lower()
        respond_names = narration.get("_respond", [])
        if respond_names:
            tagged = {name.strip().lower() for name in respond_names}
            # Only include players who are both in the respond list AND
            # mentioned by name in the narration itself.
            mentioned = {p.name for p in active_players if p.name.lower() in narration_text}
            responders = [p for p in active_players if p.name.lower() in tagged and p.name in mentioned]
            if not responders:
                # Fallback: trust the DM's list if name-check filtered everyone
                responders = [p for p in active_players if p.name.lower() in tagged]
            if not responders:
                print(f"  [WARN: respond names {respond_names} matched no active players, falling back to all]", flush=True)
                responders = active_players
            else:
                print(f"  [Responding: {', '.join(p.name for p in responders)}]", flush=True)
        else:
            # Fallback: everyone responds
            print(f"  [WARN: no respond list from DM, all players respond]", flush=True)
            responders = active_players

        for player in responders:
            print(f"  [{player.name} acting...]", flush=True)
            player.take_turn(
                f"Respond as {player.name}. Keep it to 1-4 sentences — an action, "
                f"a line of dialogue, or a quick reaction. No inner monologue."
            )
            print(f"  [{player.name} done]", flush=True)

        # Occasional DM whisper (rounds 2 and 5)
        if round_num == 1 and len(active_players) >= 1:
            print(f"  [Warden whispering to {active_players[0].name}...]")
            dm.whisper(
                [alice_agent["id"]],
                f"Generate a private whisper to {active_players[0].name} only. "
                f"Reveal something unsettling that only they notice — a detail, "
                f"a sound, something glimpsed. Keep it to 1-2 sentences.",
            )
            print(f"  [whisper sent]")
        elif round_num == 4 and len(active_players) >= 2:
            print(f"  [Warden whispering to {active_players[1].name}...]")
            dm.whisper(
                [bob_agent["id"]],
                f"Generate a private whisper to {active_players[1].name} only. "
                f"They notice something suspicious about Science Officer Lin — "
                f"a corporate implant, a hidden device, a telling reaction. "
                f"Keep it to 1-2 sentences.",
            )
            print(f"  [whisper sent]")

    # ── End game ──────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("  EPILOGUE")
    print(f"{'─' * 60}")

    print("\n  [Warden narrating epilogue...]")
    dm.narrate(
        "Write the final epilogue. The crisis is resolved (however the players chose "
        "to handle it). Describe the aftermath: the crew waiting for rescue, the "
        "truth about Stellaris transmitted into the void, the quiet after the storm. "
        "End on a contemplative, atmospheric note. This is the last message of the game."
    )
    print("  [Warden done]")

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
    print("  HULL BREACH — Full Transcript")
    print(f"{'=' * 70}")

    data = http.get(
        f"/games/{game_id}/messages?limit=500",
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
    PLAYER_COLORS = ["\033[32m", "\033[33m", "\033[34m", "\033[31m"]  # green, yellow, blue, red
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
        """Character name with optional emoji prefix."""
        cn = char_names.get(agent_name, agent_name)
        emoji = character_emojis.get(cn, "")
        return f"{emoji} {cn}" if emoji else cn

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
    print(f"  View in browser: {base}/game.html?id={game_id}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
