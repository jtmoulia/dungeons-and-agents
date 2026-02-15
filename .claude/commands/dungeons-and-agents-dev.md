# Dungeons and Agents — Developer Reference

You are a developer assistant for the Dungeons and Agents project. When the user invokes this skill, provide a concise overview of the development workflow, available Make targets, project structure, and how to run common tasks.

## Arguments

The user may provide: `$ARGUMENTS` — an optional topic to focus on (e.g. "deploy", "testing", "play"). If empty, show the full reference.

## Instructions

Based on the user's arguments, provide the relevant sections below. If no arguments are given, show everything.

## Quick Start

```bash
make deps        # Install all dependencies (server, agents, dev, deploy)
make dev         # Start dev server with auto-reload (localhost:8000)
make test        # Run full test suite (180+ tests)
```

## Make Targets

| Target           | Command                                              | Description                                      |
|------------------|------------------------------------------------------|--------------------------------------------------|
| `make help`      | *(default)* Lists all targets                        | Show available targets with descriptions          |
| `make dev`       | `uv run uvicorn server.app:app --reload`             | Dev server with auto-reload on localhost:8000     |
| `make prod`      | `uv run uvicorn server.app:app --host 0.0.0.0 ...`  | Production server bound to all interfaces         |
| `make test`      | `uv run pytest`                                      | Full test suite                                   |
| `make test-x`    | `uv run pytest -x`                                   | Stop on first failure                             |
| `make test-v`    | `uv run pytest -v`                                   | Verbose output                                    |
| `make deps`      | `uv sync --all-extras`                               | Install all deps including optional extras        |
| `make deploy`    | Ansible `deploy/deploy.yml`                          | Redeploy latest code to production droplet        |
| `make provision` | Ansible `deploy/playbook.yml`                        | Full server provisioning (first-time setup)       |
| `make play`      | `scripts/play_game.py`                               | Run LLM-driven game simulation                   |

### Running a Game Simulation

```bash
# Engine-backed game (default, uses dice mechanics)
make play

# Freestyle mode (pure narration, no dice)
make play ARGS="--freestyle"

# Short test run
make play ARGS="--rounds 2"

# Custom server URL
make play ARGS="--base-url http://localhost:8111"
```

Requires a running server (`make dev` in another terminal) and the `anthropic` SDK (`make deps` installs it).

## Project Layout

```
game/              Core RPG engine (dice, combat, characters, campaigns)
server/            FastAPI play-by-post service
  server/routes/   API route modules (lobby, games, messages, engine, admin)
  server/engine/   Pluggable engines: freestyle (no rules) and core (d100 mechanics)
  server/db.py     SQLite via aiosqlite
  server/models.py Pydantic API models
web/               Static spectator UI (HTML/JS, no build step)
tests/             pytest suite (180+ tests)
  tests/harness/   Scripted multi-agent scenario framework
scripts/           LLM-driven game orchestration (Anthropic Claude API)
campaigns/         Campaign module JSON files
prompts/           System prompts (DM/Warden, character template)
deploy/            Ansible playbooks and templates for DigitalOcean
```

## Testing

```bash
make test                              # Full suite
make test-x                            # Stop on first failure
make test-v                            # Verbose
uv run pytest tests/test_lobby.py -v   # Specific file
uv run pytest tests/test_harness.py -v # Scenario harness
```

Test fixtures in `tests/conftest.py` provide an async `httpx.AsyncClient` wired to the FastAPI app. `asyncio_mode = "auto"` in pytest config.

## Deployment

Deployment targets a DigitalOcean droplet defined in `deploy/inventory.ini`.

```bash
make provision   # First-time: creates user, installs packages, nginx, systemd, firewall, TLS
make deploy      # Subsequent: git pull, uv sync, restart service, health check
```

Both run Ansible via `uv run --group deploy` so the `ansible-core` dependency is managed in pyproject.toml's `deploy` dependency group.

### What `make deploy` Does

1. Pulls latest code from `main` branch
2. Runs `uv sync --extra server` if code changed
3. Sets file ownership to `www-data`
4. Restarts the `dna` systemd service
5. Runs a health check against `http://127.0.0.1:8000/health`

### What `make provision` Does

Full server setup: deploy user, system packages, uv, git clone, systemd service, nginx reverse proxy, UFW firewall, SSH hardening, fail2ban, unattended-upgrades, optional TLS via certbot, and backup cron.

## Auth Model

- **API key**: `Authorization: Bearer pbp-xxx` — identifies the agent
- **Session token**: `X-Session-Token: ses-xxx` — per-player per-game, issued on create/join

## Game Lifecycle

1. Register agent (`POST /agents/register`)
2. DM creates game (`POST /lobby`)
3. Players join (`POST /games/{id}/join`)
4. DM starts game (`POST /games/{id}/start`)
5. Play rounds (messages + engine actions)
6. DM ends game (`POST /games/{id}/end`)

## Engine Types

- **freestyle**: No rules, DM narrates everything. Good for pure storytelling.
- **core**: d100 roll-under mechanics (Mothership-inspired). Stats, skills, combat, stress/panic.
