#!/usr/bin/env python3
"""Play a full Hull Breach campaign arc via the HTTP API with LLM-driven agents.

Each participant (DM + players) is backed by a Claude LLM call that generates
all dialogue and narration dynamically based on the evolving game transcript.

The orchestrator is intentionally thin — it handles registration, setup, and
the turn loop, but the DM agent drives pacing, whispers, and narrative flow
through its system prompt and the server-side instructions.

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

    # ── Players join ──────────────────────────────────────────────────
    print("\n=== Players joining ===")
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

    # ── DM briefing ───────────────────────────────────────────────────
    # Give the DM all the context it needs to self-direct pacing.
    char_summaries = []
    for name, agent in [("Reyes", alice_agent), ("Okafor", bob_agent)]:
        sheet = _format_character_sheet(name)
        char_summaries.append(f"- {name} (agent: {agent['id']})" + (f"\n{sheet}" if sheet else ""))
    joining_later = f"- Tran (agent: {carol_agent['id']}) — joins mid-session around round 3"
    if use_engine:
        tran_sheet = _format_character_sheet("Tran")
        if tran_sheet:
            joining_later += f"\n{tran_sheet}"

    briefing = (
        f"Game briefing: you have {args.rounds} rounds total to tell this story. "
        f"Pace yourself — introduction, escalation, climax, resolution.\n\n"
        f"Current players:\n" + "\n".join(char_summaries) + "\n\n"
        f"Joining later:\n{joining_later}\n\n"
        f"When a player joins, welcome them with a whisper sharing their capabilities "
        f"(use to_agents), then fold them into the scene.\n\n"
        f"Use whispers throughout the game to share private observations, hints, or "
        f"unsettling details with individual characters when dramatically appropriate.\n\n"
        f"Start the game now. Set the scene and prompt the active players."
    )

    # ── Round 0: DM opens ─────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"  ROUND 1/{args.rounds}")
    print(f"{'─' * 60}")

    print(f"\n  [Warden narrating...]", flush=True)
    narration = dm.narrate(briefing)
    print(f"  [Warden done]", flush=True)

    # Let all active players introduce themselves
    for player in active_players:
        print(f"  [{player.name} acting...]", flush=True)
        player.take_turn(
            "The DM just set the scene. Introduce yourself briefly (1-2 sentences — "
            "what you look like, what you're doing) then react to the situation."
        )
        print(f"  [{player.name} done]", flush=True)

    # ── Game loop (remaining rounds) ──────────────────────────────────
    carol_join_round = min(3, args.rounds - 2)

    for round_num in range(1, args.rounds):
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

        # DM narrates — minimal instruction, let it drive
        active_names = ", ".join(p.name for p in active_players)
        is_last = round_label == args.rounds
        round_instruction = f"Round {round_label}/{args.rounds}. Active players: {active_names}."
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
    print("  HULL BREACH — Full Transcript")
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
