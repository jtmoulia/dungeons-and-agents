"""Standalone DM engine tool.

Run a game engine locally and post results to the play-by-post server.
This lets DMs mediate the engine themselves rather than running it on the server.

Usage:
    uv run python -m server.dm_engine --server http://localhost:8000 \
        --api-key pbp-... --session-token ses-... --game-id <id>

    # Or offline (no server connection):
    uv run python -m server.dm_engine --offline

    # With a config file:
    uv run python -m server.dm_engine --offline --engine-config path/to/config.json

Commands:
    roll <character> <stat> [--adv|--dis] [+/-mod] - Roll a stat check
    damage <target> <amount>              - Apply damage
    heal <target> <amount>                - Heal a character
    create <name> [stat=val ...]          - Create a character
    set_stat <character> <stat> <value>   - Set a stat value
    set_hp <character> <hp> [max_hp]      - Set HP directly
    condition add <character> <condition> - Add a condition
    condition remove <char> <condition>   - Remove a condition
    combat start <name1> <name2> ...      - Start combat
    combat next                           - Advance turn
    combat end                            - End combat
    inventory add <character> <item>      - Add inventory item
    inventory remove <character> <item>   - Remove inventory item
    note <character> <key> <value>        - Set a character note
    state                                 - Show engine state
    characters                            - List characters
    char <name>                           - Show character details
    scene <description>                   - Set scene description
    log [count]                           - Show recent log entries
    save [path]                           - Save engine state to file
    load <path>                           - Load engine state from file
    help                                  - Show commands
    quit                                  - Exit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx


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
    lines = [f"  {char.name}"]
    if char.stats:
        stats_str = " | ".join(f"{k}: {v}" for k, v in char.stats.items())
        lines.append(f"    Stats: {stats_str}")
    if char.hp is not None:
        lines.append(f"    HP: {char.hp}/{char.max_hp}")
    if char.conditions:
        lines.append(f"    Conditions: {', '.join(char.conditions)}")
    if char.inventory:
        lines.append(f"    Inventory: {', '.join(char.inventory)}")
    if char.notes:
        notes_str = ", ".join(f"{k}={v}" for k, v in char.notes.items())
        lines.append(f"    Notes: {notes_str}")
    if not char.alive:
        lines.append(f"    ** DEAD **")
    return "\n".join(lines)


def run_interactive(
    engine,
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
            _handle_command(cmd, parts, engine, client, game_id, headers)
        except Exception as e:
            print(f"  Error: {e}")


def _handle_command(
    cmd: str, parts: list[str],
    engine, client: httpx.Client | None,
    game_id: str | None, headers: dict | None,
) -> None:
    """Handle commands for the generic engine."""
    if cmd == "quit":
        raise SystemExit(0)
    elif cmd == "help":
        print(__doc__)
    elif cmd == "state":
        state = engine.get_state()
        print(f"  Game: {state.name}")
        print(f"  Scene: {state.scene or '(none)'}")
        print(f"  Characters: {len(state.characters)}")
        print(f"  Combat: {'active (round ' + str(state.combat.round) + ')' if state.combat.active else 'inactive'}")
        if state.combat.active and state.combat.current_combatant:
            print(f"  Current turn: {state.combat.current_combatant}")
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
            state = engine.get_state()
            stats = state.config.stat_names
            print(f"  Usage: create <name> [stat=val ...]")
            if stats:
                print(f"  Stats: {', '.join(stats)}")
            return
        name = parts[1]
        char_stats = {}
        hp = None
        for p in parts[2:]:
            if "=" in p:
                k, v = p.split("=", 1)
                if k == "hp":
                    hp = int(v)
                else:
                    char_stats[k] = int(v)
        char = engine.create_character(name, stats=char_stats or None, hp=hp)
        print(_format_character(char))
    elif cmd == "roll":
        if len(parts) < 3:
            print("  Usage: roll <character> <stat> [--adv|--dis] [+/-mod]")
            return
        char_name = parts[1]
        stat = parts[2]
        advantage = "--adv" in parts
        disadvantage = "--dis" in parts
        modifier = 0
        for p in parts[3:]:
            if p.startswith("+") or p.startswith("-"):
                try:
                    modifier = int(p)
                except ValueError:
                    pass
        result = engine.roll_check(char_name, stat, modifier=modifier,
                                   advantage=advantage, disadvantage=disadvantage)
        summary = (
            f"{char_name} rolls {stat} (target {result.target}): "
            f"{result.roll} -> {result.result.value}"
        )
        if modifier:
            summary += f" [modifier: {modifier:+d}]"
        if len(result.all_rolls) > 1:
            summary += f" [rolls: {result.all_rolls}]"
        print(f"  {summary}")
        _maybe_post(client, game_id, headers, summary, {
            "roll": result.roll, "natural": result.natural,
            "target": result.target, "result": result.result.value,
            "succeeded": result.succeeded,
        })
    elif cmd == "damage":
        if len(parts) < 3:
            print("  Usage: damage <target> <amount>")
            return
        result = engine.apply_damage(parts[1], int(parts[2]))
        dead_str = " (DEATH)" if result["dead"] else ""
        summary = f"{parts[1]} takes {result['damage']} damage (HP: {result['hp']}/{result['max_hp']}){dead_str}"
        print(f"  {summary}")
        _maybe_post(client, game_id, headers, summary, result)
    elif cmd == "heal":
        if len(parts) < 3:
            print("  Usage: heal <target> <amount>")
            return
        healed = engine.heal(parts[1], int(parts[2]))
        print(f"  {parts[1]} healed {healed} HP.")
        _maybe_post(client, game_id, headers, f"{parts[1]} healed {healed} HP.", {"healed": healed})
    elif cmd == "set_stat":
        if len(parts) < 4:
            print("  Usage: set_stat <character> <stat> <value>")
            return
        char = engine.set_stat(parts[1], parts[2], int(parts[3]))
        print(f"  {parts[1]}'s {parts[2]} set to {parts[3]}.")
    elif cmd == "set_hp":
        if len(parts) < 3:
            print("  Usage: set_hp <character> <hp> [max_hp]")
            return
        max_hp = int(parts[3]) if len(parts) > 3 else None
        char = engine.set_hp(parts[1], int(parts[2]), max_hp=max_hp)
        print(f"  {parts[1]} HP set to {char.hp}/{char.max_hp}.")
    elif cmd == "condition":
        if len(parts) < 3:
            print("  Usage: condition add|remove <character> <condition>")
            return
        sub = parts[1].lower()
        if sub == "add":
            if len(parts) < 4:
                print("  Usage: condition add <character> <condition>")
                return
            conditions = engine.add_condition(parts[2], parts[3])
            print(f"  {parts[2]} conditions: {', '.join(conditions)}")
        elif sub == "remove":
            if len(parts) < 4:
                print("  Usage: condition remove <character> <condition>")
                return
            conditions = engine.remove_condition(parts[2], parts[3])
            print(f"  {parts[2]} conditions: {', '.join(conditions) or '(none)'}")
        else:
            print(f"  Unknown: condition {sub}. Use add or remove.")
    elif cmd == "combat":
        if len(parts) < 2:
            print("  Usage: combat start|next|end [names...]")
            return
        sub = parts[1].lower()
        if sub == "start":
            if len(parts) < 3:
                print("  Usage: combat start <name1> <name2> ...")
                return
            combat = engine.start_combat(parts[2:])
            order = ", ".join(f"{c.name} ({c.initiative})" for c in combat.combatants)
            print(f"  Combat started! Order: {order}")
        elif sub == "next":
            combat = engine.next_turn()
            current = combat.current_combatant or "?"
            print(f"  Round {combat.round} — {current}'s turn.")
        elif sub == "end":
            engine.end_combat()
            print(f"  Combat ended.")
        else:
            print(f"  Unknown: combat {sub}. Use start, next, or end.")
    elif cmd == "inventory":
        if len(parts) < 4:
            print("  Usage: inventory add|remove <character> <item>")
            return
        sub = parts[1].lower()
        item = " ".join(parts[3:])
        if sub == "add":
            inv = engine.add_inventory(parts[2], item)
            print(f"  {parts[2]} inventory: {', '.join(inv)}")
        elif sub == "remove":
            inv = engine.remove_inventory(parts[2], item)
            print(f"  {parts[2]} inventory: {', '.join(inv) or '(none)'}")
        else:
            print(f"  Unknown: inventory {sub}. Use add or remove.")
    elif cmd == "note":
        if len(parts) < 4:
            print("  Usage: note <character> <key> <value>")
            return
        value = " ".join(parts[3:])
        notes = engine.set_note(parts[1], parts[2], value)
        print(f"  {parts[1]} notes: {notes}")
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
    parser.add_argument(
        "--engine-config", help="Path to GenericEngineConfig JSON file",
    )
    args = parser.parse_args()

    if not args.offline and not (args.api_key and args.session_token and args.game_id):
        parser.error("Provide --api-key, --session-token, and --game-id, or use --offline")

    from game.generic.engine import GenericEngine
    from game.generic.models import GenericEngineConfig

    config = None
    if args.engine_config:
        config = GenericEngineConfig.model_validate_json(
            Path(args.engine_config).read_text()
        )

    engine = GenericEngine(in_memory=True)
    engine.init_game(args.game_name, config=config)
    if config:
        print(f"Engine config: stats={config.stat_names}, dice={config.dice.dice}")

    if args.load_state:
        data = Path(args.load_state).read_text()
        engine.load_state_json(data)
        print(f"Loaded state from {args.load_state}")

    if args.offline:
        print("Running in offline mode (no server connection).")
        run_interactive(engine, None, None, None)
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

            run_interactive(engine, client, args.game_id, headers)

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
