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
import re
import uuid
from pathlib import Path

import anthropic
import httpx

from agents import GameAgent, AIPlayer, AIDM


# ---------------------------------------------------------------------------
# Campaign data
# ---------------------------------------------------------------------------

CAMPAIGN_PATH = Path(__file__).resolve().parent.parent / "campaigns" / "hull-breach.json"


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

DM_SYSTEM_PROMPT = """\
You are the **Warden** (DM) for "Dungeons and Agents," a sci-fi horror RPG. \
You run a play-by-post game aboard the MSV Koronis, a mining vessel with a \
catastrophic hull breach.

## Style

- **Tone**: Sci-fi horror. Tense, atmospheric. Think Alien meets blue-collar space workers.
- **Length**: 1-3 SHORT paragraphs. Punchy, not purple. Leave space for players to react.
- **Pacing**: End each narration with a clear prompt — a question, a sound, a choice. \
Tell players what kind of response you want: a quick reaction, a decision, a line of \
dialogue. This keeps the game snappy and conversational.
- **NPCs**: Give them distinct voices. Lin speaks in clipped, clinical sentences. \
Delacroix rambles when scared. ARIA is monotone and procedural. Tran is terse and data-focused.
- **Player agency**: Present situations. Never dictate what player characters do or feel.
- **Selective addressing**: Don't address every player every round. Focus on 1-2 characters \
per narration to keep the pace tight. Rotate focus across rounds.

## Response Tag (REQUIRED)

At the very end of every narration, add a tag listing which characters should respond:
```
[RESPOND: Reyes, Okafor]
```
Only list characters who were directly addressed or who have a clear reason to act — \
usually 1-2 characters, not everyone. This is crucial for pacing.

## Rules

- Freestyle — no dice, no stats. Pure collaborative narration.
- Stay in the fiction. Never reference APIs, game mechanics, or system details.
- Address players by character name.
- When a new player joins mid-session, fold them in naturally.

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

## Rules

- Stay in character as {character_name}. First person.
- **Keep it SHORT.** 1-4 sentences is ideal. Think dialogue, not narration.
- Declare actions plainly: "I check the console." "I grab the wrench."
- Talk like a real person under stress — fragments, interruptions, cursing.
- React to what JUST happened. Don't narrate ahead or write inner monologue.
- Have opinions. Disagree with people. Make snap decisions.
- Never reference game mechanics, APIs, or systems. Stay in the fiction.
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

    alice_tok = join(alice_agent, "Reyes")
    bob_tok = join(bob_agent, "Okafor")

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
    dm_system = DM_SYSTEM_PROMPT.format(campaign_json=campaign_json)

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
            tran = AIPlayer(
                name="Tran",
                system_prompt=player_system_prompt("Tran", **CHARACTERS["Tran"]),
                llm=llm, http=http,
                api_key=carol_agent["api_key"],
                session_token=carol_tok,
                game_id=game_id,
            )
            active_players.append(tran)

        # DM narrates
        hint = pacing[round_num]
        active_names = ", ".join(p.name for p in active_players)
        full_hint = f"{hint}\n\nActive players: {active_names}. End with [RESPOND: name1, name2] to indicate who should reply."
        print(f"\n  [Warden narrating...]", flush=True)
        narration = dm.narrate(full_hint)
        print(f"  [Warden done]", flush=True)

        # Parse [RESPOND: ...] tag from DM's raw output to decide who acts
        narration_raw = narration.get("_raw", narration.get("content", ""))
        respond_match = re.search(r'\[RESPOND:\s*([^\]]+)\]', narration_raw, re.IGNORECASE)
        if respond_match:
            tagged = {name.strip().lower() for name in respond_match.group(1).split(",")}
            responders = [p for p in active_players if p.name.lower() in tagged]
        else:
            # Fallback: everyone responds
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

    messages = http.get(
        f"/games/{game_id}/messages?limit=500",
        headers={
            "Authorization": f"Bearer {dm_agent['api_key']}",
            "X-Session-Token": dm_tok,
        },
    ).json()

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
            print(f"  {DIM}(OOC) {c}{sender}{RESET}{DIM}: {msg['content']}{RESET}")
        elif msg["type"] == "action":
            c = player_color(sender)
            print(f"\n  {BOLD}{c}{sender}{RESET}{whisper_tag}:")
            print(f"  {c}>{RESET} {msg['content']}")
        else:
            print(f"  [{msg['type'].upper()}] {sender}: {msg['content']}")

    print(f"\n{'=' * 70}")
    print(f"  Game ID: {game_id}")
    print(f"  View in browser: {base}/game.html?id={game_id}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
