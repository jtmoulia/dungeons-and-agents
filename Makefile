.PHONY: dev prod test test-x test-v deps deploy provision play lint

# --- Development ---

dev:  ## Start dev server with auto-reload
	uv run uvicorn server.app:app --reload

prod:  ## Start production server
	uv run uvicorn server.app:app --host 0.0.0.0 --port 8000

# --- Testing ---

test:  ## Run full test suite
	uv run pytest

test-x:  ## Run tests, stop on first failure
	uv run pytest -x

test-v:  ## Run tests with verbose output
	uv run pytest -v

# --- Dependencies ---

deps:  ## Install all dependencies (including optional extras)
	uv sync --all-extras

# --- Deployment ---

deploy:  ## Deploy latest code to production
	cd deploy && uv run --group deploy ansible-playbook -i inventory.ini deploy.yml

provision:  ## Full server provisioning (first-time setup)
	cd deploy && uv run --group deploy ansible-playbook -i inventory.ini playbook.yml

# --- Game ---

play:  ## Run LLM-driven game (pass ARGS, e.g. make play ARGS="--rounds 2")
	uv run python scripts/play_game.py --base-url http://localhost:8000 $(ARGS)

# --- Help ---

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
