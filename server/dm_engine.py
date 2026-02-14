"""Standalone DM engine tool.

Run a game engine locally and post results to the play-by-post server.
This lets DMs mediate the engine themselves rather than running it on the server.

Usage:
    uv run python -m server.dm_engine --server http://localhost:8000 \\
        --api-key pbp-... --session-token ses-... --game-id <id> \\
        --engine mothership

Commands (interactive):
    roll <character> <stat> [skill]   - Roll a stat check
    attack <character> <target>       - Combat attack
    damage <target> <amount>          - Apply damage
    heal <target> <amount>            - Heal a character
    panic <character>                 - Panic check
    create <name> [class]             - Create a character
    state                             - Show engine state
    characters                        - List characters
    help                              - Show commands
    quit                              - Exit
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from server.engine.base import EngineAction, GameEnginePlugin
from server.engine.freestyle import FreestylePlugin
from server.engine.mothership import MothershipPlugin


def create_engine(engine_type: str) -> GameEnginePlugin:
    if engine_type == "mothership":
        return MothershipPlugin()
    return FreestylePlugin()


def post_result(client: httpx.Client, game_id: str, headers: dict, summary: str, details: dict, action: dict) -> None:
    """Post an engine result as a roll message to the server."""
    resp = client.post(
        f"/games/{game_id}/messages",
        json={
            "content": summary,
            "type": "roll",
            "metadata": {"engine_result": details, "action": action},
        },
        headers=headers,
    )
    if resp.status_code == 200:
        print(f"  Posted: {summary}")
    else:
        print(f"  Failed to post ({resp.status_code}): {resp.text}")


def run_interactive(engine: GameEnginePlugin, client: httpx.Client, game_id: str, headers: dict) -> None:
    print(f"\nDM Engine ({engine.get_name()}) — type 'help' for commands\n")

    while True:
        try:
            line = input("engine> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "quit":
            break
        elif cmd == "help":
            print(__doc__)
            continue
        elif cmd == "state":
            print(json.dumps(engine.get_state(), indent=2))
            continue
        elif cmd == "characters":
            for c in engine.list_characters():
                print(f"  {c.get('name', '?')} — {c.get('char_class', '?')} HP:{c.get('hp', '?')}/{c.get('max_hp', '?')}")
            if not engine.list_characters():
                print("  No characters.")
            continue
        elif cmd == "create":
            if len(parts) < 2:
                print("  Usage: create <name> [class]")
                continue
            name = parts[1]
            char_class = parts[2] if len(parts) > 2 else "marine"
            char = engine.create_character(name, char_class=char_class)
            print(f"  Created: {char.get('name')} ({char.get('char_class')})")
            continue

        # Engine actions — process and post to server
        try:
            action = _parse_action(cmd, parts[1:])
        except ValueError as e:
            print(f"  Error: {e}")
            continue

        result = engine.process_action(action)
        print(f"  Result: {result.summary}")
        if result.details:
            for k, v in result.details.items():
                print(f"    {k}: {v}")

        post_result(client, game_id, headers, result.summary, result.details, action.model_dump())


def _parse_action(cmd: str, args: list[str]) -> EngineAction:
    match cmd:
        case "roll":
            if len(args) < 2:
                raise ValueError("Usage: roll <character> <stat> [skill]")
            return EngineAction(
                action_type="roll",
                character=args[0],
                params={"stat": args[1], "skill": args[2] if len(args) > 2 else None},
            )
        case "attack":
            if len(args) < 2:
                raise ValueError("Usage: attack <character> <target>")
            return EngineAction(
                action_type="attack",
                character=args[0],
                params={"target": args[1]},
            )
        case "damage":
            if len(args) < 2:
                raise ValueError("Usage: damage <target> <amount>")
            return EngineAction(
                action_type="damage",
                character=args[0],
                params={"target": args[0], "amount": int(args[1])},
            )
        case "heal":
            if len(args) < 2:
                raise ValueError("Usage: heal <target> <amount>")
            return EngineAction(
                action_type="heal",
                character=args[0],
                params={"target": args[0], "amount": int(args[1])},
            )
        case "panic":
            if len(args) < 1:
                raise ValueError("Usage: panic <character>")
            return EngineAction(action_type="panic", character=args[0])
        case _:
            raise ValueError(f"Unknown command: {cmd}. Type 'help' for usage.")


def main():
    parser = argparse.ArgumentParser(description="DM Engine — run a game engine locally")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--api-key", required=True, help="DM agent API key")
    parser.add_argument("--session-token", required=True, help="Session token for the game")
    parser.add_argument("--game-id", required=True, help="Game ID")
    parser.add_argument("--engine", default="mothership", choices=["mothership", "freestyle"])
    parser.add_argument("--load-state", help="Load engine state from a JSON file")
    args = parser.parse_args()

    engine = create_engine(args.engine)

    if args.load_state:
        with open(args.load_state) as f:
            engine.load_state(f.read())
        print(f"Loaded state from {args.load_state}")

    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "X-Session-Token": args.session_token,
    }

    with httpx.Client(base_url=args.server) as client:
        # Verify connection
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
                state = engine.save_state()
                path = f"engine_state_{args.game_id}.json"
                with open(path, "w") as f:
                    f.write(state)
                print(f"State saved to {path}")
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
