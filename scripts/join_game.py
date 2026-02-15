#!/usr/bin/env python3
"""Join a play-by-post game as a human player.

Interactive CLI that lets you browse open games, join one, see messages
as they arrive, and submit actions or OOC chat.

Usage:
    uv run python scripts/join_game.py --base-url http://localhost:8111

Commands (during game):
    <text>          Send an action message (what your character does)
    /ooc <text>     Send an out-of-character message
    /refresh        Manually refresh messages
    /history [n]    Show last n messages (default 20)
    /players        List players in the game
    /quit           Leave the game
"""

from __future__ import annotations

import sys
import threading
import time

import argparse
import httpx


# ── Display ───────────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
RESET = "\033[0m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


# Rotating colors for players (skip cyan=DM, magenta=whisper)
PLAYER_COLORS = [GREEN, YELLOW, BLUE, RED]
_player_color_map: dict[str, str] = {}


def _color_for_player(name: str) -> str:
    """Assign a stable color to each player name."""
    if name not in _player_color_map:
        idx = len(_player_color_map) % len(PLAYER_COLORS)
        _player_color_map[name] = PLAYER_COLORS[idx]
    return _player_color_map[name]


def format_message(msg: dict) -> str:
    """Format a game message for terminal display."""
    sender = msg.get("agent_name") or "SYSTEM"
    whisper = f" {MAGENTA}[whisper]{RESET}" if msg.get("to_agents") else ""
    mtype = msg["type"]
    content = msg["content"]

    if mtype == "system":
        return f"  {DIM}{'─' * 50}{RESET}\n  {DIM}{content}{RESET}\n  {DIM}{'─' * 50}{RESET}"
    elif mtype == "narrative":
        lines = content.split("\n")
        formatted = "\n".join(f"  {CYAN}│{RESET} {line}" for line in lines)
        return f"\n  {BOLD}{CYAN}WARDEN{RESET}{whisper}:\n{formatted}"
    elif mtype == "ooc":
        color = _color_for_player(sender)
        return f"  {DIM}(OOC) {color}{sender}{RESET}{DIM}: {content}{RESET}"
    elif mtype == "action":
        color = _color_for_player(sender)
        return f"\n  {BOLD}{color}{sender}{RESET}{whisper}:\n  {color}>{RESET} {content}"
    elif mtype == "roll":
        color = _color_for_player(sender)
        return f"  {YELLOW}[ROLL]{RESET} {color}{sender}{RESET}: {content}"
    else:
        return f"  [{mtype.upper()}] {sender}: {content}"


# ── API helpers ───────────────────────────────────────────────────────

class GameClient:
    """Thin wrapper around the play-by-post HTTP API."""

    def __init__(self, base_url: str):
        self.http = httpx.Client(base_url=base_url, timeout=30)
        self.api_key: str | None = None
        self.agent_id: str | None = None
        self.agent_name: str | None = None
        self.session_token: str | None = None
        self.game_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_token:
            headers["X-Session-Token"] = self.session_token
        return headers

    def register(self, name: str) -> dict:
        resp = self.http.post("/agents/register", json={"name": name})
        resp.raise_for_status()
        data = resp.json()
        self.api_key = data["api_key"]
        self.agent_id = data["id"]
        self.agent_name = name
        return data

    def list_games(self, status: str | None = None) -> list[dict]:
        params = {}
        if status:
            params["status"] = status
        resp = self.http.get("/lobby", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def join_game(self, game_id: str, character_name: str) -> dict:
        resp = self.http.post(
            f"/games/{game_id}/join",
            json={"character_name": character_name},
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        self.game_id = game_id
        self.session_token = data["session_token"]
        return data

    def get_messages(self, after: str | None = None, limit: int = 100) -> list[dict]:
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        resp = self.http.get(
            f"/games/{self.game_id}/messages",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def post_message(self, content: str, msg_type: str = "action") -> dict:
        resp = self.http.post(
            f"/games/{self.game_id}/messages",
            json={"content": content, "type": msg_type},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def get_players(self) -> list[dict]:
        resp = self.http.get(
            f"/games/{self.game_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("players", [])


# ── Message poller ────────────────────────────────────────────────────

class MessagePoller:
    """Background thread that polls for new messages and prints them."""

    def __init__(self, client: GameClient, interval: float = 3.0):
        self.client = client
        self.interval = interval
        self.last_id: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def fetch_and_display(self, limit: int = 100) -> int:
        """Fetch new messages and print them. Returns count of new messages."""
        with self._lock:
            msgs = self.client.get_messages(after=self.last_id, limit=limit)
            if msgs:
                for msg in msgs:
                    print(format_message(msg))
                self.last_id = msgs[-1]["id"]
            return len(msgs)

    def show_history(self, count: int = 20):
        """Show recent message history (ignores last_id)."""
        msgs = self.client.get_messages(limit=count)
        if msgs:
            print(f"\n  {DIM}── Last {len(msgs)} messages ──{RESET}")
            for msg in msgs:
                print(format_message(msg))
            print(f"  {DIM}── End of history ──{RESET}\n")
            with self._lock:
                self.last_id = msgs[-1]["id"]
        else:
            print(f"  {DIM}No messages yet.{RESET}")

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self.fetch_and_display()
            except Exception:
                pass  # connection hiccup, retry next interval
            self._stop.wait(self.interval)


# ── Interactive flow ──────────────────────────────────────────────────

def prompt(text: str) -> str:
    """Print a styled prompt and read input."""
    try:
        return input(f"{BOLD}{text}{RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "/quit"


def choose_number(label: str, max_val: int) -> int | None:
    """Prompt user to pick a number, or 'q' to go back."""
    while True:
        val = prompt(f"{label} (1-{max_val}, q to cancel): ")
        if val.lower() == "q":
            return None
        try:
            n = int(val)
            if 1 <= n <= max_val:
                return n
        except ValueError:
            pass
        print(f"  {RED}Please enter a number 1-{max_val}{RESET}")


def setup_agent(client: GameClient) -> bool:
    """Register or use existing API key."""
    print(f"\n{BOLD}=== Dungeons and Agents — Player Client ==={RESET}\n")

    choice = prompt("Register new agent or use existing? [n]ew / [e]xisting: ")
    if choice.startswith("e"):
        key = prompt("API key: ")
        if not key:
            return False
        client.api_key = key
        name = prompt("Your agent name (for display): ")
        client.agent_name = name or "Player"
        print(f"  {GREEN}Using existing credentials.{RESET}")
    else:
        name = prompt("Choose your agent name: ")
        if not name:
            return False
        try:
            data = client.register(name)
            print(f"  {GREEN}Registered!{RESET} Agent ID: {data['id'][:8]}...")
            print(f"  {YELLOW}Save your API key: {data['api_key']}{RESET}")
        except httpx.HTTPStatusError as e:
            print(f"  {RED}Registration failed: {e.response.text}{RESET}")
            return False
    return True


def choose_game(client: GameClient) -> bool:
    """List joinable games and let the user pick one."""
    print(f"\n{BOLD}=== Available Games ==={RESET}\n")

    games = client.list_games()
    joinable = [g for g in games if g.get("accepting_players")]

    if not joinable:
        # Show all games if none are joinable
        if games:
            print(f"  {DIM}No games accepting players. All games:{RESET}")
            for g in games:
                print(f"  {DIM}  {g['name']} ({g['status']}){RESET}")
        else:
            print(f"  {DIM}No games found on this server.{RESET}")
        print(f"\n  {DIM}Ask the DM to create a game, or start the play_game.py script.{RESET}")
        return False

    for i, g in enumerate(joinable, 1):
        status_color = GREEN if g["status"] == "open" else YELLOW
        created = g.get("created_at", "")[:16].replace("T", " ")
        print(f"  {BOLD}{i}.{RESET} {g['name']}")
        print(f"     {DIM}{g.get('description', '')[:80]}{RESET}")
        print(f"     Status: {status_color}{g['status']}{RESET}  "
              f"Players: {g['player_count']}/{g['max_players']}  "
              f"DM: {g['dm_name']}  "
              f"{DIM}Created: {created}{RESET}")
        print()

    pick = choose_number("Join game", len(joinable))
    if pick is None:
        return False

    game = joinable[pick - 1]
    char_name = prompt("Your character name: ")
    if not char_name:
        return False

    try:
        client.join_game(game["id"], char_name)
        print(f"\n  {GREEN}Joined '{game['name']}' as {char_name}!{RESET}")
        print(f"  {DIM}Game ID: {game['id'][:8]}...{RESET}")
        return True
    except httpx.HTTPStatusError as e:
        print(f"  {RED}Failed to join: {e.response.text}{RESET}")
        return False


def print_help():
    print(f"""
  {BOLD}Commands:{RESET}
    {GREEN}<text>{RESET}            Send an action (what your character does/says)
    {CYAN}/ooc <text>{RESET}       Send out-of-character chat
    {DIM}/refresh{RESET}          Check for new messages
    {DIM}/history [n]{RESET}      Show last n messages (default 20)
    {DIM}/players{RESET}          List players in the game
    {DIM}/help{RESET}             Show this help
    {DIM}/quit{RESET}             Leave
""")


def game_loop(client: GameClient):
    """Main interactive game loop."""
    poller = MessagePoller(client)

    # Show recent history to catch up
    poller.show_history(50)

    # Start background polling
    poller.start()

    print_help()

    try:
        while True:
            text = prompt(f"  {client.agent_name}> ")

            if not text or text == "/refresh":
                count = poller.fetch_and_display()
                if count == 0 and text == "/refresh":
                    print(f"  {DIM}No new messages.{RESET}")
                continue

            if text == "/quit":
                print(f"  {DIM}Leaving game. Goodbye!{RESET}")
                break

            if text == "/help":
                print_help()
                continue

            if text == "/players":
                try:
                    players = client.get_players()
                    print(f"\n  {BOLD}Players:{RESET}")
                    for p in players:
                        role = f" {CYAN}(DM){RESET}" if p.get("role") == "dm" else ""
                        muted = f" {RED}[muted]{RESET}" if p.get("muted") else ""
                        print(f"    {p.get('character_name') or p.get('agent_name', '?')}{role}{muted}")
                    print()
                except Exception:
                    print(f"  {RED}Could not fetch player list.{RESET}")
                continue

            if text.startswith("/history"):
                parts = text.split()
                count = 20
                if len(parts) > 1:
                    try:
                        count = int(parts[1])
                    except ValueError:
                        pass
                poller.show_history(count)
                continue

            # Post a message
            if text.startswith("/ooc "):
                content = text[5:].strip()
                if content:
                    try:
                        client.post_message(content, "ooc")
                    except httpx.HTTPStatusError as e:
                        print(f"  {RED}Failed: {e.response.text}{RESET}")
            else:
                try:
                    client.post_message(text, "action")
                except httpx.HTTPStatusError as e:
                    print(f"  {RED}Failed: {e.response.text}{RESET}")

    finally:
        poller.stop()


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Join a play-by-post game as a human player")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="Server URL (default: http://localhost:8000)")
    parser.add_argument("--api-key", help="Existing API key (skip registration)")
    parser.add_argument("--game-id", help="Game ID to join directly")
    parser.add_argument("--character", help="Character name (used with --game-id)")
    args = parser.parse_args()

    client = GameClient(args.base_url.rstrip("/"))

    # Setup agent
    if args.api_key:
        client.api_key = args.api_key
        client.agent_name = "Player"
        print(f"  {GREEN}Using provided API key.{RESET}")
    else:
        if not setup_agent(client):
            sys.exit(1)

    # Join game
    if args.game_id:
        char_name = args.character or prompt("Your character name: ")
        if not char_name:
            sys.exit(1)
        try:
            client.join_game(args.game_id, char_name)
            print(f"  {GREEN}Joined game as {char_name}!{RESET}")
        except httpx.HTTPStatusError as e:
            print(f"  {RED}Failed to join: {e.response.text}{RESET}")
            sys.exit(1)
    else:
        if not choose_game(client):
            sys.exit(1)

    # Play
    game_loop(client)


if __name__ == "__main__":
    main()
