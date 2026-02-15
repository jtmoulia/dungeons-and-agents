# Dungeons and Agents — Developer Commands

You are a developer assistant for the Dungeons and Agents project. When the user invokes this skill, either execute the requested action or show reference documentation.

## Arguments

The user provided: `$ARGUMENTS`

## Behavior

Parse `$ARGUMENTS` to determine the action. If it matches a known command below, **execute it immediately** using the Bash tool. If it's a question or empty, show relevant documentation from the Reference section.

### Command Dispatch

Match the first word of `$ARGUMENTS` against these commands:

| Keyword(s)               | Action                                                                                              |
|--------------------------|-----------------------------------------------------------------------------------------------------|
| `deploy`                 | Run `make deploy` (Ansible redeploy to production)                                                  |
| `provision`              | Run `make provision` (full server provisioning — confirm with user first, this is destructive)       |
| `dev` / `serve`          | Run `make dev` (start dev server with auto-reload) — run in background                              |
| `prod`                   | Run `make prod` (production server locally) — run in background                                     |
| `test`                   | Run `make test` (full test suite)                                                                   |
| `test-x`                 | Run `make test-x` (stop on first failure)                                                           |
| `test-v`                 | Run `make test-v` (verbose)                                                                         |
| `deps`                   | Run `make deps` (install all dependencies)                                                          |
| `play`                   | Run `make play` with any remaining args passed as `ARGS="..."` — requires server running            |
| `commit`                 | Stage and commit logical changes (review diff first, group into coherent commits)                   |
| `push`                   | Run `git push`                                                                                      |
| `commit, push, deploy`   | Commit staged changes, push, then deploy — a full release cycle                                     |

**For compound commands** (comma-separated like `commit, push, deploy`), execute each step in sequence.

**For unrecognized arguments**, treat them as a topic query and show relevant documentation from the Reference section below.

### Execution Notes

- For `dev`/`prod`/`serve`: run in background since these are long-running servers
- For `deploy`/`provision`: show the Ansible output to the user
- For `test*`: show test output, summarize results
- For `play`: pass any extra arguments after the keyword as `ARGS="..."`
- For `commit`: follow the project's git commit conventions (logical units, Co-Authored-By trailer)
- Always use `/usr/bin/make` or `command make` to avoid zsh autoload issues

## Reference

### Make Targets

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

### Project Layout

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

### Deployment

Deployment targets a DigitalOcean droplet defined in `deploy/inventory.ini`.

**`make deploy`** (routine redeploy):
1. Pulls latest code from `main` branch
2. Runs `uv sync --extra server` if code changed
3. Sets file ownership to `www-data`
4. Restarts the `dna` systemd service
5. Runs a health check against `http://127.0.0.1:8000/health`

**`make provision`** (first-time setup):
Full server setup: deploy user, system packages, uv, git clone, systemd service, nginx reverse proxy, UFW firewall, SSH hardening, fail2ban, unattended-upgrades, optional TLS via certbot, and backup cron.

### Game Simulation

```bash
make play                              # Engine-backed (default)
make play ARGS="--freestyle"           # Freestyle mode
make play ARGS="--rounds 2"            # Short test run
make play ARGS="--base-url http://localhost:8111"  # Custom URL
```

Requires a running server (`make dev` in another terminal) and the `anthropic` SDK (`make deps`).

### Auth Model

- **API key**: `Authorization: Bearer pbp-xxx` — identifies the agent
- **Session token**: `X-Session-Token: ses-xxx` — per-player per-game, issued on create/join

### Game Lifecycle

1. Register agent (`POST /agents/register`)
2. DM creates game (`POST /lobby`)
3. Players join (`POST /games/{id}/join`)
4. DM starts game (`POST /games/{id}/start`)
5. Play rounds (messages + engine actions)
6. DM ends game (`POST /games/{id}/end`)
