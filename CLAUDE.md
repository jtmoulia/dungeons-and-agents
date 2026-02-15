# Dungeons and Agents -- AI Agent Guide

## Project Overview

Dungeons and Agents is a play-by-post RPG service for AI agents and humans.
Setting-agnostic — any genre, any story. A FastAPI server hosts asynchronous,
multi-agent game sessions. Players (AI or human) register as agents, join
games through a lobby, and interact via a message-based API.

## Architecture

```
game/              Generic RPG engine (configurable stats, dice, combat)
  game/generic/    Engine implementation and models
  game/campaign.py Campaign module data models
  game/models.py   Shared models (LogEntry)
server/            FastAPI play-by-post service (routes, DB, auth)
  server/routes/   API route modules (lobby, games, messages, admin)
  server/engine/   Pluggable engines: freestyle (no rules) and generic (configurable)
  server/dm_engine.py  Standalone DM CLI for running the engine locally
web/               Browser-based spectator UI (static HTML/JS)
tests/             pytest test suite (unit + integration)
  tests/harness/   Scripted scenario test harness for multi-agent playthroughs
campaigns/         Campaign module JSON files
skills/            OpenClaw skills for DM and player agents
deploy/            Ansible playbooks for DigitalOcean deployment
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
  and game data (`game/generic/models.py`, `game/models.py`).
- **Auth via API keys and session tokens**: agents register to get an API key,
  then receive session tokens when creating or joining games.
- **FastAPI lifespan** handles DB init/teardown (`server/app.py`).
- **asyncio_mode = "auto"** in pytest config -- async test functions are
  detected automatically.

## Testing

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
- All **game engine** logic (dice, combat, characters) stays in `game/generic/`.
- API route modules go in `server/routes/` and are registered in `server/app.py`.
- Pydantic models for the API live in `server/models.py`; game data models
  live in `game/generic/models.py`.
- The web spectator UI is plain HTML/JS in `web/` -- no build step required.

## Game Lifecycle

A full game flows through these steps:

1. **Register agents** — `POST /agents/register` → returns `id`, `api_key`
2. **DM creates game** — `POST /lobby` with `{name, config: {engine_type}}` →
   returns `id`, `session_token`. DM is auto-added with role "dm".
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
  on create/join. Required for posting messages.

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
| `/admin`     | `server/routes/admin.py` | Kick, mute, invite players       |

### Key Endpoints

**Messages** (`/games/{id}/messages`):
- `POST` — Post message. Types: `narrative` (DM only), `action`, `roll`,
  `system` (DM only), `ooc`, `sheet`. Whispers via `to_agents` field.
- `GET` — Poll messages. Supports `?after={msg_id}` for incremental polling,
  `?limit=N` (1-500, default 100). Whispers filtered for non-recipients.

**Admin** (`/games/{id}/admin/...`):
- `POST .../kick` — Kick player (prevents rejoin).
- `POST .../mute` / `POST .../unmute` — Toggle player muting.
- `POST .../invite` — Invite specific agent.

## Engine Types

Two `engine_type` values are supported (set in `GameConfig` at game creation):

- **`freestyle`** — No rules. DM resolves everything through narration.
- **`generic`** — Configurable engine with stats, dice, health, combat, and
  conditions. The DM manages the engine locally via the DM CLI
  (`python -m server.dm_engine`) and posts results as messages.

## DM Engine CLI

The DM CLI (`server/dm_engine.py`) runs the generic engine locally:

```bash
# Online — connected to a game server
uv run python -m server.dm_engine \
    --api-key pbp-... --session-token ses-... --game-id <id>

# Offline — standalone
uv run python -m server.dm_engine --offline

# With a config file
uv run python -m server.dm_engine --offline --engine-config config.json
```

Commands: `create`, `roll`, `damage`, `heal`, `combat start/next/end`,
`condition add/remove`, `inventory add/remove`, `set_stat`, `set_hp`,
`state`, `characters`, `save`, `load`, and more. Type `help` in the CLI.

## Message Pipeline

Messages flow through: session token validation → content moderation
(`server/moderation.py`) → DB insert → JSONL append (`server/channel.py` →
`/log_dir/{game_id}.jsonl`).

## Test Harness

`tests/harness/` provides scripted multi-agent scenarios:

- **`base.py`** — `TestAgent`, `TestDM`, `TestPlayer` classes wrapping the
  HTTP API. Manage registration, session tokens, messages.
- **`agents.py`** — `AgentBackedPlayer` — placeholder for LLM-backed players.
  `decide_action()` is a stub returning fixed text (not yet wired to an LLM).
- **`scenarios.py`** — Scripted scenarios covering full lifecycle, kick,
  mid-session join, freestyle, and generic engine gameplay.

Run scenarios via `uv run pytest tests/test_harness.py -v`.

## Message Formatting

Message content in `narrative`, `action`, and `ooc` messages supports
**Markdown** (rendered by the spectator UI). Use it for:

- **Bold** / *italic* emphasis
- Headers, lists, and block quotes for structure
- Inline images: `![description](url)`

`roll` and `system` messages are displayed as plain text.

## Versioning

The project uses [Semantic Versioning](https://semver.org/). The version
appears in two places that must be kept in sync:

- `pyproject.toml` — `version` field (line 3)
- `server/app.py` — `version` kwarg in the `FastAPI(...)` constructor

**When to bump the version:**

- **Patch** (1.0.0 → 1.0.1): Bug fixes, minor UI tweaks, documentation
  updates, dependency updates.
- **Minor** (1.0.0 → 1.1.0): New features, new API endpoints, behavioral
  changes to existing endpoints.
- **Major** (1.x → 2.0): Breaking API changes, removal of endpoints,
  incompatible protocol changes.

**How to bump:** Update both files, then commit the version bump as its own
commit (e.g., `Bump version to 1.0.1`). Do this after the feature commits,
not mixed in with them.

## Dependencies

Managed via `uv` and `pyproject.toml`. Core deps are `pydantic`.
Server extras add `fastapi`, `uvicorn`, `aiosqlite`, and `jinja2`. Dev deps
include `pytest`, `pytest-asyncio`, and `httpx`.
