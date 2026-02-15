"""Standalone DM engine tool.

Run a game engine locally and post results to the play-by-post server.
This lets DMs mediate the engine themselves rather than running it on the server.

Usage:
    uv run python -m server.dm_engine --server http://localhost:8000 \
        --api-key pbp-... --session-token ses-... --game-id <id>

    # Or offline (no server connection):
    uv run python -m server.dm_engine --offline

Commands (interactive):
    roll <character> <stat> [skill]       - Roll a stat check
    damage <target> <amount>              - Apply damage
    heal <target> <amount>                - Heal a character
    panic <character>                     - Panic check
    stress <character> <amount>           - Add/remove stress
    create <name> [class]                 - Create a character
    state                                 - Show engine state
    characters                            - List characters
    char <name>                           - Show character details
    scene <description>                   - Set scene description
    log [count]                           - Show recent log entries

    preview roll <character> <stat> [skill] - Dry-run a roll (no side effects)
    preview damage <character> <amount>     - Dry-run damage
    odds <character> <stat> [skill]         - Show success probabilities
    what-if <dice> <threshold> [effect]     - Conditional chain (e.g. 1d20 15 1d10)
    simulate <dice> <threshold> <effect>    - Monte Carlo simulation

    snapshot save [name]                    - Save engine state snapshot
    snapshot restore [name]                 - Restore from snapshot
    snapshot list                           - List snapshots
    snapshot delete <name>                  - Delete a snapshot

    save [path]                             - Save engine state to file
    load <path>                             - Load engine state from file
    help                                    - Show commands
    quit                                    - Exit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from game.engine import GameEngine
from game.models import CharacterClass
from game.preview import PreviewEngine, dice_avg, dice_range, roll_dice_expr


def post_result(
    client: httpx.Client, game_id: str, headers: dict,
    summary: str, details: dict,
) -> None:
    """Post an engine result as a roll message to the server."""
    resp = client.post(
        f"/games/{game_id}/messages",
        json={
            "content": summary,
            "type": "roll",
            "metadata": {"engine_result": details},
        },
        headers=headers,
    )
    if resp.status_code == 200:
        print(f"  [posted to server]")
    else:
        print(f"  [post failed ({resp.status_code}): {resp.text}]")


def _format_character(char) -> str:
    """Format a character for display."""
    lines = [
        f"  {char.name} — {char.char_class.value}",
        f"    HP: {char.hp}/{char.max_hp} | Wounds: {char.wounds}/{char.max_wounds} | Stress: {char.stress}",
        f"    STR: {char.stats.strength} SPD: {char.stats.speed} INT: {char.stats.intellect} CMB: {char.stats.combat}",
        f"    Saves — SAN: {char.saves.sanity} FEAR: {char.saves.fear} BODY: {char.saves.body}",
    ]
    if char.armor.ap > 0:
        lines.append(f"    Armor: {char.armor.name} (AP {char.armor.ap})")
    if char.skills:
        skills_str = ", ".join(f"{k} ({v.value})" for k, v in char.skills.items())
        lines.append(f"    Skills: {skills_str}")
    if char.conditions:
        lines.append(f"    Conditions: {', '.join(c.value for c in char.conditions)}")
    if char.inventory:
        lines.append(f"    Inventory: {', '.join(char.inventory)}")
    if not char.alive:
        lines.append(f"    ** DEAD **")
    return "\n".join(lines)


def run_interactive(
    engine: GameEngine,
    preview: PreviewEngine,
    client: httpx.Client | None,
    game_id: str | None,
    headers: dict | None,
) -> None:
    mode = "online" if client else "offline"
    print(f"\nDM Engine ({mode}) — type 'help' for commands\n")

    while True:
        try:
            line = input("dm> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            _handle_command(cmd, parts, engine, preview, client, game_id, headers)
        except Exception as e:
            print(f"  Error: {e}")


def _handle_command(
    cmd: str, parts: list[str],
    engine: GameEngine, preview: PreviewEngine,
    client: httpx.Client | None, game_id: str | None, headers: dict | None,
) -> None:
    if cmd == "quit":
        raise SystemExit(0)
    elif cmd == "help":
        print(__doc__)
    elif cmd == "state":
        state = engine.get_state()
        print(f"  Game: {state.name}")
        print(f"  Scene: {state.scene or '(none)'}")
        print(f"  Characters: {len(state.characters)}")
        print(f"  Combat: {'active' if state.combat.active else 'inactive'}")
    elif cmd == "characters":
        state = engine.get_state()
        if not state.characters:
            print("  No characters.")
        for char in state.characters.values():
            print(_format_character(char))
    elif cmd == "char":
        if len(parts) < 2:
            print("  Usage: char <name>")
            return
        char = engine.get_character(parts[1])
        print(_format_character(char))
    elif cmd == "scene":
        if len(parts) < 2:
            state = engine.get_state()
            print(f"  Scene: {state.scene or '(none)'}")
            return
        desc = " ".join(parts[1:])
        engine.set_scene(desc)
        print(f"  Scene set.")
    elif cmd == "log":
        count = int(parts[1]) if len(parts) > 1 else 10
        entries = engine.get_log(count)
        for e in entries:
            print(f"  [{e.category}] {e.message}")
        if not entries:
            print("  No log entries.")
    elif cmd == "create":
        if len(parts) < 2:
            print("  Usage: create <name> [class]")
            print(f"  Classes: {', '.join(c.value for c in CharacterClass)}")
            return
        name = parts[1]
        cls_name = parts[2] if len(parts) > 2 else "marine"
        try:
            char_class = CharacterClass(cls_name.lower())
        except ValueError:
            print(f"  Unknown class '{cls_name}'. Valid: {', '.join(c.value for c in CharacterClass)}")
            return
        char = engine.create_character(name, char_class)
        print(_format_character(char))

    # --- Engine actions (post to server if connected) ---
    elif cmd == "roll":
        if len(parts) < 3:
            print("  Usage: roll <character> <stat> [skill] [--adv|--dis]")
            return
        char_name = parts[1]
        stat = parts[2]
        skill = None
        advantage = "--adv" in parts
        disadvantage = "--dis" in parts
        remaining = [p for p in parts[3:] if p not in ("--adv", "--dis")]
        if remaining:
            skill = remaining[0]
        result = engine.roll_check(char_name, stat, skill=skill,
                                   advantage=advantage, disadvantage=disadvantage)
        summary = (
            f"{char_name} rolls {stat} (target {result.target}): "
            f"{result.roll} -> {result.result.value}"
        )
        if skill:
            summary += f" [skill: {skill}]"
        if len(result.all_rolls) > 1:
            summary += f" [rolls: {result.all_rolls}]"
        print(f"  {summary}")
        _maybe_post(client, game_id, headers, summary, {
            "roll": result.roll, "target": result.target,
            "result": result.result.value, "doubles": result.doubles,
            "succeeded": result.succeeded,
        })
    elif cmd == "damage":
        if len(parts) < 3:
            print("  Usage: damage <target> <amount>")
            return
        result = engine.apply_damage(parts[1], int(parts[2]))
        summary = (
            f"{parts[1]} takes {result['damage_taken']} damage"
            + (f" (wound!)" if result["wound"] else "")
            + (f" (DEATH)" if result["dead"] else "")
        )
        print(f"  {summary}")
        _maybe_post(client, game_id, headers, summary, result)
    elif cmd == "heal":
        if len(parts) < 3:
            print("  Usage: heal <target> <amount>")
            return
        healed = engine.heal(parts[1], int(parts[2]))
        print(f"  {parts[1]} healed {healed} HP.")
        _maybe_post(client, game_id, headers, f"{parts[1]} healed {healed} HP.", {"healed": healed})
    elif cmd == "panic":
        if len(parts) < 2:
            print("  Usage: panic <character>")
            return
        result = engine.panic_check(parts[1])
        if result["panicked"]:
            summary = f"{parts[1]} panics! (rolled {result['roll']} vs stress {result['stress']}) — {result['effect']}"
        else:
            summary = f"{parts[1]} keeps it together (rolled {result['roll']} vs stress {result['stress']})."
        print(f"  {summary}")
        _maybe_post(client, game_id, headers, summary, result)
    elif cmd == "stress":
        if len(parts) < 3:
            print("  Usage: stress <character> <amount> (negative to reduce)")
            return
        new_stress = engine.add_stress(parts[1], int(parts[2]))
        print(f"  {parts[1]} stress is now {new_stress}.")

    # --- Preview / what-if commands ---
    elif cmd == "preview":
        _handle_preview(parts[1:], preview)
    elif cmd == "odds":
        if len(parts) < 3:
            print("  Usage: odds <character> <stat> [skill]")
            return
        skill = parts[3] if len(parts) > 3 else None
        odds = preview.check_odds(parts[1], parts[2], skill=skill)
        print(f"  {parts[1]} {parts[2]} check (target {odds.target}, modifier {odds.modifier:+d}, effective {odds.effective_target}):")
        print(f"    Critical success: {odds.critical_success_pct:.0f}%")
        print(f"    Success:          {odds.success_pct:.0f}%")
        print(f"    Total pass:       {odds.critical_success_pct + odds.success_pct:.0f}%")
        print(f"    Failure:          {odds.failure_pct:.0f}%")
        print(f"    Critical failure: {odds.critical_failure_pct:.0f}%")
    elif cmd == "what-if":
        if len(parts) < 3:
            print("  Usage: what-if <dice> <threshold> [effect_dice]")
            print("  Example: what-if 1d20 15 1d10")
            return
        dice_expr = parts[1]
        threshold = int(parts[2])
        effect_expr = parts[3] if len(parts) > 3 else None
        result = preview.resolve_conditional(dice_expr, threshold, on_success_expr=effect_expr)
        print(f"  {result.description}")
        for k, v in result.details.items():
            print(f"    {k}: {v}")
    elif cmd == "simulate":
        if len(parts) < 4:
            print("  Usage: simulate <dice> <threshold> <effect_dice> [trials]")
            print("  Example: simulate 1d20 15 1d10 10000")
            return
        trials = int(parts[4]) if len(parts) > 4 else 10000
        result = preview.simulate_conditional(parts[1], int(parts[2]), parts[3], trials=trials)
        print(f"  Simulation ({result['trials']} trials):")
        print(f"    Hit rate:              {result['hit_rate_pct']}%")
        print(f"    Avg damage on hit:     {result['avg_damage_on_hit']}")
        print(f"    Expected damage/roll:  {result['expected_damage_per_roll']}")
        print(f"    Trigger range:         {result['trigger_range']} (need {result['threshold']}+)")
        print(f"    Effect range:          {result['effect_range']} (avg {result['effect_avg']})")

    # --- Snapshot commands ---
    elif cmd == "snapshot":
        _handle_snapshot(parts[1:], preview)

    # --- Save/Load ---
    elif cmd == "save":
        path = parts[1] if len(parts) > 1 else "engine_state.json"
        data = engine.save_state_json()
        Path(path).write_text(data)
        print(f"  State saved to {path}")
    elif cmd == "load":
        if len(parts) < 2:
            print("  Usage: load <path>")
            return
        data = Path(parts[1]).read_text()
        engine.load_state_json(data)
        print(f"  State loaded from {parts[1]}")
    else:
        print(f"  Unknown command: {cmd}. Type 'help' for usage.")


def _handle_preview(parts: list[str], preview: PreviewEngine) -> None:
    if not parts:
        print("  Usage: preview roll <character> <stat> [skill]")
        print("         preview damage <character> <amount>")
        return
    sub = parts[0].lower()
    if sub == "roll":
        if len(parts) < 3:
            print("  Usage: preview roll <character> <stat> [skill] [--adv|--dis]")
            return
        char_name = parts[1]
        stat = parts[2]
        advantage = "--adv" in parts
        disadvantage = "--dis" in parts
        remaining = [p for p in parts[3:] if p not in ("--adv", "--dis")]
        skill = remaining[0] if remaining else None
        result = preview.preview_roll(char_name, stat, skill=skill,
                                      advantage=advantage, disadvantage=disadvantage)
        print(f"  {result.description}")
    elif sub == "damage":
        if len(parts) < 3:
            print("  Usage: preview damage <character> <amount>")
            return
        result = preview.preview_damage(parts[1], int(parts[2]))
        print(f"  {result.description}")
    else:
        print(f"  Unknown preview command: {sub}")


def _handle_snapshot(parts: list[str], preview: PreviewEngine) -> None:
    if not parts:
        print("  Usage: snapshot save|restore|list|delete [name]")
        return
    sub = parts[0].lower()
    if sub == "save":
        name = parts[1] if len(parts) > 1 else "default"
        preview.save_snapshot(name)
        print(f"  Snapshot '{name}' saved.")
    elif sub == "restore":
        name = parts[1] if len(parts) > 1 else "default"
        if preview.restore_snapshot(name):
            print(f"  Snapshot '{name}' restored.")
        else:
            print(f"  Snapshot '{name}' not found.")
    elif sub == "list":
        names = preview.list_snapshots()
        if names:
            for n in names:
                print(f"  - {n}")
        else:
            print("  No snapshots.")
    elif sub == "delete":
        if len(parts) < 2:
            print("  Usage: snapshot delete <name>")
            return
        if preview.delete_snapshot(parts[1]):
            print(f"  Snapshot '{parts[1]}' deleted.")
        else:
            print(f"  Snapshot '{parts[1]}' not found.")
    else:
        print(f"  Unknown snapshot command: {sub}")


def _maybe_post(
    client: httpx.Client | None, game_id: str | None,
    headers: dict | None, summary: str, details: dict,
) -> None:
    """Post to server if connected."""
    if client and game_id and headers:
        post_result(client, game_id, headers, summary, details)


def main():
    parser = argparse.ArgumentParser(description="DM Engine — run a game engine locally")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--api-key", help="DM agent API key")
    parser.add_argument("--session-token", help="Session token for the game")
    parser.add_argument("--game-id", help="Game ID")
    parser.add_argument("--offline", action="store_true", help="Run without server connection")
    parser.add_argument("--load-state", help="Load engine state from a JSON file")
    parser.add_argument("--game-name", default="DM Session", help="Game name (offline mode)")
    args = parser.parse_args()

    if not args.offline and not (args.api_key and args.session_token and args.game_id):
        parser.error("Provide --api-key, --session-token, and --game-id, or use --offline")

    # Create engine (always in-memory — state persists via save/load)
    engine = GameEngine(in_memory=True)
    engine.init_game(args.game_name)

    if args.load_state:
        data = Path(args.load_state).read_text()
        engine.load_state_json(data)
        print(f"Loaded state from {args.load_state}")

    preview = PreviewEngine(engine)

    if args.offline:
        print("Running in offline mode (no server connection).")
        run_interactive(engine, preview, None, None, None)
    else:
        headers = {
            "Authorization": f"Bearer {args.api_key}",
            "X-Session-Token": args.session_token,
        }
        with httpx.Client(base_url=args.server) as client:
            try:
                resp = client.get(f"/lobby/{args.game_id}")
                if resp.status_code != 200:
                    print(f"Error: Could not find game {args.game_id} ({resp.status_code})")
                    sys.exit(1)
                game = resp.json()
                print(f"Connected to game: {game['name']} (DM: {game['dm_name']})")
            except httpx.ConnectError:
                print(f"Error: Could not connect to {args.server}")
                sys.exit(1)

            run_interactive(engine, preview, client, args.game_id, headers)

    # Offer to save state
    try:
        save = input("\nSave engine state? [y/N] ").strip().lower()
        if save == "y":
            path = f"engine_state_{args.game_id or 'offline'}.json"
            Path(path).write_text(engine.save_state_json())
            print(f"State saved to {path}")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
