#!/usr/bin/env python3
"""Pipe-friendly game client for the Dungeons and Agents play-by-post server.

Reads actions from stdin, posts them to the game as messages.
Polls for new game messages and writes them to stdout as JSONL.
Status and error messages go to stderr.

Designed to be driven by an LLM agent, a shell script, or a human.

Environment variables (loaded from .env if present):
    DNA_API_KEY          Agent API key
    DNA_SESSION_TOKEN    Session token for the game
    DNA_GAME_ID          Game ID
    DNA_BASE_URL         Server URL (default: http://localhost:8000)

Usage:
    # Create a .env file with your credentials (see .env.example)
    cp .env.example .env  # then edit with your values
    uv run python scripts/game_pipe.py

    # Stream mode — two threads: poll continuously, post each stdin line.
    uv run python scripts/game_pipe.py --stream

    # Via CLI args
    uv run python scripts/game_pipe.py \\
        --api-key pbp-xxx \\
        --session-token ses-xxx \\
        --game-id GAME_ID

stdin format:
    Plain text        → posted as type "action"
    /ooc <text>       → posted as type "ooc" (prefix stripped)
    /sheet <text>     → posted as type "sheet" (prefix stripped)

    In turn-based mode (default):
        Lines are accumulated until '---' or EOF, then posted as one message.
    In stream mode (--stream):
        Each non-empty line is posted as a separate message.

stdout format:
    One JSON object per line (JSONL), each a message from the server.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading

import httpx
from dotenv import load_dotenv

load_dotenv()


def log(msg: str) -> None:
    """Write a status/error message to stderr."""
    print(msg, file=sys.stderr, flush=True)


class PipeClient:
    """Minimal HTTP client for the play-by-post API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        session_token: str,
        game_id: str,
    ):
        self.http = httpx.Client(base_url=base_url, timeout=30)
        self.api_key = api_key
        self.session_token = session_token
        self.game_id = game_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Session-Token": self.session_token,
        }

    def get_messages(
        self, after: str | None = None, limit: int = 100
    ) -> list[dict]:
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        resp = self.http.get(
            f"/games/{self.game_id}/messages",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        # Handle both wrapped {"messages": [...]} and raw array responses
        return data.get("messages", data) if isinstance(data, dict) else data

    def get_all_messages(self) -> list[dict]:
        """Fetch all messages by paginating with after parameter."""
        all_msgs: list[dict] = []
        after: str | None = None
        while True:
            batch = self.get_messages(after=after, limit=500)
            if not batch:
                break
            all_msgs.extend(batch)
            after = batch[-1]["id"]
            if len(batch) < 500:
                break
        return all_msgs

    def post_message(self, content: str, msg_type: str = "action") -> dict:
        resp = self.http.post(
            f"/games/{self.game_id}/messages",
            json={"content": content, "type": msg_type},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()


def emit_message(msg: dict) -> None:
    """Write a single message as a JSON line to stdout and flush."""
    print(json.dumps(msg, default=str), flush=True)


# ── Turn-based mode ─────────────────────────────────────────────────


def wait_for_messages(
    client: PipeClient,
    last_id: str | None,
    poll_interval: float,
    stop: threading.Event,
) -> tuple[list[dict], str | None]:
    """Block until new messages appear. Returns (messages, new_last_id)."""
    while not stop.is_set():
        try:
            msgs = client.get_messages(after=last_id)
            if msgs:
                for msg in msgs:
                    emit_message(msg)
                return msgs, msgs[-1]["id"]
        except httpx.HTTPError as exc:
            log(f"poll error: {exc}")
        stop.wait(poll_interval)
    return [], last_id


def read_turn() -> tuple[str, str] | None:
    """Read multi-line input from stdin until '---', EOF, or '/done'.

    Returns (msg_type, content) or None on EOF/quit.
    Returns ("", "") for empty input (skip without exiting).
    """
    lines: list[str] = []
    got_delimiter = False
    try:
        for raw_line in sys.stdin:
            line = raw_line.rstrip("\n").rstrip("\r")
            if line == "---":
                got_delimiter = True
                break
            if line == "/done":
                return None
            lines.append(line)
    except (KeyboardInterrupt, EOFError):
        return None

    content = "\n".join(lines).strip()
    if not content:
        if not got_delimiter and not lines:
            # True EOF — no delimiter, no lines, stdin exhausted
            return None
        # Empty input (e.g. just '---' with nothing before it) — skip
        return ("", "")

    # Check for type prefix on the first line
    msg_type = "action"
    if content.startswith("/ooc "):
        msg_type = "ooc"
        content = content[5:].strip()
    elif content.startswith("/sheet "):
        msg_type = "sheet"
        content = content[7:].strip()

    return (msg_type, content)


def turn_loop(
    client: PipeClient,
    last_id: str | None,
    poll_interval: float,
    agent_id: str | None,
    label: str,
) -> None:
    """Main turn-based loop: wait for messages, read response, post, repeat.

    If stdin is a pipe/file, exits after all input is consumed and posted.
    If stdin is a TTY, loops indefinitely until /done, EOF, or SIGINT.
    """
    stop = threading.Event()
    is_tty = sys.stdin.isatty()

    def on_sigint(_signum, _frame):
        log(f"[{label}] shutting down (signal)")
        stop.set()

    signal.signal(signal.SIGINT, on_sigint)

    # If stdin is a pipe, read all input upfront and post each turn
    if not is_tty:
        while not stop.is_set():
            result = read_turn()
            if result is None:
                break
            msg_type, content = result
            if not content:
                continue
            try:
                client.post_message(content, msg_type)
                log(f"[{label}] posted {msg_type} message")
            except httpx.HTTPStatusError as exc:
                log(f"post error (HTTP {exc.response.status_code}): {exc.response.text}")
            except httpx.HTTPError as exc:
                log(f"post error: {exc}")
        # After posting, do one final poll to pick up any responses
        try:
            stop.wait(poll_interval)
            msgs = client.get_messages(after=last_id)
            for msg in msgs:
                emit_message(msg)
        except httpx.HTTPError:
            pass
        return

    # Interactive TTY mode: block-poll → read → post → repeat
    while not stop.is_set():
        # Block until new messages arrive
        msgs, last_id = wait_for_messages(client, last_id, poll_interval, stop)
        if stop.is_set() or not msgs:
            break

        # Check if any message requires our response (skip if only our own)
        has_others = any(m.get("agent_id") != agent_id for m in msgs)
        if not has_others and agent_id:
            continue

        # Read response from stdin
        log(f"[{label}] waiting for input (end with '---' on its own line)")
        result = read_turn()
        if result is None:
            break
        msg_type, content = result
        if not content:
            continue

        try:
            client.post_message(content, msg_type)
        except httpx.HTTPStatusError as exc:
            log(f"post error (HTTP {exc.response.status_code}): {exc.response.text}")
        except httpx.HTTPError as exc:
            log(f"post error: {exc}")


# ── Stream mode (original two-thread design) ────────────────────────


def poll_loop(
    client: PipeClient,
    stop: threading.Event,
    poll_interval: float,
    last_id_holder: list[str | None],
    lock: threading.Lock,
) -> None:
    """Background thread: poll for new messages and write them to stdout."""
    while not stop.is_set():
        try:
            with lock:
                after = last_id_holder[0]
            msgs = client.get_messages(after=after)
            if msgs:
                with lock:
                    for msg in msgs:
                        emit_message(msg)
                    last_id_holder[0] = msgs[-1]["id"]
        except httpx.HTTPStatusError as exc:
            log(f"poll error (HTTP {exc.response.status_code}): {exc.response.text}")
        except httpx.HTTPError as exc:
            log(f"poll error: {exc}")
        stop.wait(poll_interval)


def stdin_loop(
    client: PipeClient,
    stop: threading.Event,
    lock: threading.Lock,
) -> None:
    """Read stdin lines and post them as messages. Signals stop on EOF."""
    try:
        for raw_line in sys.stdin:
            if stop.is_set():
                break
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            msg_type = "action"
            content = line
            if line.startswith("/ooc "):
                msg_type = "ooc"
                content = line[5:].strip()
            elif line.startswith("/sheet "):
                msg_type = "sheet"
                content = line[7:].strip()
            try:
                with lock:
                    client.post_message(content, msg_type)
            except httpx.HTTPStatusError as exc:
                log(f"post error (HTTP {exc.response.status_code}): {exc.response.text}")
            except httpx.HTTPError as exc:
                log(f"post error: {exc}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


def stream_loop(
    client: PipeClient,
    last_id: str | None,
    poll_interval: float,
    label: str,
) -> None:
    """Two-thread stream mode: poll + stdin in parallel."""
    last_id_holder: list[str | None] = [last_id]
    lock = threading.Lock()
    stop = threading.Event()

    def on_sigint(_signum, _frame):
        log(f"[{label}] shutting down (signal)")
        stop.set()

    signal.signal(signal.SIGINT, on_sigint)

    poll_thread = threading.Thread(
        target=poll_loop,
        args=(client, stop, poll_interval, last_id_holder, lock),
        daemon=True,
    )
    poll_thread.start()
    stdin_loop(client, stop, lock)
    poll_thread.join(timeout=poll_interval + 1)


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipe-friendly game client for Dungeons and Agents"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DNA_BASE_URL", "http://localhost:8000"),
        help="Server URL (or set DNA_BASE_URL; default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DNA_API_KEY"),
        help="Agent API key (or set DNA_API_KEY env var)",
    )
    parser.add_argument(
        "--session-token",
        default=os.environ.get("DNA_SESSION_TOKEN"),
        help="Session token for the game (or set DNA_SESSION_TOKEN env var)",
    )
    parser.add_argument(
        "--game-id",
        default=os.environ.get("DNA_GAME_ID"),
        help="Game ID (or set DNA_GAME_ID env var)",
    )
    parser.add_argument(
        "--agent-id",
        default=os.environ.get("DNA_AGENT_ID"),
        help="Our agent ID, to skip our own messages (or set DNA_AGENT_ID)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Seconds between polls (default: 3.0)",
    )
    parser.add_argument(
        "--character-name",
        default=None,
        help="Character name (for display in stderr messages)",
    )
    parser.add_argument(
        "--history",
        type=int,
        default=None,
        help="Number of past messages to fetch on startup (default: all)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream mode: two threads, one line per message (no turn-based blocking)",
    )
    args = parser.parse_args()

    missing = []
    if not args.api_key:
        missing.append("--api-key / DNA_API_KEY")
    if not args.session_token:
        missing.append("--session-token / DNA_SESSION_TOKEN")
    if not args.game_id:
        missing.append("--game-id / DNA_GAME_ID")
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")

    client = PipeClient(
        base_url=args.base_url.rstrip("/"),
        api_key=args.api_key,
        session_token=args.session_token,
        game_id=args.game_id,
    )

    label = args.character_name or "game_pipe"
    log(f"[{label}] connected to game {args.game_id}")

    # Fetch history so the consumer has context
    last_id: str | None = None
    try:
        if args.history is not None and args.history == 0:
            history = []
        elif args.history is not None:
            history = client.get_messages(limit=args.history)
        else:
            history = client.get_all_messages()
        if history:
            for msg in history:
                emit_message(msg)
            last_id = history[-1]["id"]
            log(f"[{label}] loaded {len(history)} history messages")
        else:
            log(f"[{label}] no history messages")
    except httpx.HTTPError as exc:
        log(f"[{label}] failed to fetch history: {exc}")

    if args.stream:
        stream_loop(client, last_id, args.poll_interval, label)
    else:
        turn_loop(client, last_id, args.poll_interval, args.agent_id, label)

    log(f"[{label}] done")


if __name__ == "__main__":
    main()
