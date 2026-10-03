# ControlProof developer commands. Implemented in A1: setup, dev, check, format, test.
# Targets marked "not implemented" fail on purpose so they never look like a passed check.

UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000
# Load .env for app commands only when it exists. Tests never load it.
WITH_ENV = $$(test -f .env && echo --env-file=.env)

.DEFAULT_GOAL := help
.PHONY: help setup dev check format test test-live verify benchmark reload-config reset-demo

help:
	@echo "setup      install locked dependencies, create .env if missing, initialise the database"
	@echo "dev        run the API and panel on http://$(HOST):$(PORT) (one process, one worker)"
	@echo "check      Ruff lint and format check"
	@echo "format     apply Ruff formatting and safe fixes"
	@echo "test       offline tests; network to TypeSafe and OpenAI is blocked"
	@echo "test-live  paid Jev and Luna tests (not implemented yet, B5)"
	@echo "verify     check + test + test-live"

setup:
	$(UV) sync --locked
	@test -f .env || { cp .env.example .env && chmod 600 .env && echo "Created .env from .env.example; fill in local values."; }
	$(UV) run $(WITH_ENV) python -m app.db

dev:
	$(UV) run $(WITH_ENV) uvicorn --factory app.main:create_app --host $(HOST) --port $(PORT)

check:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

test:
	$(UV) run pytest -m "not live"

test-live:
	@echo "test-live is not implemented yet (B5): no live verification was run." >&2; exit 1

verify: check test test-live

benchmark reload-config reset-demo:
	@echo "$@ is not implemented yet." >&2; exit 1
