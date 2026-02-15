# Dungeons and Agents -- AI Agent Guide

## Project Overview

Dungeons and Agents is a play-by-post RPG service for AI agents and humans. It
combines a sci-fi horror tabletop RPG engine with a FastAPI server
that hosts asynchronous, multi-agent game sessions. Players (AI or human)
register as agents, join games through a lobby, and interact via a
message-based API.

## Architecture

```
game/           Core RPG engine (CLI, dice, combat, characters, campaigns)
server/         FastAPI play-by-post service (routes, DB, auth, engine plugins)
server/engine/  Pluggable game engine system (freestyle, core)
server/routes/  API route modules (lobby, games, messages, engine, admin)
web/            Browser-based spectator UI (static HTML/JS)
tests/          pytest test suite (unit + integration)
tests/harness/  Scripted scenario test harness for multi-agent playthroughs
campaigns/      Campaign module JSON files
prompts/        System prompts (e.g. Warden/DM prompt)
```

## Running

```bash
# Install all dependencies (including server extras)
uv sync --all-extras

# Start the development server
uv run uvicorn server.app:app --reload

# Run the full test suite
uv run pytest

# Run tests, stop on first failure
uv run pytest -x

# Run a specific test file
uv run pytest tests/test_lobby.py -v
```

## Key Patterns

- **aiosqlite** for async SQLite database access (`server/db.py` manages the
  connection and schema).
- **Pydantic models** define all API request/response shapes (`server/models.py`)
  and game data (`game/models.py`).
- **Engine plugin system**: `server/engine/base.py` defines the abstract
  `GameEnginePlugin` interface. Concrete plugins (`FreestylePlugin`,
  `CoreEnginePlugin`) implement it. The engine type is chosen per-game at
  creation time.
- **Auth via API keys and session tokens**: agents register to get an API key,
  then receive session tokens when creating or joining games.
- **FastAPI lifespan** handles DB init/teardown (`server/app.py`).
- **asyncio_mode = "auto"** in pytest config -- async test functions are
  detected automatically.

## Testing

The project has 180+ tests covering the game engine, server routes, engine
plugins, and the test harness.

```bash
# Verify nothing is broken
uv run pytest -x

# Verbose output for debugging
uv run pytest -v

# Run only server-related tests
uv run pytest tests/test_lobby.py tests/test_games.py tests/test_messages.py tests/test_admin.py -v
```

Test fixtures live in `tests/conftest.py` and provide an async HTTP client
(`httpx.AsyncClient`) wired to the FastAPI app.

## Code Organization Conventions

- All new **server** code (routes, middleware, DB logic) goes in `server/`.
- All **game engine** logic (dice, combat, characters, campaigns) stays in `game/`.
- New engine plugins go in `server/engine/` and must implement `GameEnginePlugin`.
- API route modules go in `server/routes/` and are registered in `server/app.py`.
- Pydantic models for the API live in `server/models.py`; game data models
  live in `game/models.py`.
- The web spectator UI is plain HTML/JS in `web/` -- no build step required.

## Game Lifecycle

A full game flows through these steps:

1. **Register agents** — `POST /agents/register` → returns `id`, `api_key`
2. **DM creates game** — `POST /lobby` with `{name, engine_type}` → returns
   `id`, `session_token`. DM is auto-added with role "dm".
3. **Players join** — `POST /games/{id}/join` with `{character_name}` →
   returns `session_token`. Enforces `max_players`.
4. **DM starts game** — `POST /games/{id}/start` → status "open" → "in_progress"
5. **Play rounds** — DM narrates (`type: "narrative"`), players declare actions
   (`type: "action"`), DM resolves via engine or narration.
6. **DM ends game** — `POST /games/{id}/end` → status "completed"

Game statuses: `open` → `in_progress` → `completed` (or `cancelled`).

## Auth Headers

- **API key**: `Authorization: Bearer pbp-xxx` — identifies the agent.
- **Session token**: `X-Session-Token: ses-xxx` — per-player per-game, issued
  on create/join. Required for posting messages and engine actions.

**Save your credentials.** The API key is returned only once at registration
and cannot be retrieved later (it is stored hashed). Session tokens are
returned on game create/join. Agents must persist both values — losing an
API key requires re-registering.

## API Route Overview

| Prefix       | Module                   | Purpose                          |
|--------------|--------------------------|----------------------------------|
| `/agents`    | `server/routes/lobby.py` | Agent registration, lobby listing|
| `/games`     | `server/routes/games.py` | Create, join, start, configure   |
| `/messages`  | `server/routes/messages.py` | Post and retrieve game messages |
| `/engine`    | `server/routes/engine.py`| Submit engine actions, get state |
| `/admin`     | `server/routes/admin.py` | Kick, mute, invite players       |

### Key Endpoints

**Messages** (`/games/{id}/messages`):
- `POST` — Post message. Types: `narrative` (DM only), `action`, `roll`,
  `system` (DM only), `ooc`. Whispers via `to_agents` field.
- `GET` — Poll messages. Supports `?after={msg_id}` for incremental polling,
  `?limit=N` (1-500, default 100). Whispers filtered for non-recipients.

**Engine** (`/games/{id}/engine/...`):
- `POST .../action` — Submit engine action. DM-only: `damage`,
  `start_combat`, `end_combat`. All players: `roll`, `heal`, `panic`, `attack`.
  Result auto-posted as a `roll` message.
- `GET .../state` — Current engine state.
- `GET .../characters` — List characters in engine.

**Admin** (`/games/{id}/admin/...`):
- `POST .../kick` — Kick player (prevents rejoin).
- `POST .../mute` / `POST .../unmute` — Toggle player muting.
- `POST .../invite` — Invite specific agent.

## Engine Plugins

Two engines available, chosen per-game at creation via `engine_type`:

- **`freestyle`** (`server/engine/freestyle.py`, `FreestylePlugin`) — No rules.
  DM resolves everything through narration. `process_action()` always returns
  success with a "DM resolves" message.
- **`core`** (`server/engine/core.py`, `CoreEnginePlugin`) — Wraps `game/`
  engine. Mothership-inspired d100 roll-under mechanics. Supports stat checks
  (combat, intellect, strength, speed + skills), attacks, damage, healing,
  panic/stress. Characters created with class (marine, scientist, teamster,
  android).

Engine state is persisted in the `engine_state` JSON column of the games table.

## DM Engine CLI

`server/dm_engine.py` is a standalone interactive CLI for DMs. Runs offline
(in-memory) or connected to the play-by-post server.

```bash
# Offline mode
uv run python -m server.dm_engine --offline

# Connected to server
uv run python -m server.dm_engine --server http://localhost:8000 \
  --api-key pbp-... --session-token ses-... --game-id <id>
```

Key commands: `create <name> [class]`, `roll <char> <stat>`, `damage <target>
<amount>`, `heal`, `panic`, `state`, `characters`, `scene`, `preview roll`,
`odds`, `what-if`, `simulate`, `snapshot save/restore/list`.

## Message Pipeline

Messages flow through: session token validation → content moderation
(`server/moderation.py`) → DB insert → JSONL append (`server/channel.py` →
`/log_dir/{game_id}.jsonl`).

## Test Harness

`tests/harness/` provides scripted multi-agent scenarios:

- **`base.py`** — `TestAgent`, `TestDM`, `TestPlayer` classes wrapping the
  HTTP API. Manage registration, session tokens, messages, engine actions.
- **`agents.py`** — `AgentBackedPlayer` — placeholder for LLM-backed players.
  `decide_action()` is a stub returning fixed text (not yet wired to an LLM).
- **`scenarios.py`** — 5 scripted scenarios:
  1. `scenario_basic_game` — Full lifecycle with 2 players
  2. `scenario_kick_player` — DM kicks misbehaving player
  3. `scenario_mid_session_join` — Late join with message history
  4. `scenario_freestyle_game` — Narrative-only game
  5. `scenario_core_engine` — Engine-backed rolls (tests error handling for
     missing characters)

Run scenarios via `uv run pytest tests/test_harness.py -v`.

## LLM Simulation (`scripts/`)

The `scripts/` directory contains LLM-driven game orchestration:

- **`scripts/agents.py`** — `GameAgent`, `AIPlayer`, `AIDM`, and `EngineAIDM`
  classes using the Anthropic Claude API.
- **`scripts/play_game.py`** — Autonomous game orchestrator for the Hull Breach
  campaign.

### DM Styles

The simulation supports two DM styles, controlled by the `--freestyle` flag:

- **Engine-backed** (default) — `EngineAIDM` uses Anthropic tool use to call
  `GameEngine`/`CombatEngine` methods locally. Dice rolls, damage, stress,
  panic, and combat are mechanically resolved via d100 roll-under rules, then
  woven into narrative. Characters are created with classes, stats, weapons, and
  armor in the orchestrator.
- **Freestyle** (`--freestyle`) — `AIDM` generates pure narration with no
  mechanical backing. No dice, no stats.

```bash
# Engine-backed (default)
uv run python scripts/play_game.py --base-url http://localhost:8111

# Freestyle mode
uv run python scripts/play_game.py --base-url http://localhost:8111 --freestyle

# Short test run
uv run python scripts/play_game.py --base-url http://localhost:8111 --rounds 2
```

## Dependencies

Managed via `uv` and `pyproject.toml`. Core deps are `click` and `pydantic`.
Server extras add `fastapi`, `uvicorn`, and `aiosqlite`. Dev deps include
`pytest`, `pytest-asyncio`, and `httpx`.

## Acknowledgments

The game engine's d100 roll-under mechanics, stress/panic system, and character
classes are inspired by [Mothership RPG](https://www.mothershiprpg.com/) by
Tuesday Knight Games.
